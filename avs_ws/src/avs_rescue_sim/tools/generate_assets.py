#!/usr/bin/env python3
"""Generate deterministic competition textures and the navigation map."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / 'models' / 'rescue_course' / 'materials' / 'textures'
MAPS = ROOT / 'maps'


def make_hazard(filename, bgr, title, symbol):
    image = np.full((512, 512, 3), bgr, dtype=np.uint8)
    cv2.rectangle(image, (14, 14), (497, 497), (245, 245, 245), 22)
    cv2.rectangle(image, (42, 42), (469, 469), (20, 20, 20), 6)
    if symbol == 'triangle':
        points = np.array([[256, 100], [105, 370], [407, 370]], np.int32)
        cv2.polylines(image, [points], True, (255, 255, 255), 34)
        cv2.line(image, (256, 180), (256, 285), (255, 255, 255), 28)
        cv2.circle(image, (256, 330), 16, (255, 255, 255), -1)
    elif symbol == 'diamond':
        points = np.array([[256, 90], [422, 256], [256, 422], [90, 256]], np.int32)
        cv2.polylines(image, [points], True, (255, 255, 255), 30)
        cv2.circle(image, (256, 255), 78, (255, 255, 255), 25)
    elif symbol == 'radiation':
        cv2.circle(image, (256, 250), 40, (255, 255, 255), -1)
        for angle in (-90, 30, 150):
            ellipse = np.zeros_like(image)
            cv2.ellipse(ellipse, (256, 250), (145, 145), angle, 0, 62, (255, 255, 255), -1)
            cv2.circle(ellipse, (256, 250), 62, (0, 0, 0), -1)
            image = cv2.bitwise_or(image, ellipse)
    elif symbol == 'bolt':
        points = np.array([[285, 78], [145, 280], [240, 280], [205, 435], [375, 218], [275, 218]], np.int32)
        cv2.fillPoly(image, [points], (255, 255, 255))
    elif symbol == 'bio':
        cv2.circle(image, (256, 260), 44, (255, 255, 255), -1)
        for center in ((256, 150), (160, 316), (352, 316)):
            cv2.circle(image, center, 73, (255, 255, 255), 25)
    cv2.rectangle(image, (65, 425), (447, 487), (20, 20, 20), -1)
    scale = 1.05 if len(title) < 9 else 0.78
    width = cv2.getTextSize(title, cv2.FONT_HERSHEY_DUPLEX, scale, 2)[0][0]
    cv2.putText(image, title, ((512 - width) // 2, 469), cv2.FONT_HERSHEY_DUPLEX,
                scale, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(TEXTURES / filename), image)


def make_tags():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    for tag_id in range(4):
        marker = cv2.aruco.generateImageMarker(dictionary, tag_id, 400, borderBits=1)
        canvas = np.full((512, 512), 255, dtype=np.uint8)
        canvas[56:456, 56:456] = marker
        cv2.imwrite(str(TEXTURES / f'apriltag_{tag_id}.png'), canvas)


def world_to_pixel(x, y, resolution, origin_y, height):
    px = int(round((x + 0.2) / resolution))
    py = height - 1 - int(round((y - origin_y) / resolution))
    return px, py


def make_map():
    resolution = 0.02
    origin_y = -0.2
    size = 170
    image = np.full((size, size), 254, dtype=np.uint8)

    def wall(x1, y1, x2, y2, thickness=0.10):
        p1 = world_to_pixel(x1, y1, resolution, origin_y, size)
        p2 = world_to_pixel(x2, y2, resolution, origin_y, size)
        cv2.line(image, p1, p2, 0, max(1, int(round(thickness / resolution))))

    wall(0, 0, 3, 0)
    wall(0, 3, 3, 3)
    wall(0, 0, 0, 3)
    wall(3, 0, 3, 3)
    wall(1.10, 0, 1.10, 1.90)
    wall(1.10, 1.90, 1.25, 1.90)
    wall(1.75, 1.90, 3.00, 1.90)
    cv2.imwrite(str(MAPS / 'rescue_map.pgm'), image)


def main():
    TEXTURES.mkdir(parents=True, exist_ok=True)
    MAPS.mkdir(parents=True, exist_ok=True)
    hazards = [
        ('hazard_fire.png', (25, 25, 220), 'FIRE', 'triangle'),
        ('hazard_chemical.png', (0, 125, 245), 'CHEMICAL', 'diamond'),
        ('hazard_radiation.png', (0, 225, 235), 'RADIATION', 'radiation'),
        ('hazard_electrical.png', (220, 80, 20), 'ELECTRICAL', 'bolt'),
        ('hazard_biohazard.png', (180, 20, 180), 'BIOHAZARD', 'bio'),
    ]
    for args in hazards:
        make_hazard(*args)
    make_tags()
    make_map()
    print(f'Generated textures in {TEXTURES}')
    print(f'Generated map in {MAPS}')


if __name__ == '__main__':
    main()
