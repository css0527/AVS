"""TorchScript YOLOv5 inference with letterboxing and class-aware NMS."""
import json
from pathlib import Path

import cv2
import numpy as np
import torch


class YoloV5Detector:
    def __init__(self, weights, labels, image_size=320, confidence=.60,
                 iou_threshold=.45, min_area=80, model=None, panel_verifier=None):
        self.weights = Path(weights)
        self.labels = list(labels)
        self.image_size = int(image_size)
        self.confidence = float(confidence)
        self.iou_threshold = float(iou_threshold)
        self.min_area = float(min_area)
        self.panel_verifier = panel_verifier
        if self.image_size < 160 or self.image_size % 32:
            raise ValueError('YOLOv5 image_size must be a multiple of 32 and at least 160')
        # This compact model is traced at a fixed input size. Its decode grid
        # shape is embedded in TorchScript, so a different letterbox size would
        # silently put boxes at the wrong camera pixels.
        metadata_path = self.weights.with_suffix('.json')
        if metadata_path.is_file():
            try:
                trained_size = int(json.loads(metadata_path.read_text())['image_size'])
            except (OSError, ValueError, KeyError) as exc:
                raise ValueError(f'Invalid YOLOv5 model metadata: {metadata_path}') from exc
            if trained_size != self.image_size:
                raise ValueError(f'YOLOv5 weights require image_size={trained_size}; '
                                 f'configured {self.image_size}')
        if model is None:
            if not self.weights.is_file():
                raise FileNotFoundError(
                    f'YOLOv5 weights missing: {self.weights}. '
                    'Run tools/train_yolov5_hazards.py first or select the sift backend.')
            model = torch.jit.load(str(self.weights), map_location='cpu')
        self.model = model.eval()
        torch.set_num_threads(min(2, max(1, torch.get_num_threads())))

    def letterbox(self, frame):
        h, w = frame.shape[:2]
        scale = min(self.image_size / w, self.image_size / h)
        resized_w, resized_h = max(1, round(w * scale)), max(1, round(h * scale))
        resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
        left = (self.image_size - resized_w) // 2
        top = (self.image_size - resized_h) // 2
        canvas = np.full((self.image_size, self.image_size, 3), 114, np.uint8)
        canvas[top:top + resized_h, left:left + resized_w] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float().unsqueeze(0) / 255.
        return tensor, scale, left, top

    def detect(self, frame):
        tensor, scale, left, top = self.letterbox(frame)
        with torch.inference_mode():
            predictions = self.model(tensor)
        if isinstance(predictions, (tuple, list)):
            predictions = predictions[0]
        predictions = predictions.detach().cpu().numpy()
        if predictions.ndim == 3:
            predictions = predictions[0]
        if predictions.ndim != 2 or predictions.shape[1] != len(self.labels) + 5:
            raise ValueError(
                f'Unexpected YOLOv5 output {predictions.shape}; expected [N,{len(self.labels)+5}]')

        boxes, scores, class_ids, polygons = [], [], [], []
        for row in predictions:
            class_id = int(np.argmax(row[5:]))
            score = float(row[4] * row[5 + class_id])
            if score < self.confidence:
                continue
            cx, cy, width, height = row[:4] * self.image_size
            x1 = (cx - width / 2. - left) / scale
            y1 = (cy - height / 2. - top) / scale
            x2 = (cx + width / 2. - left) / scale
            y2 = (cy + height / 2. - top) / scale
            x1, x2 = np.clip((x1, x2), 0, frame.shape[1] - 1)
            y1, y2 = np.clip((y1, y2), 0, frame.shape[0] - 1)
            width, height = x2 - x1, y2 - y1
            if width * height < self.min_area or width < 3 or height < 3:
                continue
            polygon = np.float32([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]).reshape(-1, 1, 2)
            if self.panel_verifier is not None:
                polygon = self.panel_verifier.refine(frame, self.labels[class_id], polygon)
                if polygon is None:
                    continue
            polygon = np.rint(polygon).astype(np.int32)
            minimum, maximum = polygon.reshape(-1, 2).min(axis=0), polygon.reshape(-1, 2).max(axis=0)
            width, height = maximum - minimum
            if abs(cv2.contourArea(polygon)) < self.min_area:
                continue
            boxes.append([int(minimum[0]), int(minimum[1]), int(width), int(height)])
            scores.append(score)
            class_ids.append(class_id)
            polygons.append(polygon)

        selected = []
        for class_id in sorted(set(class_ids)):
            indices = [i for i, value in enumerate(class_ids) if value == class_id]
            kept = cv2.dnn.NMSBoxes([boxes[i] for i in indices],
                                    [scores[i] for i in indices],
                                    self.confidence, self.iou_threshold)
            # The competition course contains one panel of each hazard class.
            # Verify/refit every proposal before selecting the class winner:
            # a high-confidence blue floor must not hide a real blue sign.
            kept = np.asarray(kept).reshape(-1)
            if kept.size:
                selected.append(max((indices[int(relative)] for relative in kept),
                                    key=lambda index: scores[index]))
        result = []
        for index in sorted(selected, key=lambda i: scores[i], reverse=True):
            polygon = polygons[index]
            result.append((self.labels[class_ids[index]], polygon,
                           scores[index], abs(float(cv2.contourArea(polygon)))))
        return result
