"""Image-only detector for this course's solid red push box."""
import cv2
import numpy as np


class BarrierDetector:
    def __init__(self, min_area=700, min_fill=.82, max_white_fraction=.08):
        self.min_area = min_area
        self.min_fill = min_fill
        self.max_white_fraction = max_white_fraction

    def detect(self, frame, excluded_polygons=()):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 160, 45), (9, 255, 255))
        red |= cv2.inRange(hsv, (172, 160, 45), (179, 255, 255))
        # Suppress recognized printed signs before connected-component analysis.
        for polygon in excluded_polygons:
            cv2.fillConvexPoly(red, np.asarray(polygon, np.int32), 0)
        red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        white = cv2.inRange(hsv, (0, 0, 135), (179, 65, 255))
        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            # AprilTag trim and isolated thin red edges are not a box face.
            if min(w, h) < 18 or not .2 <= w / h <= 5.0:
                continue
            # A slanted AprilTag border can have a wide axis-aligned box even
            # though the red strip itself is thin. Check its rotated shape too.
            sides = cv2.minAreaRect(contour)[1]
            if min(sides) < 18 or max(sides) / min(sides) > 5.0:
                continue
            filled = np.zeros(red.shape, np.uint8)
            cv2.drawContours(filled, [contour], -1, 255, -1)
            support = filled > 0
            count = np.count_nonzero(support)
            if np.count_nonzero(red[support]) / count < self.min_fill:
                continue
            if np.count_nonzero(white[support]) / count > self.max_white_fraction:
                continue
            hull_area = cv2.contourArea(cv2.convexHull(contour))
            if hull_area <= 0 or area / hull_area < .90:
                continue
            boxes.append((x, y, w, h))
        return sorted(boxes, key=lambda box: box[2] * box[3], reverse=True)
