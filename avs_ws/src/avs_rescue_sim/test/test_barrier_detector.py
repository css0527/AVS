"""Only the solid red push box should gain an image-space obstacle box."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from avs_rescue_sim.barrier_detector import BarrierDetector
from avs_rescue_sim.hazard_classifier import HazardClassifier
from avs_rescue_sim.panel_geometry import PanelGeometryVerifier


TEXTURES = Path(__file__).resolve().parents[1] / 'models/rescue_course/materials/textures'
ARTWORK = [
    'hazard_fire.png', 'hazard_chemical.png', 'hazard_radiation.png',
    'hazard_electrical.png', 'hazard_biohazard.png',
    'apriltag_0.png', 'apriltag_1.png', 'apriltag_2.png', 'apriltag_3.png',
]


@pytest.mark.parametrize('left,shadowed', [
    pytest.param(210, False, id='normal'),
    pytest.param(210, True, id='partly-in-shadow'),
    pytest.param(0, False, id='clipped-at-image-edge'),
])
def test_solid_box_survives_shadow_and_image_edge(left, shadowed):
    frame = np.full((480, 640, 3), 180, np.uint8)
    frame[150:330, left:left + 150] = (18, 18, 220)
    if shadowed:
        frame[150:330, left:left + 75] = (5, 5, 55)
    assert BarrierDetector().detect(frame) == [(left, 150, 150, 180)]


@pytest.mark.parametrize('strip_width', [
    pytest.param(16., id='thin-tag-trim'),
    pytest.param(24., id='long-tag-trim'),
])
def test_slanted_red_trim_is_rejected_while_rotated_box_is_kept(strip_width):
    frame = np.full((480, 640, 3), 180, np.uint8)
    trim = np.rint(cv2.boxPoints(((170., 150.), (210., strip_width), 10.))).astype(np.int32)
    box = np.rint(cv2.boxPoints(((440., 300.), (130., 100.), 25.))).astype(np.int32)
    cv2.fillConvexPoly(frame, trim, (18, 18, 220))
    cv2.fillConvexPoly(frame, box, (18, 18, 220))

    # Tilt makes a narrow AprilTag edge's axis-aligned box appear thick enough
    # to resemble an obstacle, reproducing the near-camera false positive.
    _, _, width, height = cv2.boundingRect(trim)
    assert min(width, height) >= 18
    assert .2 <= width / height <= 5.
    assert BarrierDetector().detect(frame) == [cv2.boundingRect(box)]


@pytest.mark.parametrize('filename', ARTWORK)
def test_actual_hazard_and_apriltag_artwork_are_not_boxes(filename):
    artwork = cv2.imread(str(TEXTURES / filename))
    assert artwork is not None, filename
    detector = BarrierDetector()
    # Cover both the original artwork and a smaller, dimly lit camera view.
    assert detector.detect(artwork) == []
    frame = np.full((480, 640, 3), 150, np.uint8)
    frame[100:300, 220:420] = (cv2.resize(artwork, (200, 200)) * .6).astype(np.uint8)
    assert detector.detect(frame) == []


@pytest.mark.parametrize('side,clip', [(90, 64), (90, 66), (120, 87), (180, 96),
                                       (240, 126), (320, 168)])
def test_clipped_fire_glyph_fragment_is_not_a_box(side, clip):
    # During a right pan the FIRE panel leaves the left image edge. Its white
    # triangle separates a solid red fragment from the rest of the panel;
    # checking only the fragment's own white fraction misidentifies it.
    art = cv2.resize(cv2.imread(str(TEXTURES / 'hazard_fire.png')), (side, side))
    frame = np.full((480, 640, 3), 40, np.uint8)
    fragment = art[:, clip:]
    frame[60:60 + side, :fragment.shape[1]] = fragment
    frame[200:380, 400:550] = (18, 18, 220)
    assert BarrierDetector().detect(frame) == [(400, 200, 150, 180)]


def test_solid_box_touching_bright_wall_is_preserved():
    frame = np.full((480, 640, 3), 245, np.uint8)
    frame[150:330, :150] = (18, 18, 220)
    assert BarrierDetector().detect(frame) == [(0, 150, 150, 180)]


@pytest.mark.parametrize('quad', [
    [[356.2878, -72.4863], [826.9833, -65.1276],
     [826.9833, 351.5137], [356.2878, 258.8082]],
    [[318.2561, -132.8797], [918.9465, -167.0933],
     [918.9465, 388.1203], [318.2561, 320.8632]],
])
def test_clipped_fitted_fire_mask_does_not_create_box_residue(quad):
    artwork = cv2.imread(str(TEXTURES / 'hazard_fire.png'))
    source = np.float32([[0, 0], [511, 0], [511, 511], [0, 511]])
    transform = cv2.getPerspectiveTransform(source, np.float32(quad))
    frame = np.full((480, 640, 3), 40, np.uint8)
    warped = cv2.warpPerspective(artwork, transform, (640, 480))
    mask = cv2.warpPerspective(np.full((512, 512), 255, np.uint8), transform, (640, 480))
    frame[mask > 0] = warped[mask > 0]
    # The real fitted corners cut across the clipped triangle. Its small red
    # tip remains outside the mask; the printing context must use the raw image.
    corners = np.clip(np.float32(quad), [0, 0], [639, 479])
    minimum, maximum = corners.min(axis=0), corners.max(axis=0)
    proposal = np.float32([minimum, [maximum[0], minimum[1]], maximum,
                          [minimum[0], maximum[1]]])
    polygon = PanelGeometryVerifier(TEXTURES).refine(frame, 'FIRE', proposal)
    assert polygon is not None
    frame[200:380, 60:210] = (18, 18, 220)
    assert BarrierDetector().detect(frame, [polygon]) == [(60, 200, 150, 180)]


@pytest.mark.parametrize('background,sign_brightness,box_brightness', [
    (180, 1., 220), (245, 1., 220), (180, .6, 220),
    (245, .6, 220), (180, 1., 55),
])
def test_printing_context_does_not_merge_separate_nearby_box(
        background, sign_brightness, box_brightness):
    frame = np.full((480, 640, 3), background, np.uint8)
    artwork = cv2.imread(str(TEXTURES / 'hazard_fire.png'))
    frame[100:280, 80:260] = (cv2.resize(artwork, (180, 180)) * sign_brightness).astype(np.uint8)
    frame[150:220, 290:340] = (5, 5, box_brightness)
    assert BarrierDetector().detect(frame) == [(290, 150, 50, 70)]


def test_white_wall_band_does_not_join_sign_and_box():
    frame = np.full((480, 640, 3), 40, np.uint8)
    frame[80:300] = 180
    artwork = cv2.imread(str(TEXTURES / 'hazard_fire.png'))
    frame[100:280, 80:260] = cv2.resize(artwork, (180, 180))
    frame[150:220, 290:340] = (18, 18, 220)
    assert BarrierDetector().detect(frame) == [(290, 150, 50, 70)]


def test_hazard_exclusion_preserves_separate_push_box():
    frame = np.full((480, 640, 3), 180, np.uint8)
    fire = cv2.imread(str(TEXTURES / 'hazard_fire.png'))
    frame[95:275, 60:240] = cv2.resize(fire, (180, 180))
    frame[190:390, 400:570] = (18, 18, 220)
    hits = HazardClassifier(TEXTURES, ['FIRE']).detect(frame)
    assert [hit[0] for hit in hits] == ['FIRE']
    excluded = [hit[1] for hit in hits]
    assert BarrierDetector().detect(frame, excluded) == [(400, 190, 170, 200)]

    # A recognized red region must remain excluded even if its white printing
    # cannot be seen in this exposure; a spatially separate box still survives.
    frame[95:275, 60:240] = (18, 18, 220)
    excluded = [np.array([[60, 95], [239, 95], [239, 274], [60, 274]])]
    assert len(BarrierDetector().detect(frame)) == 2
    assert BarrierDetector().detect(frame, excluded) == [(400, 190, 170, 200)]


def test_vision_publishes_pixel_boxes_with_exposure_header_and_clears_missing_box():
    pytest.importorskip('rclpy')
    from avs_rescue_sim.vision_node import VisionNode

    node = SimpleNamespace(
        barrier_detector=BarrierDetector(), visible_hazard_polygons=[],
        visible_barriers=[], obstacle_pub=Mock())
    frame = np.full((480, 640, 3), 180, np.uint8)
    frame[190:390, 400:570] = (18, 18, 220)
    header = SimpleNamespace(frame_id='camera_optical_frame',
                             stamp=SimpleNamespace(sec=123, nanosec=456789))
    annotated = frame.copy()
    VisionNode.detect_barrier(node, frame, annotated, header)
    payload = json.loads(node.obstacle_pub.publish.call_args.args[0].data)
    assert payload == {
        'kind': 'push_barrier', 'frame_id': 'camera_optical_frame',
        'stamp': {'sec': 123, 'nanosec': 456789},
        'boxes': [{'x': 400, 'y': 190, 'width': 170, 'height': 200}],
    }
    assert np.any(annotated != frame)

    empty_frame = np.full_like(frame, 180)
    header.stamp = SimpleNamespace(sec=124, nanosec=987654)
    VisionNode.detect_barrier(node, empty_frame, empty_frame.copy(), header)
    cleared = json.loads(node.obstacle_pub.publish.call_args.args[0].data)
    assert cleared['boxes'] == []
    assert cleared['stamp'] == {'sec': 124, 'nanosec': 987654}
    assert node.visible_barriers == []
    assert node.obstacle_pub.publish.call_count == 2
