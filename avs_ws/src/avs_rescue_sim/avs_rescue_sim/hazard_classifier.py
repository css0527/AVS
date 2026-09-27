"""Verify printed hazard artwork using local features and projective geometry."""
from pathlib import Path
import cv2
import numpy as np


class HazardClassifier:
    def __init__(self, texture_dir, labels, min_inliers=7, min_area=900):
        self.sift = cv2.SIFT_create(nfeatures=1200, contrastThreshold=0.025)
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.min_inliers, self.min_area = min_inliers, min_area
        self.templates = {}
        for label in labels:
            template = cv2.imread(str(Path(texture_dir) / f'hazard_{label.lower()}.png'))
            if template is None:
                raise ValueError(f'Missing artwork for {label}')
            points, descriptors = self.sift.detectAndCompute(cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), None)
            hsv = cv2.cvtColor(template, cv2.COLOR_BGR2HSV)
            color = hsv[(hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)]
            self.templates[label] = (points, descriptors, template.shape[:2], float(np.median(color[:, 0])))

    def detect(self, frame):
        points, descriptors = self.sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
        if descriptors is None or len(points) < self.min_inliers:
            return []
        found = []
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for label, (reference, features, (h, w), hue) in self.templates.items():
            pairs = self.matcher.knnMatch(features, descriptors, k=2)
            good = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .70 * b.distance]
            if len(good) < self.min_inliers:
                continue
            src = np.float32([reference[m.queryIdx].pt for m in good])
            dst = np.float32([points[m.trainIdx].pt for m in good])
            homography, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
            if homography is None or int(inliers.sum()) < self.min_inliers:
                continue
            support = src[inliers.ravel().astype(bool)]
            if cv2.contourArea(cv2.convexHull(support)) < w * h * .06:
                continue
            corners = np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]).reshape(-1, 1, 2)
            projected = cv2.perspectiveTransform(corners, homography)
            if not np.isfinite(projected).all() or not cv2.isContourConvex(projected):
                continue
            area = cv2.contourArea(projected)
            if not self.min_area <= area <= frame.shape[0] * frame.shape[1] * .9:
                continue
            x, y, width, height = cv2.boundingRect(projected)
            viewport = np.float32([[0, 0], [frame.shape[1], 0],
                                   [frame.shape[1], frame.shape[0]], [0, frame.shape[0]]])
            visible_area, _ = cv2.intersectConvexConvex(projected, viewport)
            # A scanning camera may clip one edge; accept only when most of
            # the fitted plate and enough distributed artwork remain visible.
            if visible_area < area * .60:
                continue
            mask = np.zeros(frame.shape[:2], np.uint8)
            cv2.fillConvexPoly(mask, projected.astype(np.int32), 255)
            pixels = hsv[(mask > 0) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 50)]
            if len(pixels) < area * .15:
                continue
            delta = np.abs(pixels[:, 0].astype(float) - hue)
            if np.mean(np.minimum(delta, 180-delta) < 12) < .65:
                continue
            found.append((label, projected.astype(np.int32), int(inliers.sum()), area))
        return found
