from pathlib import Path

import cv2
import numpy as np
import pytest

from avs_rescue_sim.panel_geometry import PanelGeometryVerifier


TEXTURES = Path(__file__).resolve().parents[1] / 'models/rescue_course/materials/textures'
LABELS = ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']


def box(x, y, width, height):
    return np.array([[x, y], [x + width, y], [x + width, y + height],
                     [x, y + height]], np.int32).reshape(4, 1, 2)


def project(label, quad, shade=1., blur=0):
    frame = np.full((240, 320, 3), (40, 35, 30), np.uint8)
    artwork = cv2.imread(str(TEXTURES / f'hazard_{label.lower()}.png'))
    source = np.float32([[0, 0], [511, 0], [511, 511], [0, 511]])
    transform = cv2.getPerspectiveTransform(source, np.float32(quad))
    warped = cv2.warpPerspective(artwork, transform, (320, 240))
    mask = cv2.warpPerspective(np.full((512, 512), 255, np.uint8), transform, (320, 240))
    frame[mask > 127] = warped[mask > 127]
    frame = np.clip(frame.astype(float) * shade, 0, 255).astype(np.uint8)
    if blur:
        frame = cv2.GaussianBlur(frame, (3, 3), blur)
    return frame


@pytest.mark.parametrize('label', LABELS)
def test_fits_angulated_panel_despite_oversized_yolo_proposal(label):
    truth = np.float32([[105, 65], [198, 48], [213, 172], [98, 183]])
    frame = project(label, truth, shade=.65, blur=.5)
    verifier = PanelGeometryVerifier(TEXTURES)
    refined = verifier.refine(frame, label, box(65, 28, 180, 175))
    assert refined is not None
    # Corners are fitted to image evidence, rather than the oversized proposal.
    assert np.linalg.norm(refined.reshape(4, 2) - truth, axis=1).max() < 9.


@pytest.mark.parametrize('label', LABELS)
def test_keeps_distant_twenty_six_pixel_pictograms(label):
    truth = np.float32([[132, 87], [158, 89], [158, 115], [132, 114]])
    frame = project(label, truth, shade=.8, blur=.45)
    refined = PanelGeometryVerifier(TEXTURES).refine(frame, label, box(122, 76, 46, 48))
    assert refined is not None
    assert cv2.contourArea(refined) < 1.5 * cv2.contourArea(truth)


@pytest.mark.parametrize('label,color', [
    ('RADIATION', (0, 225, 235)), ('ELECTRICAL', (220, 80, 20)),
    ('FIRE', (25, 25, 220)),
])
def test_rejects_plain_coloured_vehicle_floor_and_box(label, color):
    frame = np.full((240, 320, 3), (40, 35, 30), np.uint8)
    cv2.rectangle(frame, (60, 90), (260, 230), color, -1)
    # A white floor edge or bright metal rim must not stand in for the glyph.
    cv2.rectangle(frame, (60, 90), (260, 230), (230, 230, 230), 3)
    assert PanelGeometryVerifier(TEXTURES).refine(frame, label, box(50, 75, 225, 160)) is None


def test_rejects_same_colour_patch_with_unrelated_white_mark():
    frame = np.full((240, 320, 3), (40, 35, 30), np.uint8)
    cv2.rectangle(frame, (85, 55), (225, 195), (0, 225, 235), -1)
    cv2.circle(frame, (112, 88), 14, (245, 245, 245), -1)
    assert PanelGeometryVerifier(TEXTURES).refine(frame, 'RADIATION', box(75, 45, 165, 165)) is None


@pytest.mark.parametrize('label', LABELS)
def test_box_extent_follows_the_panel_when_yolo_size_changes(label):
    truth = np.float32([[110, 75], [229, 75], [229, 194], [110, 194]])
    frame = project(label, truth)
    verifier = PanelGeometryVerifier(TEXTURES)
    refined = [verifier.refine(frame, label, proposal) for proposal in (
        box(90, 50, 165, 175), box(65, 35, 210, 195),
        box(122, 90, 100, 90), box(84, 64, 173, 146))]
    assert all(value is not None for value in refined)
    # Network regression jitter must not inflate the displayed sign geometry.
    for value in refined:
        assert np.linalg.norm(value.reshape(4, 2) - truth, axis=1).max() < 3.


def test_edge_only_panel_without_visible_glyph_is_rejected():
    # The camera sees a sliver of the blue board at a corridor corner. A
    # stretch of white rim is not evidence of the ELECTRICAL pictogram.
    frame = np.full((240, 320, 3), (35, 35, 35), np.uint8)
    artwork = cv2.imread(str(TEXTURES / 'hazard_electrical.png'))
    skinny = cv2.resize(artwork, (14, 70), interpolation=cv2.INTER_AREA)
    frame[80:150, 180:194] = skinny
    assert PanelGeometryVerifier(TEXTURES).refine(frame, 'ELECTRICAL', box(172, 71, 30, 87)) is None

