"""Associate verified camera panels and steady their displayed outlines."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class HazardTrack:
    name: str
    polygon: np.ndarray
    raw_polygon: np.ndarray
    score: float
    area: float
    streak: int


def bounds_iou(first, second):
    first, second = first.reshape(-1, 2), second.reshape(-1, 2)
    amin, amax = first.min(axis=0), first.max(axis=0)
    bmin, bmax = second.min(axis=0), second.max(axis=0)
    intersection = np.maximum(0., np.minimum(amax, bmax) - np.maximum(amin, bmin)).prod()
    union = (amax - amin).prod() + (bmax - bmin).prod() - intersection
    return float(intersection / max(1., union))


class HazardTracker:
    """Track the course's single panel per class without retaining missed boxes.

    Camera panning can move a distant sign by more than its width between
    frames. Association therefore allows a bounded image displacement as well
    as overlap. Smoothing acts on corner offsets about the *current* centre,
    so a moving camera does not leave a rectangle behind the sign.
    """

    def __init__(self, smoothing_alpha=.65, max_center_step=.18):
        if not 0. < smoothing_alpha <= 1. or not 0. < max_center_step < 1.:
            raise ValueError('Invalid hazard tracker smoothing or displacement')
        self.alpha = float(smoothing_alpha)
        self.max_center_step = float(max_center_step)
        self.tracks = {}

    def update(self, detections, frame_shape):
        updated = {}
        for name, polygon, score, _area in detections:
            # Both inference backends may propose several observations. Use
            # one verified observation of each physical course panel.
            if name in updated and score <= updated[name].score:
                continue
            raw = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
            area = abs(float(cv2.contourArea(raw)))
            if area <= 0. or not np.isfinite(raw).all():
                continue
            previous = self.tracks.get(name)
            streak, displayed = 1, raw.copy()
            if previous is not None and previous.raw_polygon.shape == raw.shape:
                current_points = raw.reshape(-1, 2)
                previous_points = previous.raw_polygon.reshape(-1, 2)
                centre = current_points.mean(axis=0)
                old_centre = previous_points.mean(axis=0)
                ratio = area / max(1., abs(float(cv2.contourArea(previous.raw_polygon))))
                displacement = float(np.linalg.norm(centre - old_centre))
                extent = max(np.linalg.norm(np.ptp(current_points, axis=0)),
                             np.linalg.norm(np.ptp(previous_points, axis=0)))
                # A 20 px sign cannot legitimately teleport 100 px merely
                # because the camera image is wide. Larger nearby signs can
                # still move quickly when the pan motor scans.
                nearby = displacement <= min(self.max_center_step * frame_shape[1],
                                             1.8 * extent)
                associated = (.35 <= ratio <= 2.8 and
                              (bounds_iou(raw, previous.raw_polygon) >= .15 or nearby))
                if associated:
                    streak = previous.streak + 1
                    # Adapt immediately when approaching a sign or when its
                    # outline changes strongly; smooth only small shape jitter.
                    if .75 <= ratio <= 1.33:
                        old = previous.polygon.reshape(-1, 2)
                        displayed = (centre + self.alpha * (current_points - centre) +
                                     (1. - self.alpha) * (old - old.mean(axis=0)))
                        displayed = displayed.reshape(-1, 1, 2)
            updated[name] = HazardTrack(name, displayed, raw, float(score), area, streak)
        # A missing sign disappears immediately and loses its confirmation
        # streak. Reappearing proposals must establish fresh observations.
        self.tracks = updated
        return list(updated.values())
