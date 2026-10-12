from pathlib import Path
import cv2
import numpy as np
from avs_rescue_sim.hazard_classifier import HazardClassifier

ROOT = Path(__file__).resolve().parents[1] / 'models/rescue_course/materials/textures'
LABELS = ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']


def test_artwork_survives_perspective_and_lighting():
    classifier = HazardClassifier(ROOT, LABELS)
    source = np.float32([[0, 0], [511, 0], [511, 511], [0, 511]])
    target = np.float32([[220, 120], [408, 150], [390, 350], [200, 330]])
    transform = cv2.getPerspectiveTransform(source, target)
    for label in LABELS:
        template = cv2.imread(str(ROOT / f'hazard_{label.lower()}.png'))
        frame = cv2.warpPerspective(template, transform, (640, 480))
        frame = (frame * .65).astype(np.uint8)
        assert {hit[0] for hit in classifier.detect(frame)} == {label}


def test_vehicle_floor_and_barrier_colors_are_not_signs():
    classifier = HazardClassifier(ROOT, LABELS)
    frame = np.zeros((480, 640, 3), np.uint8)
    cv2.rectangle(frame, (50, 90), (200, 400), (25, 25, 220), -1)
    cv2.rectangle(frame, (230, 200), (400, 400), (220, 80, 20), -1)
    cv2.rectangle(frame, (0, 420), (639, 479), (0, 125, 245), -1)
    assert classifier.detect(frame) == []
