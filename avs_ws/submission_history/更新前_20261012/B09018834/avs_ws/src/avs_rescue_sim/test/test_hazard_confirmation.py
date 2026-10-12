"""A painted proposal alone cannot become a confirmed corridor discovery."""
import json
from types import SimpleNamespace

import numpy as np

from avs_rescue_sim.hazard_tracker import HazardTracker
from avs_rescue_sim.vision_node import VisionNode


def proposal(x=100):
    polygon = np.int32([[x, 80], [x+50, 80], [x+50, 130], [x, 130]]).reshape(-1, 1, 2)
    return 'RADIATION', polygon, .91, 2500.


def harness():
    messages = []
    logger = SimpleNamespace(info=lambda *_: None)
    frame_detections = []
    node = SimpleNamespace(
        visible_hazard_polygons=[],
        hazard_classifier=SimpleNamespace(detect=lambda _frame: frame_detections),
        hazard_tracker=HazardTracker(),
        hazard_display_frames=2,
        confirmation_frames=3,
        detected_hazards=set(),
        detection_pub=SimpleNamespace(publish=lambda message: messages.append(json.loads(message.data))),
        hazard_backend='yolov5',
        get_logger=lambda: logger,
    )

    def process(detections):
        frame_detections[:] = detections
        frame = np.full((480, 640, 3), 30, np.uint8)
        annotated = frame.copy()
        VisionNode.detect_hazards(node, frame, annotated)
        return annotated

    return node, messages, process


def test_three_consecutive_spatial_observations_publish_once():
    node, messages, process = harness()
    first = process([proposal()])
    assert np.array_equal(first, np.full_like(first, 30))
    assert not messages
    assert len(node.visible_hazard_polygons) == 1
    process([proposal(105)])
    assert not messages
    process([proposal(110)])
    assert [item['label'] for item in messages] == ['RADIATION']
    assert messages[0]['detector'] == 'yolov5'
    process([proposal(115)])
    assert len(messages) == 1


def test_disappearing_or_unrelated_spatial_proposals_reset_confirmation():
    node, messages, process = harness()
    process([proposal(100)])
    process([proposal(100)])
    process([])
    assert node.visible_hazard_polygons == []
    process([proposal(450)])
    process([proposal(100)])
    assert messages == []
