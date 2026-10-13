"""Verify a YOLO proposal against the visible pictogram, then fit its panel.

Colour locates the panel; a registered white glyph validates it.  A plain
coloured rover part, floor patch or push box therefore cannot pass on colour
alone.  All measurements come from the camera and the supplied artwork.
"""
from pathlib import Path

import cv2
import numpy as np


class PanelGeometryVerifier:
    """Return a tight four-corner polygon, or ``None`` for a false proposal."""

    def __init__(self, textures_dir, labels=None, min_side=6., symbol_score=.34):
        self.labels = list(labels or [
            'FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD'])
        self.min_side = float(min_side)
        self.symbol_score = float(symbol_score)
        self.templates = {}
        self.side = 72
        for label in self.labels:
            image = cv2.imread(str(Path(textures_dir) / f'hazard_{label.lower()}.png'))
            if image is None:
                raise FileNotFoundError(f'Missing pictogram artwork for {label}')
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            coloured = (hsv[..., 1] > 120) & (hsv[..., 2] > 60)
            if not np.any(coloured):
                raise ValueError(f'Pictogram {label} has no coloured panel')
            histogram = np.bincount(hsv[..., 0][coloured], minlength=180)
            hue = int(histogram.argmax())
            resized = cv2.resize(image, (self.side, self.side), interpolation=cv2.INTER_AREA)
            small = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
            white = (small[..., 1] < 75) & (small[..., 2] > 180)
            self.templates[label] = (hue, self._interior(white), white)

    @staticmethod
    def _ordered(points):
        points = np.asarray(points, np.float32).reshape(4, 2)
        centre = points.mean(axis=0)
        order = np.argsort(np.arctan2(points[:, 1] - centre[1],
                                     points[:, 0] - centre[0]))
        points = points[order]
        return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)

    @staticmethod
    def _interior(mask):
        # Border and decorative bolts must not count as a pictogram glyph.
        result = np.zeros_like(mask, dtype=bool)
        margin = int(round(mask.shape[0] * .16))
        result[margin:-margin, margin:-margin] = mask[margin:-margin, margin:-margin]
        return result

    def _white_mask(self, image):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        coloured = (hsv[..., 1] > 95) & (hsv[..., 2] > 35)
        if coloured.mean() < .15:
            return None
        saturation = float(np.median(hsv[..., 1][coloured]))
        brightness = float(np.median(hsv[..., 2][coloured]))
        white = ((hsv[..., 1] < max(75., min(165., saturation * .72))) &
                 (hsv[..., 2] > max(40., brightness * .85)))
        return white

    def _glyph_score(self, image, label):
        white = self._white_mask(image)
        if white is None:
            return 0.
        white = self._interior(white)
        if white.mean() < .025:
            return 0.
        template = self.templates[label][1]
        # A few pixels of alignment tolerance cover small/blurred panel edges.
        best = 0.
        for dy in (-3, 0, 3):
            for dx in (-3, 0, 3):
                shifted = cv2.warpAffine(template.astype(np.uint8),
                    np.float32([[1, 0, dx], [0, 1, dy]]), (self.side, self.side),
                    flags=cv2.INTER_NEAREST).astype(bool)
                overlap = np.logical_and(white, shifted).sum()
                best = max(best, 2. * overlap / max(1, white.sum() + shifted.sum()))
        return best

    def _fit_rim(self, frame, quad, label, destination):
        # The outer colour sliver is only 3/512 of the artwork. At a distance
        # it disappears, leaving the colour component inside the white rim.
        # Search the visible rim to restore the complete panel extent.
        edge = np.ones((self.side, self.side), bool)
        margin = int(round(self.side * .12))
        edge[margin:-margin, margin:-margin] = False
        expected = self.templates[label][2] & edge
        centre = quad.mean(axis=0)
        fitted = []
        for expansion in (1., 1.04, 1.08, 1.12, 1.16):
            corners = centre + (quad - centre) * expansion
            transform = cv2.getPerspectiveTransform(corners.astype(np.float32), destination)
            warped = cv2.warpPerspective(frame, transform, (self.side, self.side))
            white = self._white_mask(warped)
            if white is None:
                continue
            glyph = self._glyph_score(warped, label)
            actual = white & edge
            overlap = np.logical_and(actual, expected).sum()
            rim = 2. * overlap / max(1, actual.sum() + expected.sum())
            fitted.append((.70 * glyph + .30 * rim, corners))
        return max(fitted, key=lambda item: item[0])[1] if fitted else quad

    def refine(self, frame, label, polygon):
        """Fit/validate a candidate in original image coordinates.

        ``polygon`` can be the four corners of a YOLO axis-aligned box.  The
        result has shape ``[4, 1, 2]`` (OpenCV polygon convention).  Invalid or
        unverified candidates return ``None``; no stale geometry is retained.
        """
        if label not in self.templates:
            return None
        points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
        if len(points) < 3 or not np.isfinite(points).all():
            return None
        minimum, maximum = points.min(axis=0), points.max(axis=0)
        width, height = maximum - minimum
        if min(width, height) < 3:
            return None
        padding = np.maximum(np.array([width, height]) * .30, 4.)
        start = np.maximum(0, np.floor(minimum - padding)).astype(int)
        stop = np.minimum([frame.shape[1], frame.shape[0]],
                          np.ceil(maximum + padding)).astype(int)
        if np.any(stop - start < 5):
            return None
        crop = frame[start[1]:stop[1], start[0]:stop[0]]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue = self.templates[label][0]
        difference = np.abs(hsv[..., 0].astype(np.int16) - hue)
        difference = np.minimum(difference, 180 - difference)
        mask = np.uint8((difference <= 13) & (hsv[..., 1] > 95) &
                        (hsv[..., 2] > 35)) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        destination = np.float32([[0, 0], [self.side - 1, 0],
                                  [self.side - 1, self.side - 1], [0, self.side - 1]])
        centre = (minimum + maximum) * .5
        candidate_area = width * height
        proposals = []
        for contour in contours:
            if cv2.contourArea(contour) < 36:
                continue
            hull = cv2.convexHull(contour)
            outline = cv2.approxPolyDP(hull, .025 * cv2.arcLength(hull, True), True)
            if len(outline) == 4:
                quad = self._ordered(outline)
            else:
                quad = self._ordered(cv2.boxPoints(cv2.minAreaRect(hull)))
            lengths = np.linalg.norm(quad - np.roll(quad, 1, axis=0), axis=1)
            # A nearly edge-on strip may show only the coloured/white border.
            # It is insufficient evidence for the pictogram even if warping
            # the few white border pixels resembles part of the template.
            if lengths.min() < self.min_side or lengths.max() / lengths.min() > 3.:
                continue
            if cv2.contourArea(hull) / max(1., cv2.contourArea(quad)) < .65:
                continue
            quad += start
            qmin, qmax = quad.min(axis=0), quad.max(axis=0)
            intersection = np.maximum(0., np.minimum(maximum, qmax) -
                                      np.maximum(minimum, qmin)).prod()
            panel_area = (qmax - qmin).prod()
            if intersection / max(1., min(candidate_area, panel_area)) < .30:
                continue
            transform = cv2.getPerspectiveTransform(quad, destination)
            warped = cv2.warpPerspective(frame, transform, (self.side, self.side))
            score = self._glyph_score(warped, label)
            if score < self.symbol_score:
                continue
            quad = self._fit_rim(frame, quad, label, destination)
            distance = np.linalg.norm(quad.mean(axis=0) - centre) / max(1., np.hypot(width, height))
            proposals.append((score - .15 * distance, quad))
        if not proposals:
            return None
        _, quad = max(proposals, key=lambda item: item[0])
        quad[:, 0] = np.clip(quad[:, 0], 0, frame.shape[1] - 1)
        quad[:, 1] = np.clip(quad[:, 1], 0, frame.shape[0] - 1)
        return np.rint(quad).astype(np.int32).reshape(4, 1, 2)
