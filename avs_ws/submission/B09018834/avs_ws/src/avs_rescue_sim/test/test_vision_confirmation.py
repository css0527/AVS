"""Core discoveries require room entry, repeated PnP, and matching map markers."""
import json
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip('rclpy')
from rclpy.time import Time
from tf2_ros import TransformException
from visualization_msgs.msg import Marker
from avs_rescue_sim.vision_node import VisionNode


def make_node(tag_id=0, base_position=(2.0, 1.0, 0.0)):
    """Use real projection/PnP and map conversion without creating a ROS node."""
    camera_matrix = np.array([[450., 0., 320.], [0., 450., 240.], [0., 0., 1.]])
    tag_size = .1875
    half = tag_size / 2
    object_points = np.array([
        [-half, half, 0.], [half, half, 0.],
        [half, -half, 0.], [-half, -half, 0.],
    ], dtype=np.float32)
    camera_position = np.array([.03, -.015, .85])
    corners, _ = cv2.projectPoints(
        object_points, np.array([3.05, .12, .04]), camera_position,
        camera_matrix, np.zeros(5))
    corners = corners.reshape(1, 4, 2).astype(np.float32)
    camera_translation = np.array([1.5, .8, 0.])

    def lookup_transform(target, source, stamp, timeout):
        assert target == 'map'
        position = base_position if source == 'base_link' else camera_translation
        return SimpleNamespace(transform=SimpleNamespace(
            rotation=SimpleNamespace(x=0., y=0., z=0., w=1.),
            translation=SimpleNamespace(x=position[0], y=position[1], z=position[2])))

    node = SimpleNamespace(
        camera_matrix=camera_matrix, distortion=np.zeros(5), tag_size=tag_size,
        core_bounds=[1.15, .05, 2.95, 1.85], core_visible=False,
        tag_labels=['COLLAPSE', 'TOXIC_LEAK', 'TRAPPED_PERSON', 'HIGH_TEMPERATURE'],
        tag_samples={}, stable_tag_positions={}, tag_confirmations=4,
        max_reprojection_error=2.5, marker_alpha=.35, map_frame='map',
        tag_detector=Mock(), tf_buffer=Mock(),
        detection_pub=Mock(), marker_pub=Mock(),
        get_logger=lambda: Mock(),
        get_clock=lambda: SimpleNamespace(now=lambda: Time(seconds=12.)),
    )
    node.tag_detector.detectMarkers.return_value = (
        [corners], np.array([[tag_id]], dtype=np.int32), [])
    node.tf_buffer.lookup_transform.side_effect = lookup_transform
    node.to_map = MethodType(VisionNode.to_map, node)
    node.publish_markers = MethodType(VisionNode.publish_markers, node)
    return node, camera_translation + camera_position


def detect(node):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    VisionNode.detect_tags(node, frame, frame.copy(), 'camera_optical_frame',
                           Time(seconds=10.).to_msg())


@pytest.mark.parametrize('base_position', [
    (.55, 1.4, 0.), (1.5, 2.5, 0.), (1.15, 1., 0.), (2., 1.85, 0.),
])
def test_core_tags_require_base_inside_room(base_position):
    node, _ = make_node(base_position=base_position)
    detect(node)
    node.tag_detector.detectMarkers.assert_not_called()
    node.detection_pub.publish.assert_not_called()
    node.marker_pub.publish.assert_not_called()
    assert not node.tag_samples
    assert not node.stable_tag_positions


@pytest.mark.parametrize('tag_id', range(4))
def test_repeated_valid_pnp_confirms_tag_and_publishes_matching_marker(tag_id):
    node, expected_map_position = make_node(tag_id)
    for sample_count in range(1, node.tag_confirmations):
        detect(node)
        assert len(node.tag_samples[tag_id]) == sample_count
        assert tag_id not in node.stable_tag_positions
        node.detection_pub.publish.assert_not_called()
        assert not node.marker_pub.publish.call_args.args[0].markers

    detect(node)
    np.testing.assert_allclose(node.stable_tag_positions[tag_id], expected_map_position,
                               atol=1e-5)
    node.detection_pub.publish.assert_called_once()
    payload = json.loads(node.detection_pub.publish.call_args.args[0].data)
    assert payload['kind'] == 'core_hazard'
    assert payload['tag_id'] == tag_id
    assert payload['label'] == node.tag_labels[tag_id]
    assert payload['map_x'] == pytest.approx(expected_map_position[0], abs=.001)
    assert payload['map_y'] == pytest.approx(expected_map_position[1], abs=.001)

    markers = node.marker_pub.publish.call_args.args[0].markers
    cube, label = markers
    assert (cube.ns, cube.id, cube.type) == ('core_hazard', tag_id, Marker.CUBE)
    assert cube.header.frame_id == 'map'
    assert cube.pose.position.x == pytest.approx(expected_map_position[0], abs=1e-5)
    assert cube.pose.position.y == pytest.approx(expected_map_position[1], abs=1e-5)
    assert (label.ns, label.id, label.text) == ('core_hazard_label', tag_id + 100, f'T{tag_id}')

    # Further observations update the map marker without duplicating discoveries.
    detect(node)
    node.detection_pub.publish.assert_called_once()
    assert node.marker_pub.publish.call_args.args[0].markers[0].id == tag_id


def test_missing_image_transform_does_not_count_towards_confirmation():
    node, _ = make_node()
    detect(node)
    original_lookup = node.tf_buffer.lookup_transform.side_effect

    def unavailable_camera(target, source, stamp, timeout):
        if source == 'camera_optical_frame':
            raise TransformException('camera TF for this exposure has not arrived')
        return original_lookup(target, source, stamp, timeout)

    node.tf_buffer.lookup_transform.side_effect = unavailable_camera
    for _ in range(node.tag_confirmations):
        detect(node)
    assert len(node.tag_samples[0]) == 1
    assert not node.stable_tag_positions
    node.detection_pub.publish.assert_not_called()

    node.tf_buffer.lookup_transform.side_effect = original_lookup
    for _ in range(node.tag_confirmations - 1):
        detect(node)
    assert 0 in node.stable_tag_positions
    node.detection_pub.publish.assert_called_once()
