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
        # Preserve the whole observed panel for the printing check. Removing
        # a fitted hazard polygon first can erase its surrounding colour while
        # leaving a clipped red tip outside the fitted corners.
        context_red = cv2.morphologyEx(red, cv2.MORPH_CLOSE,
                                      np.ones((3, 3), np.uint8))
        # Suppress recognized printed signs before connected-component analysis.
        for polygon in excluded_polygons:
            cv2.fillConvexPoly(red, np.asarray(polygon, np.int32), 0)
        red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        white = cv2.inRange(hsv, (0, 0, 135), (179, 65, 255))
        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        grouped_contours = None
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
            # A clipped FIRE triangle splits its red background into separate
            # solid components. The white printing then lies outside this
            # component's support and passes the ordinary white-fraction
            # check. A tiny fragment can belong to a large offscreen sign, so
            # its width cannot set the maximum printable stroke width. Inspect
            # context at camera resolution (61 px for 640x480), independently
            # of both the fragment dimensions and YOLO's fitted exclusion.
            size = max(5, round(min(frame.shape[:2]) / 8)) | 1
            if grouped_contours is None:
                grouped = cv2.morphologyEx(context_red, cv2.MORPH_CLOSE,
                                          np.ones((size, size), np.uint8))
                # Join across white printing, not across a grey/white wall
                # between a sign and a separate real box. Large white regions
                # spanning the image are background rather than glyphs.
                join_white = white.copy()
                component_count, components, stats, _ = cv2.connectedComponentsWithStats(white)
                height, width = white.shape
                for component in range(1, component_count):
                    left, top, cw, ch, component_area = stats[component]
                    spans_image = ((left == 0 and left + cw == width) or
                                   (top == 0 and top + ch == height))
                    if spans_image and component_area > .1 * height * width:
                        join_white[components == component] = 0
                grouped &= context_red | join_white
                # The artwork also has a thin black outline between its red
                # fill and white rim; bridge only that short separation.
                outline_size = max(3, round(min(frame.shape[:2]) / 60)) | 1
                grouped = cv2.morphologyEx(grouped, cv2.MORPH_CLOSE,
                                          np.ones((outline_size, outline_size), np.uint8))
                grouped_contours, _ = cv2.findContours(
                    grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            printed = False
            for parent in grouped_contours:
                if cv2.pointPolygonTest(parent, (x + (w - 1) / 2.,
                                                y + (h - 1) / 2.), False) < 0:
                    continue
                context = np.zeros(red.shape, np.uint8)
                cv2.drawContours(context, [parent], -1, 255, -1)
                context_support = context > 0
                printed = (np.count_nonzero(white[context_support]) /
                           max(1, np.count_nonzero(context_support)) >
                           self.max_white_fraction)
                break
            if printed:
                continue
            boxes.append((x, y, w, h))
        return sorted(boxes, key=lambda box: box[2] * box[3], reverse=True)
