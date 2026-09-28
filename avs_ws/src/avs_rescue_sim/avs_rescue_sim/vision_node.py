#!/usr/bin/env python3
"""Hazard classification and AprilTag localization for the rescue course."""

import json
from collections import deque
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from avs_rescue_sim.hazard_classifier import HazardClassifier
from avs_rescue_sim.barrier_detector import BarrierDetector
from avs_rescue_sim.hazard_tracker import HazardTracker

import cv2
import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener
from visualization_msgs.msg import Marker, MarkerArray


def rotate_vector(vector, quaternion):
    """Rotate a vector by a geometry_msgs quaternion without cv_bridge/tf helpers."""
    q = np.array([quaternion.x, quaternion.y, quaternion.z], dtype=np.float64)
    v = np.asarray(vector, dtype=np.float64)
    return v + 2.0 * np.cross(q, np.cross(q, v) + quaternion.w * v)


def annotate_label(frame, lines, anchor, color):
    """Keep recognition text readable even when a target is near an image edge."""
    scale, thickness, spacing = .52, 1, 21
    width = max(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0]
                for line in lines) + 12
    height = spacing * len(lines) + 8
    x = max(0, min(int(anchor[0]), frame.shape[1] - width))
    y = max(0, min(int(anchor[1]) - height, frame.shape[0] - height))
    cv2.rectangle(frame, (x, y), (x + width, y + height), (20, 25, 30), -1)
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (x + 6, y + 20 + index * spacing),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


class VisionNode(Node):
    def __init__(self):
        super().__init__(
            'vision_node',
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )
        cv2.setNumThreads(2)
        self.image_topic = self._param('image_topic', '/camera/image_raw')
        self.camera_info_topic = self._param('camera_info_topic', '/camera/camera_info')
        self.map_frame = self._param('map_frame', 'map')
        self.min_hazard_area = int(self._param('min_hazard_area', 900))
        self.tag_size = float(self._param('tag_size', 0.1875))
        self.process_every_n = max(1, int(self._param('process_every_n', 2)))
        self.marker_alpha = float(self._param('marker_smoothing_alpha', 0.35))
        self.core_bounds = list(self._param('core_bounds', [1.15, 0.05, 2.95, 1.85]))
        self.tag_samples = {}
        self.tag_confirmations = int(self._param('tag_confirmation_frames', 4))
        self.max_reprojection_error = float(self._param('max_reprojection_error', 2.5))
        self.hazard_names = list(self._param(
            'hazard_names', ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']))
        self.tag_labels = list(self._param(
            'tag_labels', ['COLLAPSE', 'TOXIC_LEAK', 'TRAPPED_PERSON', 'HIGH_TEMPERATURE']))
        share = Path(get_package_share_directory('avs_rescue_sim'))
        self.hazard_backend = str(self._param('hazard_backend', 'yolov5')).lower()
        if self.hazard_backend == 'yolov5':
            try:
                from avs_rescue_sim.yolov5_detector import YoloV5Detector
                from avs_rescue_sim.panel_geometry import PanelGeometryVerifier
                configured_weights = str(self._param('yolov5_weights', '')).strip()
                weights = (Path(configured_weights) if configured_weights else
                           share / 'models/yolov5/hazard_yolov5.torchscript')
                self.hazard_classifier = YoloV5Detector(
                    weights, self.hazard_names,
                    image_size=int(self._param('yolov5_image_size', 320)),
                    confidence=float(self._param('yolov5_confidence', .45)),
                    iou_threshold=float(self._param('yolov5_iou_threshold', .45)),
                    min_area=float(self._param('yolov5_min_area', 80)),
                    panel_verifier=PanelGeometryVerifier(
                        share / 'models/rescue_course/materials/textures', self.hazard_names,
                        symbol_score=float(self._param('panel_symbol_score', .34))))
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                if not bool(self._param('allow_sift_fallback', True)):
                    raise
                self.get_logger().warning(f'YOLOv5 unavailable ({exc}); using SIFT fallback')
                self.hazard_backend = 'sift'
        if self.hazard_backend == 'sift':
            self.hazard_classifier = HazardClassifier(
                share / 'models/rescue_course/materials/textures', self.hazard_names,
                min_inliers=int(self._param('min_pattern_inliers', 7)),
                min_area=self.min_hazard_area)
        elif self.hazard_backend != 'yolov5':
            raise ValueError(f'Unknown hazard_backend: {self.hazard_backend}')
        self.hazard_tracker = HazardTracker(
            smoothing_alpha=float(self._param('hazard_box_smoothing_alpha', .65)),
            max_center_step=float(self._param('hazard_max_center_step', .18)))
        self.hazard_display_frames = max(1, int(self._param('hazard_display_frames', 2)))
        self.barrier_detector = BarrierDetector(
            min_area=int(self._param('barrier_min_area', 700)),
            min_fill=float(self._param('barrier_min_fill', .82)),
            max_white_fraction=float(self._param('barrier_max_white_fraction', .08)))
        self.visible_hazard_polygons = []
        self.visible_barriers = []
        self.confirmation_frames = int(self._param('confirmation_frames', 3))

        self.detected_hazards = set()
        self.stable_tag_positions = {}
        self.camera_matrix = None
        self.distortion = None
        self.frame_count = 0
        self.core_visible = False
        self.pending_images = deque(maxlen=8)

        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        detector_parameters = cv2.aruco.DetectorParameters()
        detector_parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.tag_detector = cv2.aruco.ArucoDetector(dictionary, detector_parameters)

        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = TransformListener(self.tf_buffer, self)
        # Retain all nine discoveries for the mission, which starts later.
        detection_qos = QoSProfile(depth=20, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.detection_pub = self.create_publisher(String, '/hazards/detections', detection_qos)
        self.marker_pub = self.create_publisher(MarkerArray, '/hazards/core_markers', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.annotated_pub = self.create_publisher(Image, '/camera/annotated', 10)
        self.obstacle_pub = self.create_publisher(String, '/obstacles/detections', 10)
        self.create_subscription(CameraInfo, self.camera_info_topic, self.camera_info_callback,
                                 qos_profile_sensor_data)
        self.create_subscription(Image, self.image_topic, self.image_callback,
                                 qos_profile_sensor_data)
        self.create_timer(0.5, self.publish_markers)
        self.create_timer(0.04, self.process_pending_image)
        self.get_logger().info(
            f'Vision ready: {self.image_topic}, hazard backend={self.hazard_backend}, '
            'five hazard classes, AprilTag 36h11 IDs 0-3')

    def _param(self, name, default):
        parameter = self.get_parameter(name)
        return parameter.value if parameter.type_ != parameter.Type.NOT_SET else default

    def camera_info_callback(self, msg):
        self.camera_matrix = np.asarray(msg.k, dtype=np.float64).reshape(3, 3)
        self.distortion = np.asarray(msg.d, dtype=np.float64)

    @staticmethod
    def decode_image(msg):
        channels = 3 if msg.encoding.lower() in ('rgb8', 'bgr8') else 4
        raw = np.frombuffer(msg.data, dtype=np.uint8)
        rows = raw.reshape(msg.height, msg.step)
        frame = rows[:, :msg.width * channels].reshape(msg.height, msg.width, channels).copy()
        encoding = msg.encoding.lower()
        if encoding == 'rgb8':
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if encoding in ('rgba8', 'bgra8'):
            code = cv2.COLOR_RGBA2BGR if encoding == 'rgba8' else cv2.COLOR_BGRA2BGR
            return cv2.cvtColor(frame, code)
        return frame[:, :, :3]

    def image_callback(self, msg):
        self.frame_count += 1
        if self.frame_count % self.process_every_n:
            return
        self.pending_images.append(msg)

    def process_pending_image(self):
        if not self.pending_images:
            return
        msg = self.pending_images[0]
        age = (self.get_clock().now() - rclpy.time.Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
        # Sensor messages can precede the joint/odometry TF for their timestamp.
        # A synchronous TF wait cannot receive those callbacks on this executor.
        if age < 0.15:
            return
        if age > 1.0:
            self.pending_images.popleft()
            return
        if not self.tf_buffer.can_transform(self.map_frame,
                msg.header.frame_id or 'camera_optical_frame',
                rclpy.time.Time.from_msg(msg.header.stamp)):
            return
        self.pending_images.popleft()
        try:
            frame = self.decode_image(msg)
        except (ValueError, IndexError) as exc:
            self.get_logger().error(f'Cannot decode {msg.encoding} image: {exc}')
            return

        annotated = frame.copy()
        self.detect_hazards(frame, annotated)
        self.detect_barrier(frame, annotated, msg.header)
        self.detect_tags(frame, annotated, msg.header.frame_id, msg.header.stamp)
        self.publish_annotated(annotated, msg)

    def detect_hazards(self, frame, annotated):
        self.visible_hazard_polygons = []
        tracks = self.hazard_tracker.update(self.hazard_classifier.detect(frame), frame.shape)
        for track in tracks:
            name, inliers, area = track.name, track.score, track.area
            polygon = np.rint(track.polygon).astype(np.int32)
            # Exclude validated panels from red-box detection even during the
            # short display warm-up, otherwise a red sign can become a box.
            self.visible_hazard_polygons.append(polygon)
            if track.streak < self.hazard_display_frames:
                continue
            cv2.polylines(annotated, [polygon], True, (80, 255, 80), 2)
            x, y = polygon.reshape(-1, 2).min(axis=0)
            if name not in self.detected_hazards and track.streak >= self.confirmation_frames:
                self.detected_hazards.add(name)
                payload = {'kind': 'corridor_hazard', 'label': name,
                           'area_px': round(area, 1), 'detector': self.hazard_backend}
                if self.hazard_backend == 'yolov5':
                    payload['confidence'] = round(float(inliers), 4)
                else:
                    payload['pattern_inliers'] = int(inliers)
                self.detection_pub.publish(String(data=json.dumps(payload)))
                metric = (f'YOLOv5 confidence {inliers:.2f}' if self.hazard_backend == 'yolov5'
                          else f'artwork matching ({inliers} inliers)')
                self.get_logger().info(
                    f'[CORRIDOR {len(self.detected_hazards)}/5] confirmed {name} with {metric}')
            detail = (f'{name}  {inliers:.2f}' if self.hazard_backend == 'yolov5'
                      else f'{name}  {int(inliers)} matches')
            if name not in self.detected_hazards:
                detail += f' [{track.streak}/{self.confirmation_frames}]'
            # Put the caption below signs near the top edge, leaving the
            # white pictogram visible in the first-person camera view.
            caption_y = y if y >= 29 else polygon.reshape(-1, 2).max(axis=0)[1] + 29
            annotate_label(annotated, [detail],
                           (x, caption_y), (80, 255, 80))

    def detect_barrier(self, frame, annotated, header):
        self.visible_barriers = self.barrier_detector.detect(frame, self.visible_hazard_polygons)
        for x, y, w, h in self.visible_barriers:
            cv2.rectangle(annotated, (x, y), (x + w - 1, y + h - 1), (255, 100, 255), 3)
            annotate_label(annotated, ['PUSH BARRIER'], (x, y), (255, 100, 255))
        # Image measurements only; an empty list explicitly clears stale boxes.
        self.obstacle_pub.publish(String(data=json.dumps({
            'kind': 'push_barrier', 'frame_id': header.frame_id,
            'stamp': {'sec': header.stamp.sec, 'nanosec': header.stamp.nanosec},
            'boxes': [{'x': x, 'y': y, 'width': w, 'height': h}
                      for x, y, w, h in self.visible_barriers],
        })))

    def detect_tags(self, frame, annotated, camera_frame, stamp=None):
        self.core_visible = False
        if self.camera_matrix is None:
            return
        # Core scoring begins after entering the rescue room. No layout ground
        # truth is used to estimate tags; this rectangle only defines task phase.
        base = self.to_map(np.zeros(3), 'base_link', stamp)
        if base is None or not (self.core_bounds[0] < base[0] < self.core_bounds[2]
                               and self.core_bounds[1] < base[1] < self.core_bounds[3]):
            return
        self.core_visible = True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.tag_detector.detectMarkers(gray)
        if ids is None:
            return
        cv2.aruco.drawDetectedMarkers(annotated, corners, ids)
        half = self.tag_size / 2.0
        object_points = np.array([
            [-half, half, 0.0], [half, half, 0.0],
            [half, -half, 0.0], [-half, -half, 0.0],
        ], dtype=np.float32)
        for image_corners, tag_id_raw in zip(corners, ids.flatten()):
            tag_id = int(tag_id_raw)
            if tag_id < 0 or tag_id >= len(self.tag_labels):
                continue
            ok, rvec, tvec = cv2.solvePnP(
                object_points, image_corners.reshape(4, 2).astype(np.float32),
                self.camera_matrix, self.distortion, flags=cv2.SOLVEPNP_IPPE_SQUARE)
            if not ok or float(tvec[2, 0]) <= 0.0:
                continue
            reprojection, _ = cv2.projectPoints(object_points, rvec, tvec,
                                               self.camera_matrix, self.distortion)
            error = np.linalg.norm(reprojection.reshape(4, 2) - image_corners.reshape(4, 2), axis=1).mean()
            if not np.isfinite(tvec).all() or error > self.max_reprojection_error:
                continue
            cv2.drawFrameAxes(annotated, self.camera_matrix, self.distortion,
                              rvec, tvec, self.tag_size * 0.5)
            map_position = self.to_map(tvec.reshape(3), camera_frame, stamp)
            if map_position is None:
                continue
            previous = self.stable_tag_positions.get(tag_id)
            if previous is not None and np.linalg.norm(map_position[:2] - previous[:2]) > .20:
                continue
            samples = self.tag_samples.setdefault(tag_id, [])
            samples.append(map_position)
            del samples[:-20]
            if len(samples) < self.tag_confirmations:
                annotate_label(annotated,
                    [f'T{tag_id} {self.tag_labels[tag_id]}',
                     f'confirming {len(samples)}/{self.tag_confirmations}'],
                    image_corners.reshape(4, 2).min(axis=0), (0, 220, 255))
                continue
            map_position = np.median(samples, axis=0)
            if previous is None:
                stable = map_position
                first_detection = True
            else:
                stable = self.marker_alpha * map_position + (1.0 - self.marker_alpha) * previous
                first_detection = False
            self.stable_tag_positions[tag_id] = stable
            annotate_label(annotated,
                [f'T{tag_id} {self.tag_labels[tag_id]}',
                 f'MARKER T{tag_id} | map ({stable[0]:.2f}, {stable[1]:.2f}) m'],
                image_corners.reshape(4, 2).min(axis=0), (80, 255, 80))
            if first_detection:
                label = self.tag_labels[tag_id]
                self.detection_pub.publish(String(data=json.dumps({
                    'kind': 'core_hazard', 'tag_id': tag_id, 'label': label,
                    'map_x': round(float(stable[0]), 3), 'map_y': round(float(stable[1]), 3),
                })))
                self.get_logger().info(
                    f'[CORE] AprilTag {tag_id} {label} at map ({stable[0]:.2f}, {stable[1]:.2f})')
        self.publish_markers()

    def to_map(self, camera_point, camera_frame, stamp=None):
        camera_frame = camera_frame or 'camera_optical_frame'
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame, camera_frame,
                rclpy.time.Time.from_msg(stamp) if stamp is not None else rclpy.time.Time(),
                timeout=Duration(seconds=0.0))
        except TransformException as exc:
            self.get_logger().debug(f'TF {self.map_frame} <- {camera_frame} unavailable: {exc}')
            return None
        rotated = rotate_vector(camera_point, transform.transform.rotation)
        translation = transform.transform.translation
        return rotated + np.array([translation.x, translation.y, translation.z])

    def publish_markers(self):
        markers = MarkerArray()
        stamp = self.get_clock().now().to_msg()
        colors = [(0.88, 0.12, 0.10), (0.95, 0.62, 0.05),
                  (0.10, 0.55, 0.95), (0.68, 0.15, 0.78)]
        for tag_id, position in sorted(self.stable_tag_positions.items()):
            marker = Marker()
            marker.header.frame_id = self.map_frame
            marker.header.stamp = stamp
            marker.ns = 'core_hazard'
            marker.id = tag_id
            marker.type = Marker.CUBE
            marker.action = Marker.ADD
            marker.pose.position.x = float(position[0])
            marker.pose.position.y = float(position[1])
            marker.pose.position.z = 0.12
            marker.pose.orientation.w = 1.0
            marker.scale.x = marker.scale.y = marker.scale.z = 0.16
            marker.color.r, marker.color.g, marker.color.b = colors[tag_id]
            marker.color.a = 0.95
            markers.markers.append(marker)
            text = Marker()
            text.header = marker.header
            text.ns = 'core_hazard_label'
            text.id = tag_id + 100
            text.type = Marker.TEXT_VIEW_FACING
            text.action = Marker.ADD
            # Put readable IDs inside the room; cube centres retain the actual
            # PnP estimate, while full class names are printed in detections.
            text.pose.position.x = float(position[0]) - (0.18 if tag_id < 2 else 0.0)
            text.pose.position.y = float(position[1]) + (0.18 if tag_id >= 2 else 0.0)
            text.pose.position.z = 0.34
            text.pose.orientation.w = 1.0
            text.scale.z = 0.09
            text.color.r = text.color.g = text.color.b = text.color.a = 1.0
            text.text = f'T{tag_id}'
            markers.markers.append(text)
        self.marker_pub.publish(markers)

    def publish_annotated(self, frame, source):
        # Counts are confirmed discoveries, not detections invented by the UI.
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, h - 28), (w, h), (20, 25, 30), -1)
        phase = 'CORE ROOM' if self.core_visible else 'CORRIDOR / RETURN'
        cv2.putText(frame,
                    f'{phase} | confirmed {len(self.detected_hazards)}/5 | markers {len(self.stable_tag_positions)}/4',
                    (8, h - 9), cv2.FONT_HERSHEY_SIMPLEX, .48,
                    (235, 245, 250), 1, cv2.LINE_AA)
        output = Image()
        output.header = source.header
        output.height, output.width = frame.shape[:2]
        output.encoding = 'bgr8'
        output.is_bigendian = False
        output.step = output.width * 3
        output.data = frame.tobytes()
        self.annotated_pub.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = VisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
