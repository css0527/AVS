import numpy as np
import pytest
import torch
import cv2
from pathlib import Path
import json

from avs_rescue_sim.yolov5_detector import YoloV5Detector
from avs_rescue_sim.yolov5_model import YoloV5HazardNet
from avs_rescue_sim.panel_geometry import PanelGeometryVerifier


TEXTURES = Path(__file__).resolve().parents[1] / 'models/rescue_course/materials/textures'


class FixedModel:
    def __init__(self, predictions):
        self.predictions = torch.tensor([predictions], dtype=torch.float32)

    def eval(self):
        return self

    def __call__(self, _tensor):
        return self.predictions


def prediction(cx, cy, width, height, objectness, class_id, class_score=.9):
    classes = [.01] * 5
    classes[class_id] = class_score
    return [cx, cy, width, height, objectness, *classes]


def test_letterbox_coordinates_and_class_aware_nms():
    # A 640x320 camera image becomes 320x160 with 80 px vertical padding.
    # The first two predictions overlap and should collapse to one FIRE box;
    # the overlapping CHEMICAL box must remain because NMS is class-aware.
    rows = [
        prediction(.50, .50, .25, .20, .90, 0),
        prediction(.505, .50, .25, .20, .82, 0),
        prediction(.18, .55, .10, .10, .75, 0),
        prediction(.50, .50, .25, .20, .88, 1),
        prediction(.20, .20, .05, .05, .10, 2),
    ]
    detector = YoloV5Detector('unused', ['FIRE', 'CHEMICAL', 'RADIATION',
                                        'ELECTRICAL', 'BIOHAZARD'],
                              image_size=320, confidence=.35, min_area=100,
                              model=FixedModel(rows))
    result = detector.detect(np.zeros((320, 640, 3), np.uint8))

    assert [item[0] for item in result] == ['FIRE', 'CHEMICAL']
    assert result[0][2] == pytest.approx(.81, abs=1e-5)
    assert result[0][1].reshape(-1, 2).min(axis=0).tolist() == [240, 96]
    assert result[0][1].reshape(-1, 2).max(axis=0).tolist() == [400, 224]


def test_model_emits_three_scale_yolov5_predictions():
    model = YoloV5HazardNet(classes=5, width=8).eval()
    with torch.inference_mode():
        output = model(torch.zeros(1, 3, 160, 160))
    assert output.shape == (1, 3 * (20 * 20 + 10 * 10 + 5 * 5), 10)
    assert torch.isfinite(output).all()


def test_rejects_invalid_image_size():
    with pytest.raises(ValueError, match='multiple of 32'):
        YoloV5Detector('unused', ['FIRE'], image_size=300, model=FixedModel([]))


def test_rejects_input_size_different_from_traced_model(tmp_path):
    weights = tmp_path / 'model.torchscript'
    weights.with_suffix('.json').write_text(json.dumps({'image_size': 320}))
    with pytest.raises(ValueError, match='require image_size=320'):
        YoloV5Detector(weights, ['FIRE'], image_size=416, model=FixedModel([]))


@pytest.mark.parametrize('label,class_id,plain', [
    ('FIRE', 0, (25, 25, 220)),
    ('RADIATION', 2, (0, 225, 235)),
    ('ELECTRICAL', 3, (220, 80, 20)),
])
def test_real_panel_wins_over_higher_score_course_colour(label, class_id, plain):
    labels = ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']
    frame = np.full((320, 320, 3), 35, np.uint8)
    cv2.rectangle(frame, (25, 205), (295, 305), plain, -1)
    art = cv2.imread(str(TEXTURES / f'hazard_{label.lower()}.png'))
    art = cv2.resize(art, (66, 66))
    frame[80:146, 120:186] = art
    rows = [
        prediction(160/320, 255/320, 270/320, 100/320, .99, class_id, .99),
        prediction(154/320, 113/320, 95/320, 92/320, .85, class_id, .90),
    ]
    detector = YoloV5Detector('unused', labels, model=FixedModel(rows),
        image_size=320, confidence=.60, panel_verifier=PanelGeometryVerifier(TEXTURES))
    detections = detector.detect(frame)
    assert len(detections) == 1
    assert detections[0][0] == label
    fitted = detections[0][1].reshape(4, 2)
    assert np.linalg.norm(fitted - [[120, 80], [186, 80], [186, 146], [120, 146]], axis=1).max() < 5
