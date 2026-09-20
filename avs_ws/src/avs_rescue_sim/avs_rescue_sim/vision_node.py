#!/usr/bin/env python3
"""Hazard classification and AprilTag localization for the rescue course."""

import json

import cv2
import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener
from visualization_msgs.msg import Marker, MarkerArray


def rotate_vector(vector, quaternion):
    """Rotate a vector by a geometry_msgs quaternion without cv_bridge/tf helpers."""
    q = np.array([quaternion.x, quaternion.y, quaternion.z], dtype=np.float64)
    v = np.asarray(vector, dtype=np.float64)
    return v + 2.0 * np.cross(q, np.cross(q, v) + quaternion.w * v)


class VisionNode(Node):
    def __init__(self):
        super().__init__(
            'vision_node',
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )
        self.image_topic = self._param('image_topic', '/camera/image_raw')
        self.camera_info_topic = self._param('camera_info_topic', '/camera/camera_info')
        self.map_frame = self._param('map_frame', 'map')
        self.min_hazard_area = int(self._param('min_hazard_area', 900))
        self.tag_size = float(self._param('tag_size', 0.1875))
        self.process_every_n = max(1, int(self._param('process_every_n', 2)))
        self.marker_alpha = float(self._param('marker_smoothing_alpha', 0.35))
        self.hazard_names = list(self._param(
            'hazard_names', ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']))
        self.tag_labels = list(self._param(
            'tag_labels', ['COLLAPSE', 'TOXIC_LEAK', 'TRAPPED_PERSON', 'HIGH_TEMPERATURE']))

        default_ranges = {
            'FIRE': ([0, 110, 70], [7, 255, 255]),
            'CHEMICAL': ([8, 110, 80], [22, 255, 255]),
            'RADIATION': ([23, 110, 90], [38, 255, 255]),
            'ELECTRICAL': ([98, 110, 60], [125, 255, 255]),
            'BIOHAZARD': ([138, 90, 60], [170, 255, 255]),
        }
        self.hsv_ranges = {}
        for name in self.hazard_names:
            lower, upper = default_ranges[name]
            self.hsv_ranges[name] = (
                np.array(self._param(f'hsv.{name}.lower', lower), dtype=np.uint8),
                np.array(self._param(f'hsv.{name}.upper', upper), dtype=np.uint8),
            )

        self.detected_hazards = set()
        self.stable_tag_positions = {}
        self.camera_matrix = None
        self.distortion = None
        self.frame_count = 0

        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        detector_parameters = cv2.aruco.DetectorParameters()
        detector_parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.tag_detector = cv2.aruco.ArucoDetector(dictionary, detector_parameters)

        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.detection_pub = self.create_publisher(String, '/hazards/detections', 10)
        self.marker_pub = self.create_publisher(MarkerArray, '/hazards/core_markers', 10)
        self.annotated_pub = self.create_publisher(Image, '/camera/annotated', 10)
        self.create_subscription(CameraInfo, self.camera_info_topic, self.camera_info_callback,
                                 qos_profile_sensor_data)
        self.create_subscription(Image, self.image_topic, self.image_callback,
                                 qos_profile_sensor_data)
        self.get_logger().info(
            f'Vision ready: {self.image_topic}, five hazard classes, AprilTag 36h11 IDs 0-3')

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
        try:
            frame = self.decode_image(msg)
        except (ValueError, IndexError) as exc:
            self.get_logger().error(f'Cannot decode {msg.encoding} image: {exc}')
            return

        annotated = frame.copy()
        self.detect_hazards(frame, annotated)
        self.detect_tags(frame, annotated, msg.header.frame_id)
        self.publish_annotated(annotated, msg)

    def detect_hazards(self, frame, annotated):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        kernel = np.ones((5, 5), np.uint8)
        for name, (lower, upper) in self.hsv_ranges.items():
            mask = cv2.inRange(hsv, lower, upper)
            mask[int(mask.shape[0] * 0.86):, :] = 0
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(contour)
            if area < self.min_hazard_area:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            cv2.rectangle(annotated, (x, y), (x + width, y + height), (80, 255, 80), 3)
            cv2.putText(annotated, name, (x, max(28, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.75, (80, 255, 80), 2, cv2.LINE_AA)
            if name not in self.detected_hazards:
                self.detected_hazards.add(name)
                payload = {'kind': 'corridor_hazard', 'label': name, 'area_px': round(area, 1)}
                self.detection_pub.publish(String(data=json.dumps(payload)))
                self.get_logger().info(
                    f'[CORRIDOR {len(self.detected_hazards)}/5] detected {name} (area={area:.0f}px)')

    def detect_tags(self, frame, annotated, camera_frame):
        if self.camera_matrix is None:
            return
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
            if not ok or float(tvec[2]) <= 0.0:
                continue
            cv2.drawFrameAxes(annotated, self.camera_matrix, self.distortion,
                              rvec, tvec, self.tag_size * 0.5)
            map_position = self.to_map(tvec.reshape(3), camera_frame)
            if map_position is None:
                continue
            previous = self.stable_tag_positions.get(tag_id)
            if previous is None:
                stable = map_position
                first_detection = True
            else:
                stable = self.marker_alpha * map_position + (1.0 - self.marker_alpha) * previous
                first_detection = False
            self.stable_tag_positions[tag_id] = stable
            if first_detection:
                label = self.tag_labels[tag_id]
                self.detection_pub.publish(String(data=json.dumps({
                    'kind': 'core_hazard', 'tag_id': tag_id, 'label': label,
                    'map_x': round(float(stable[0]), 3), 'map_y': round(float(stable[1]), 3),
                })))
                self.get_logger().info(
                    f'[CORE] AprilTag {tag_id} {label} at map ({stable[0]:.2f}, {stable[1]:.2f})')
        self.publish_markers()

    def to_map(self, camera_point, camera_frame):
        camera_frame = camera_frame or 'camera_optical_frame'
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame, camera_frame, rclpy.time.Time(), timeout=Duration(seconds=0.08))
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
            text.pose.position.x = float(position[0])
            text.pose.position.y = float(position[1])
            text.pose.position.z = 0.34
            text.pose.orientation.w = 1.0
            text.scale.z = 0.13
            text.color.r = text.color.g = text.color.b = text.color.a = 1.0
            text.text = f'TAG {tag_id}: {self.tag_labels[tag_id]}'
            markers.markers.append(text)
        self.marker_pub.publish(markers)

    def publish_annotated(self, frame, source):
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
