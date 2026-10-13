"""Regression checks for course-colored negatives and small-sign localization."""
import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/train_yolov5_hazards.py'
SPEC = importlib.util.spec_from_file_location('train_yolov5_hazards', SCRIPT)
training = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(training)


def test_background_views_have_no_targets_and_include_actual_course_colors():
    dataset = training.SyntheticHazards(24, 160, 814, augment=False,
                                         background_fraction=1.)
    observed = {'red': False, 'blue': False, 'yellow': False}
    for index in range(len(dataset)):
        image, targets = dataset[index]
        assert targets.shape == (0, 5)
        rgb = (image.numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hue, saturation, value = cv2.split(hsv)
        colorful = (saturation > 130) & (value > 70)
        observed['red'] |= np.count_nonzero(colorful & ((hue < 10) | (hue > 170))) > 100
        observed['blue'] |= np.count_nonzero(colorful & (hue >= 95) & (hue <= 125)) > 100
        observed['yellow'] |= np.count_nonzero(colorful & (hue >= 15) & (hue <= 40)) > 100
    assert all(observed.values()), observed


def test_blank_plates_keep_class_color_but_remove_the_pictogram():
    dataset = training.SyntheticHazards(1, 160, 814, augment=False)
    for class_id in range(len(training.LABELS)):
        for bordered in (False, True):
            plate = dataset.blank_panel(class_id, bordered)
            expected = np.broadcast_to(dataset.hazard_colors[class_id], (56, 56, 3))
            np.testing.assert_array_equal(plate[20:76, 20:76], expected)
        assert np.ptp(dataset.hazards[class_id][40:200, 40:200].astype(float)) > 100


def test_synthetic_views_remain_deterministic_and_have_background_fraction():
    dataset = training.SyntheticHazards(100, 160, 814)
    first_image, first_targets = dataset[9]
    second_image, second_targets = dataset[9]
    assert torch.equal(first_image, second_image)
    assert torch.equal(first_targets, second_targets)
    blank_count = sum(len(dataset[index][1]) == 0 for index in range(len(dataset)))
    assert 20 <= blank_count <= 50


def test_labeled_signs_do_not_hide_each_other():
    dataset = training.SyntheticHazards(60, 160, 814, background_fraction=0.)
    for index in range(len(dataset)):
        _image, targets = dataset[index]
        for first in range(len(targets)):
            for second in range(first):
                assert dataset.overlap_fraction(targets[first].numpy(),
                                                 targets[second].numpy()) <= .081


def test_partial_occlusion_keeps_a_ten_pixel_sign_visible():
    dataset = training.SyntheticHazards(1, 160, 814)
    targets = [[0, .5, .5, 10/160, 10/160]]
    scene = np.full((160, 160, 3), 255, np.uint8)
    dataset.partial_occlusion(scene, targets, np.random.default_rng(814))
    sign_pixels = scene[75:85, 75:85]
    covered_columns = np.count_nonzero(np.any(sign_pixels != 255, axis=(0, 2)))
    assert 0 < covered_columns <= 2


def test_ciou_penalizes_relative_box_error_equally_for_small_and_large_signs():
    target = torch.tensor([.5, .5, .1, .1])
    fitted = target.clone()
    oversized = torch.tensor([.5, .5, .2, .2], requires_grad=True)
    assert training.complete_box_iou(fitted, target).item() == pytest.approx(1., abs=1e-4)
    ciou = training.complete_box_iou(oversized, target)
    assert ciou.item() == pytest.approx(.25, abs=1e-4)
    assert training.complete_box_iou(oversized * 2, target * 2).item() == pytest.approx(
        ciou.item(), abs=1e-4)
    (1. - ciou).backward()
    assert torch.isfinite(oversized.grad).all()
    assert oversized.grad[2] > 0 and oversized.grad[3] > 0


def test_objectness_keeps_a_strong_positive_gradient_with_many_empty_anchors():
    logits = torch.zeros(1, 3, 20, 20, 10)
    logits[..., 4] = -4.5
    logits.requires_grad_()
    mask = torch.zeros(1, 3, 20, 20, dtype=torch.bool)
    mask[0, 0, 10, 10] = True
    loss = training.balanced_objectness_loss([logits], [mask])
    loss.backward()
    gradient = logits.grad[..., 4]
    assert gradient[mask].item() < -1.
    assert gradient[~mask].sum() > 0.
    assert -gradient[mask].item() > 20 * gradient[~mask].sum().item()


def test_background_only_batch_pushes_down_one_high_confidence_false_positive():
    logits = torch.zeros(1, 3, 20, 20, 10)
    logits[..., 4] = -4.5
    logits[0, 1, 5, 6, 4] = 4.
    logits.requires_grad_()
    mask = torch.zeros(1, 3, 20, 20, dtype=torch.bool)
    loss = training.balanced_objectness_loss([logits], [mask])
    loss.backward()
    assert torch.isfinite(loss)
    assert logits.grad[0, 1, 5, 6, 4] > .04
    # Non-selected easy negatives need no gradient in hard-negative mining.
    assert (logits.grad[..., 4] == 0).sum() > 1000


def test_training_loads_matching_local_weights_and_rejects_wrong_width(tmp_path):
    source = training.YoloV5HazardNet(len(training.LABELS), width=8)
    copied = training.YoloV5HazardNet(len(training.LABELS), width=8)
    path = tmp_path / 'local_weights.pt'
    torch.save({'state_dict': source.state_dict()}, path)
    training.load_initial_weights(copied, path)
    for key, value in source.state_dict().items():
        assert torch.equal(value, copied.state_dict()[key]), key
    with pytest.raises(RuntimeError):
        training.load_initial_weights(training.YoloV5HazardNet(len(training.LABELS),
                                                                 width=16), path)


def test_validation_rejects_loose_iou_point_four_boxes_and_counts_background_false_positives():
    class FixedModel:
        def eval(self):
            return self

        def __call__(self, _image):
            # Same center and height; 0.5 width versus 0.2 truth gives IoU 0.4.
            return torch.tensor([[[.5, .5, .5, .2, .9, .9, .01, .01, .01, .01]]])

    class Views:
        size = 160

        def __len__(self):
            return 2

        def __getitem__(self, index):
            targets = ([] if index == 1 else [[0, .5, .5, .2, .2]])
            return torch.zeros(3, self.size, self.size), torch.tensor(targets).reshape(-1, 5)

    metrics = training.evaluate(FixedModel(), Views(), confidence=.6)
    assert metrics['matching_iou'] == .5
    assert metrics['true_positive'] == 0
    assert metrics['false_positive'] == 2
    assert metrics['missed'] == 1
    assert metrics['background_images'] == 1
    assert metrics['background_false_positive_images'] == 1
    assert metrics['background_false_positive_rate'] == 1.
