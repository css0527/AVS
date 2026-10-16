"""Images must wait for timestamped TF without blocking the ROS executor."""
from collections import deque
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip('rclpy')
from rclpy.time import Time
from rclpy.clock import ClockType
from sensor_msgs.msg import Image
from avs_rescue_sim.vision_node import VisionNode


def test_image_waits_for_tf_at_original_timestamp():
    message = Image()
    message.header.stamp = Time(seconds=10.).to_msg()
    message.header.frame_id = 'camera_optical_frame'
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    clock = SimpleNamespace(now=lambda: Time(seconds=10.05, clock_type=ClockType.ROS_TIME))
    node = SimpleNamespace(frame_count=0, process_every_n=1,
        pending_images=deque(maxlen=8), get_clock=lambda: clock,
        tf_buffer=Mock(), map_frame='map',
        decode_image=Mock(return_value=frame), detect_hazards=Mock(),
        detect_barrier=Mock(), detect_tags=Mock(), publish_annotated=Mock())
    VisionNode.image_callback(node, message)
    VisionNode.process_pending_image(node)
    node.decode_image.assert_not_called()
    assert len(node.pending_images) == 1
    clock.now = lambda: Time(seconds=10.2, clock_type=ClockType.ROS_TIME)
    node.tf_buffer.can_transform.return_value=False
    VisionNode.process_pending_image(node)
    node.decode_image.assert_not_called()
    assert len(node.pending_images) == 1
    node.tf_buffer.can_transform.return_value=True
    VisionNode.process_pending_image(node)
    assert not node.pending_images
    assert node.detect_tags.call_args.args[2:] == ('camera_optical_frame', message.header.stamp)
    node.publish_annotated.assert_called_once()


def test_old_images_are_dropped_instead_of_using_latest_tf():
    message = Image()
    message.header.stamp = Time(seconds=10.).to_msg()
    node = SimpleNamespace(pending_images=deque([message]),
        get_clock=lambda: SimpleNamespace(now=lambda: Time(seconds=12., clock_type=ClockType.ROS_TIME)),
        decode_image=Mock())
    VisionNode.process_pending_image(node)
    node.decode_image.assert_not_called()
    assert not node.pending_images
