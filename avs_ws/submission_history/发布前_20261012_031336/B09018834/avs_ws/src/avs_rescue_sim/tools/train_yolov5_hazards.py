#!/usr/bin/env python3
"""Train and export YOLOv5 using augmented pictograms and course-colored negatives."""
import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from avs_rescue_sim.yolov5_model import YoloV5HazardNet

LABELS = ['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']
TEXTURES = ROOT / 'models/rescue_course/materials/textures'


class SyntheticHazards(Dataset):
    def __init__(self, count, image_size, seed, augment=True,
                 background_fraction=.35):
        self.count, self.size, self.seed, self.augment = count, image_size, seed, augment
        self.background_fraction = float(background_fraction)
        if not 0. <= self.background_fraction <= 1.:
            raise ValueError('background_fraction must lie between zero and one')
        self.hazards = [cv2.imread(str(TEXTURES / f'hazard_{name.lower()}.png'))
                        for name in LABELS]
        self.tags = [cv2.imread(str(TEXTURES / f'apriltag_{index}.png')) for index in range(4)]
        if any(image is None for image in self.hazards + self.tags):
            raise FileNotFoundError(f'Missing training texture in {TEXTURES}')
        self.hazard_colors = []
        for image in self.hazards:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            pixels = image[(hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)]
            self.hazard_colors.append(np.median(pixels, axis=0).astype(np.uint8))

    def __len__(self):
        return self.count

    @staticmethod
    def project(scene, artwork, quad):
        source = np.float32([[0, 0], [artwork.shape[1] - 1, 0],
                             [artwork.shape[1] - 1, artwork.shape[0] - 1],
                             [0, artwork.shape[0] - 1]])
        transform = cv2.getPerspectiveTransform(source, np.float32(quad))
        warped = cv2.warpPerspective(artwork, transform, (scene.shape[1], scene.shape[0]))
        mask = cv2.warpPerspective(np.full(artwork.shape[:2], 255, np.uint8), transform,
                                   (scene.shape[1], scene.shape[0]))
        scene[mask > 20] = warped[mask > 20]

    def hard_negatives(self, scene, rng, horizon):
        """Paint course-colored objects before labeled signs to avoid hiding labels."""
        size = self.size
        # OpenCV 颜色元组使用 BGR 顺序。
        if rng.random() < .70:
            x1 = int(rng.integers(0, max(1, int(size * .9))))
            y1 = int(rng.integers(int(size * .20), max(int(size * .20) + 1, int(size * .9))))
            width = int(rng.integers(10, max(11, int(size * .48))))
            height = int(rng.integers(10, max(11, int(size * .58))))
            color = tuple(int(value) for value in
                          (rng.integers(0, 35), rng.integers(0, 35), rng.integers(105, 230)))
            x2, y2 = min(size - 1, x1 + width), min(size - 1, y1 + height)
            cv2.rectangle(scene, (x1, y1), (x2, y2), color, -1)
            # A shaded face makes the push box visibly three-dimensional.
            if x2 - x1 > 15 and rng.random() < .7:
                face = np.array([[x1, y1], [x1 + (x2-x1)//4, y1 + 4],
                                 [x1 + (x2-x1)//4, y2], [x1, y2]], np.int32)
                cv2.fillConvexPoly(scene, face, tuple(int(c * .62) for c in color))

        # Blue departure pads appear as horizontal trapezoids on the floor.
        if rng.random() < .80:
            cx = rng.uniform(0, size)
            cy = rng.uniform(max(0, horizon - size * .06), size - 1)
            width = rng.uniform(size * .05, size * .86)
            height = rng.uniform(size * .012, size * .20)
            taper = rng.uniform(.45, 1.3)
            quad = np.int32([[cx-width*taper/2, cy-height/2],
                             [cx+width*taper/2, cy-height/2],
                             [cx+width/2, cy+height/2],
                             [cx-width/2, cy+height/2]])
            color = tuple(int(value) for value in
                          (rng.integers(100, 210), rng.integers(20, 75), rng.integers(0, 35)))
            cv2.fillConvexPoly(scene, quad, color)

        # Yellow pusher/chassis edges are visible at the bottom while panning.
        if rng.random() < .80:
            cx = rng.uniform(0, size)
            cy = rng.uniform(size * .67, size * 1.05)
            width = rng.uniform(size * .025, size * .72)
            height = rng.uniform(size * .012, size * .30)
            skew = rng.uniform(-.45, .45) * width
            quad = np.int32([[cx-width/2+skew, cy-height/2],
                             [cx+width/2+skew, cy-height/2],
                             [cx+width/2, cy+height/2],
                             [cx-width/2, cy+height/2]])
            color = tuple(int(value) for value in
                          (rng.integers(0, 35), rng.integers(95, 190), rng.integers(170, 255)))
            cv2.fillConvexPoly(scene, quad, color)

        # 同色负样本保留颜色、边框和螺钉，去掉图案。
        for _ in range(int(rng.integers(1, 4))):
            class_id = int(rng.integers(0, len(LABELS)))
            tile = self.blank_panel(class_id, bordered=rng.random() < .50)
            tile = np.clip(tile.astype(np.float32) * rng.uniform(.45, 1.15),
                           0, 255).astype(np.uint8)
            side = float(np.exp(rng.uniform(np.log(10), np.log(size * .55))))
            width, height = side * rng.uniform(.45, 1.6), side * rng.uniform(.45, 1.6)
            cx, cy = rng.uniform(0, size), rng.uniform(0, size)
            skew = rng.uniform(-.32, .32) * width
            quad = np.float32([[cx-width/2+skew, cy-height/2],
                               [cx+width/2+skew, cy-height/2],
                               [cx+width/2-skew, cy+height/2],
                               [cx-width/2-skew, cy+height/2]])
            self.project(scene, tile, quad)

        if rng.random() < .40:
            tag = self.tags[int(rng.integers(0, len(self.tags)))]
            side = int(rng.integers(18, max(19, size // 4)))
            x1 = int(rng.integers(0, size - side)); y1 = int(rng.integers(0, size - side))
            scene[y1:y1 + side, x1:x1 + side] = cv2.resize(tag, (side, side))

    def blank_panel(self, class_id, bordered=True):
        """A same-color plate without the artwork that distinguishes the class."""
        tile = np.full((96, 96, 3), self.hazard_colors[class_id], np.uint8)
        if bordered:
            cv2.rectangle(tile, (0, 0), (95, 95), (220, 220, 220), 4)
            cv2.rectangle(tile, (7, 7), (88, 88), (20, 20, 20), 2)
            for x, y in ((13, 13), (82, 13), (13, 82), (82, 82)):
                cv2.circle(tile, (x, y), 2, (210, 210, 210), -1)
        return tile

    @staticmethod
    def overlap_fraction(candidate, existing):
        """Fraction of the smaller sign hidden if two labeled boxes overlap."""
        a_min = np.asarray(candidate[1:3]) - np.asarray(candidate[3:5]) / 2.
        a_max = np.asarray(candidate[1:3]) + np.asarray(candidate[3:5]) / 2.
        b_min = np.asarray(existing[1:3]) - np.asarray(existing[3:5]) / 2.
        b_max = np.asarray(existing[1:3]) + np.asarray(existing[3:5]) / 2.
        intersection = np.maximum(0., np.minimum(a_max, b_max) -
                                  np.maximum(a_min, b_min)).prod()
        return intersection / max(1e-9, min(candidate[3] * candidate[4],
                                            existing[3] * existing[4]))

    def partial_occlusion(self, scene, targets, rng):
        """Occlude at most 25% of any sign width, including 10px targets."""
        selected = targets[int(rng.integers(0, len(targets)))]
        width_px = selected[3] * self.size
        thickness = max(1, int(min(self.size // 10, width_px * .20)))
        left = (selected[1] - selected[3] / 2.) * self.size
        x = int(left + rng.uniform(.15, .65) * width_px)
        for target in targets:
            target_left = (target[1] - target[3] / 2.) * self.size
            target_right = (target[1] + target[3] / 2.) * self.size
            covered = max(0., min(x + thickness, target_right) - max(x, target_left))
            if covered > (target_right - target_left) * .25:
                return
        shade = int(rng.integers(20, 90))
        # Slice end is exclusive, avoiding OpenCV's extra inclusive pixel for
        # a two-pixel stripe across a very small sign.
        scene[:, max(0, x):min(self.size, x + thickness)] = shade

    def render(self, index):
        rng = np.random.default_rng(self.seed + index)
        py = random.Random(self.seed + index)
        size = self.size
        base = int(rng.integers(22, 115))
        scene = np.full((size, size, 3), base, np.float32)
        gradient = np.linspace(float(rng.integers(-35, 25)),
                               float(rng.integers(-20, 45)), size, dtype=np.float32)
        scene += gradient[None, :, None]
        horizon = int(rng.integers(size * .55, size * .88))
        floor = np.array([rng.integers(115, 210), rng.integers(115, 210),
                          rng.integers(115, 210)], np.float32)
        scene[horizon:] = floor
        for _ in range(int(rng.integers(0, 4))):
            x = int(rng.integers(0, size)); width = int(rng.integers(4, max(5, size // 12)))
            cv2.rectangle(scene, (x, 0), (min(size - 1, x + width), horizon),
                          (base * rng.uniform(.45, .9),) * 3, -1)
        scene = np.clip(scene, 0, 255).astype(np.uint8)
        self.hard_negatives(scene, rng, horizon)

        targets = []
        class_ids = ([] if rng.random() < self.background_fraction else
                     py.sample(range(len(LABELS)), k=int(rng.integers(1, 4))))
        for class_id in class_ids:
            for _attempt in range(20):
                # Log sampling over-represents distant 10-60 px signs.
                side = float(np.exp(rng.uniform(np.log(10), np.log(size * .47))))
                aspect = rng.uniform(.72, 1.28)
                width, height = side * aspect, side / aspect
                cx = rng.uniform(width * .55, size - width * .55)
                cy = rng.uniform(height * .58, min(horizon + height * .25, size - height * .58))
                skew = rng.uniform(-.28, .28) * width
                vertical = rng.uniform(-.18, .18) * height
                quad = np.float32([
                    [cx - width / 2 + skew, cy - height / 2 + vertical],
                    [cx + width / 2 + skew, cy - height / 2 - vertical],
                    [cx + width / 2 - skew, cy + height / 2 + vertical],
                    [cx - width / 2 - skew, cy + height / 2 - vertical],
                ])
                quad[:, 0] = np.clip(quad[:, 0], 0, size - 1)
                quad[:, 1] = np.clip(quad[:, 1], 0, size - 1)
                x1, y1 = quad.min(axis=0); x2, y2 = quad.max(axis=0)
                target = [class_id, (x1+x2)/(2*size), (y1+y2)/(2*size),
                          (x2-x1)/size, (y2-y1)/size]
                if all(self.overlap_fraction(target, previous) <= .08 for previous in targets):
                    break
            else:
                # 移除被其他标识遮挡的图案标签。
                continue
            artwork = self.hazards[class_id].copy()
            if rng.random() < .45:
                artwork = np.clip(artwork.astype(np.float32) * rng.uniform(.42, 1.18)
                                  + rng.uniform(-18, 18), 0, 255).astype(np.uint8)
            self.project(scene, artwork, quad)
            targets.append(target)

        if self.augment:
            if rng.random() < .55:
                kernel = int(rng.choice([3, 5, 7])); scene = cv2.GaussianBlur(scene, (kernel, kernel), rng.uniform(.3, 1.6))
            if rng.random() < .35:
                length = int(rng.integers(3, 13)); kernel = np.zeros((length, length), np.float32)
                kernel[length // 2, :] = 1. / length
                scene = cv2.filter2D(scene, -1, kernel)
            scene = np.clip(scene.astype(np.float32) * rng.uniform(.55, 1.30)
                            + rng.normal(0, rng.uniform(0, 9), scene.shape), 0, 255).astype(np.uint8)
            if rng.random() < .25 and targets:
                self.partial_occlusion(scene, targets, rng)
        rgb = cv2.cvtColor(scene, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float() / 255.
        return tensor, torch.tensor(targets, dtype=torch.float32).reshape(-1, 5)

    def __getitem__(self, index):
        return self.render(index)


def collate(batch):
    return torch.stack([item[0] for item in batch]), [item[1] for item in batch]


def complete_box_iou(predicted, target):
    """Differentiable CIoU for xywh boxes, independent of absolute sign size."""
    epsilon = 1e-7
    pred_min, pred_max = predicted[:2] - predicted[2:] / 2., predicted[:2] + predicted[2:] / 2.
    true_min, true_max = target[:2] - target[2:] / 2., target[:2] + target[2:] / 2.
    intersection_wh = (torch.minimum(pred_max, true_max) -
                       torch.maximum(pred_min, true_min)).clamp_min(0.)
    intersection = intersection_wh.prod()
    union = predicted[2:].prod() + target[2:].prod() - intersection + epsilon
    iou = intersection / union
    enclosure_wh = torch.maximum(pred_max, true_max) - torch.minimum(pred_min, true_min)
    center_penalty = (predicted[:2] - target[:2]).square().sum() / (
        enclosure_wh.square().sum() + epsilon)
    aspect_penalty = 4. / math.pi ** 2 * (
        torch.atan(target[2] / target[3].clamp_min(epsilon)) -
        torch.atan(predicted[2] / predicted[3].clamp_min(epsilon))).square()
    with torch.no_grad():
        aspect_weight = aspect_penalty / (1. - iou + aspect_penalty + epsilon)
    return iou - center_penalty - aspect_weight * aspect_penalty


def balanced_objectness_loss(raw, positive_masks):
    """Normalize positive and negative losses separately with hard-negative mining."""
    positives = torch.cat([prediction[..., 4][mask] for prediction, mask in
                           zip(raw, positive_masks)])
    negatives = torch.cat([prediction[..., 4][~mask] for prediction, mask in
                           zip(raw, positive_masks)])
    # Background-only batches still teach the hard negative branch.
    positive_loss = (F.softplus(-positives).mean() if positives.numel() else
                     raw[0][..., 4].sum() * 0.)
    if negatives.numel():
        hard_count = min(negatives.numel(),
                         max(16 * raw[0].shape[0], 8 * positives.numel()))
        negative_loss = F.softplus(negatives).topk(hard_count).values.mean()
    else:
        negative_loss = raw[0][..., 4].sum() * 0.
    return 2. * positive_loss + .75 * negative_loss


def detection_loss(model, raw, targets):
    box_loss = torch.tensor(0., device=raw[0].device)
    class_loss = torch.tensor(0., device=raw[0].device)
    assignments = [[] for _ in raw]
    positive_masks = []
    anchors = model.anchors.to(raw[0].device)
    for batch_index, boxes in enumerate(targets):
        for target in boxes.to(raw[0].device):
            class_id = int(target[0].item()); wh = target[3:5]
            ratios = torch.maximum(wh / anchors, anchors / wh).amax(2)
            scale_index, anchor_index = np.unravel_index(int(ratios.argmin().item()), ratios.shape)
            assignments[scale_index].append((batch_index, anchor_index, class_id, target[1:]))
    positive_count = 0
    for scale_index, prediction in enumerate(raw):
        positive_mask = torch.zeros_like(prediction[..., 4], dtype=torch.bool)
        positives = assignments[scale_index]
        for batch_index, anchor_index, class_id, box in positives:
            height, width = prediction.shape[2:4]
            gx, gy = box[0] * width, box[1] * height
            i, j = min(width - 1, int(gx)), min(height - 1, int(gy))
            value = prediction[batch_index, anchor_index, j, i]
            pred_xy = value[0:2].sigmoid() * 2. - .5
            pred_wh = (value[2:4].sigmoid() * 2.) ** 2 * anchors[scale_index, anchor_index]
            grid_size = value.new_tensor([width, height])
            grid_origin = value.new_tensor([i, j])
            predicted_box = torch.cat(((pred_xy + grid_origin) / grid_size, pred_wh))
            # Absolute normalized-width loss barely penalized a loose box on
            # a tiny sign. CIoU penalizes the same relative error at all scales.
            box_loss = box_loss + 1. - complete_box_iou(predicted_box, box)
            box_loss = box_loss + .25 * F.smooth_l1_loss(
                pred_xy, torch.stack((gx - i, gy - j)))
            classes = torch.zeros(model.classes, device=value.device); classes[class_id] = 1.
            class_loss = class_loss + F.binary_cross_entropy_with_logits(value[5:], classes)
            positive_mask[batch_index, anchor_index, j, i] = True
            positive_count += 1
        positive_masks.append(positive_mask)
    count = max(1, positive_count)
    return (4. * box_loss / count + class_loss / count +
            balanced_objectness_loss(raw, positive_masks))


def load_initial_weights(model, path):
    """Resume from this project's matching TorchScript or PyTorch weights."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Initial weights do not exist: {path}')
    if path.suffix == '.torchscript':
        state = torch.jit.load(str(path), map_location='cpu').state_dict()
    else:
        state = torch.load(path, map_location='cpu', weights_only=True)
        if isinstance(state, dict) and 'state_dict' in state:
            state = state['state_dict']
    model.load_state_dict(state, strict=True)


def box_iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1]); x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    intersection = max(0., x2 - x1) * max(0., y2 - y1)
    union = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]) +
                (b[2] - b[0]) * (b[3] - b[1]) - intersection)
    return intersection / union


def evaluate(model, dataset, confidence=.35, match_iou=.50):
    model.eval(); true_positive = false_positive = missed = 0
    background_images = background_false_positive_images = 0
    with torch.inference_mode():
        for image, targets in DataLoader(dataset, batch_size=1, collate_fn=collate):
            output = model(image)[0].cpu().numpy()
            predictions = []
            for row in output:
                class_id = int(row[5:].argmax()); score = float(row[4] * row[5 + class_id])
                if score < confidence: continue
                cx, cy, w, h = row[:4]
                predictions.append((score, class_id, [cx-w/2, cy-h/2, cx+w/2, cy+h/2]))
            filtered = []
            for class_id in range(len(LABELS)):
                candidates = [value for value in predictions if value[1] == class_id]
                boxes = [[int((v[2][0]) * dataset.size), int((v[2][1]) * dataset.size),
                          int((v[2][2] - v[2][0]) * dataset.size),
                          int((v[2][3] - v[2][1]) * dataset.size)] for v in candidates]
                kept = cv2.dnn.NMSBoxes(boxes, [v[0] for v in candidates], confidence, .45)
                kept = np.asarray(kept).reshape(-1)
                if kept.size:
                    filtered.append(max((candidates[int(i)] for i in kept),
                                        key=lambda value: value[0]))
            matched = set()
            if len(targets[0]) == 0:
                background_images += 1
                background_false_positive_images += bool(filtered)
            for score, class_id, box in sorted(filtered, reverse=True):
                candidates = [(box_iou(box, [float(t[1]-t[3]/2), float(t[2]-t[4]/2),
                                                    float(t[1]+t[3]/2), float(t[2]+t[4]/2)]), i)
                              for i, t in enumerate(targets[0])
                              if i not in matched and int(t[0]) == class_id]
                if candidates and max(candidates)[0] >= match_iou:
                    matched.add(max(candidates)[1]); true_positive += 1
                else: false_positive += 1
            missed += len(targets[0]) - len(matched)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + missed)
    return {'true_positive': true_positive, 'false_positive': false_positive,
            'missed': missed, 'precision': precision, 'recall': recall,
            'f1': 2 * precision * recall / max(1e-9, precision + recall),
            'matching_iou': match_iou, 'background_images': background_images,
            'background_false_positive_images': background_false_positive_images,
            'background_false_positive_rate': background_false_positive_images /
                                              max(1, background_images)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--samples', type=int, default=800)
    parser.add_argument('--validation', type=int, default=160)
    parser.add_argument('--batch-size', type=int, default=12)
    parser.add_argument('--image-size', type=int, default=320)
    parser.add_argument('--width', type=int, default=8)
    parser.add_argument('--seed', type=int, default=20260927)
    parser.add_argument('--background-fraction', type=float, default=.35)
    parser.add_argument('--initial-weights', type=Path,
                        help='Resume from matching local TorchScript or state_dict weights')
    parser.add_argument('--learning-rate', type=float,
                        help='AdamW initial rate (default: 0.0015 scratch, 0.0005 resumed)')
    parser.add_argument('--output', type=Path, default=ROOT/'models/yolov5/hazard_yolov5.torchscript')
    parser.add_argument('--checkpoint', type=Path,
                        help='Optional local training checkpoint, saved even when validation fails')
    parser.add_argument('--evaluate-only', action='store_true',
                        help='Validate and export --initial-weights without further optimization')
    parser.add_argument('--quick', action='store_true', help='Small smoke training, not competition weights')
    args = parser.parse_args()
    if args.quick:
        args.epochs, args.samples, args.validation, args.image_size, args.width = 1, 32, 12, 320, 8
    if args.evaluate_only and args.initial_weights is None:
        parser.error('--evaluate-only requires --initial-weights')
    torch.manual_seed(args.seed); np.random.seed(args.seed); random.seed(args.seed)
    torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
    model = YoloV5HazardNet(len(LABELS), args.width)
    if args.initial_weights is not None:
        load_initial_weights(model, args.initial_weights)
    learning_rate = (args.learning_rate if args.learning_rate is not None else
                     (5e-4 if args.initial_weights else 1.5e-3))
    if learning_rate <= 0.:
        parser.error('--learning-rate must be positive')
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate,
                                  weight_decay=5e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.epochs, eta_min=1e-5)
    train = SyntheticHazards(args.samples, args.image_size, args.seed, augment=True,
                             background_fraction=args.background_fraction)
    validate = SyntheticHazards(args.validation, args.image_size, args.seed + 10_000_000,
                                augment=True, background_fraction=args.background_fraction)
    loader = DataLoader(train, batch_size=args.batch_size, shuffle=True, collate_fn=collate,
                        num_workers=0, drop_last=True)
    for epoch in range(0 if args.evaluate_only else args.epochs):
        model.train(); total = 0.
        for images, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = detection_loss(model, model.forward_raw(images), targets)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 10.)
            optimizer.step(); total += float(loss.detach())
        scheduler.step()
        if epoch == 0 or (epoch + 1) % 5 == 0 or epoch + 1 == args.epochs:
            print(f'epoch {epoch+1:03d}/{args.epochs} loss={total/len(loader):.4f}', flush=True)
    candidates = {str(value): evaluate(model, validate, value)
                  for value in (.30, .35, .40, .45, .50, .60, .70)}
    if args.checkpoint is not None:
        args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), args.checkpoint)
    eligible = [(float(value), result) for value, result in candidates.items()
                if result['recall'] >= .70 and result['precision'] >= .80 and
                result['background_false_positive_rate'] <= .05]
    confidence, metrics = max(
        eligible or [(float(value), result) for value, result in candidates.items()],
        key=lambda item: (item[1]['f1'], item[1]['precision']))
    print('validation sweep:', json.dumps(candidates), flush=True)
    if not args.quick and (metrics['recall'] < .70 or metrics['precision'] < .80 or
                           metrics['background_false_positive_rate'] > .05):
        raise SystemExit(f'Validation gate failed: {metrics}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    example = torch.zeros(1, 3, args.image_size, args.image_size)
    traced = torch.jit.trace(model, example, strict=False)
    torch.jit.save(traced, str(args.output))
    training_args = {key: str(value) if isinstance(value, Path) else value
                     for key, value in vars(args).items()}
    # 导出元数据分别记录原训练参数和当前验证参数。
    if args.evaluate_only:
        training_args['evaluate_only'] = False
        training_args['initial_weights'] = 'project local YOLOv5 TorchScript weights'
        training_args['checkpoint'] = str(args.initial_weights)
    metadata = {'architecture': 'YOLOv5 C3-SPPF-PAN, 3 detection scales',
                'labels': LABELS, 'image_size': args.image_size, 'width': args.width,
                'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                'training': training_args | {
                                          'max_positive_overlap_fraction': .08,
                                          'max_occluded_sign_width_fraction': .25},
                'localization_loss': 'CIoU plus grid-center smooth-L1',
                'objectness_loss': 'separately normalized positives and top hard negatives',
                'learning_rate': learning_rate,
                'negative_classes': ['true_red_box', 'blue_start_pad', 'yellow_chassis',
                                     'same_color_blank_plates', 'AprilTag', 'background_only'],
                'recommended_confidence': confidence,
                'validation': metrics, 'validation_sweep': candidates}
    args.output.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2)); print(args.output)


if __name__ == '__main__':
    main()
