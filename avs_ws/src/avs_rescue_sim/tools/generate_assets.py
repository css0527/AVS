#!/usr/bin/env python3
"""Generate textures; optionally export a matched synthetic PGM/YAML map pair."""

import argparse
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / 'models' / 'rescue_course' / 'materials' / 'textures'


def make_hazard(filename, bgr, symbol):
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
    # Distinct geometric details preserve feature matching without printed
    # letters or numbers. These are part of each pictogram, not text labels.
    details = {
        'triangle': [(78, 87, 10), (424, 102, 16), (94, 424, 13), (175, 457, 8), (361, 452, 15)],
        'diamond': [(86, 96, 15), (425, 76, 9), (83, 410, 10), (169, 455, 16), (355, 457, 8)],
        'radiation': [(86, 81, 8), (417, 93, 14), (77, 422, 16), (188, 457, 10), (347, 454, 13)],
        'bolt': [(83, 106, 12), (418, 78, 17), (100, 422, 8), (160, 457, 12), (361, 449, 17)],
        'bio': [(88, 86, 17), (417, 101, 11), (91, 433, 10), (187, 457, 14), (342, 454, 9)],
    }
    for x, y, radius in details[symbol]:
        cv2.circle(image, (x, y), radius + 5, (20, 20, 20), -1)
        cv2.circle(image, (x, y), radius, (255, 255, 255), -1)
    cv2.imwrite(str(TEXTURES / filename), image)


def make_tags():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    colors = [(30, 30, 210), (0, 160, 240), (220, 120, 20), (190, 35, 170)]
    for tag_id in range(4):
        marker = cv2.aruco.generateImageMarker(dictionary, tag_id, 400, borderBits=1)
        canvas = np.full((512, 512), 255, dtype=np.uint8)
        canvas[56:456, 56:456] = marker
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(canvas, (0, 0), (511, 25), colors[tag_id], -1)
        cv2.rectangle(canvas, (0, 480), (511, 511), colors[tag_id], -1)
        cv2.imwrite(str(TEXTURES / f'apriltag_{tag_id}.png'), canvas)


def world_to_pixel(x, y, resolution, origin_y, height):
    px = int(round((x + 0.2) / resolution))
    py = height - 1 - int(round((y - origin_y) / resolution))
    return px, py


def make_map(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
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
    if not cv2.imwrite(str(output_dir / 'rescue_map.pgm'), image):
        raise OSError(f'Could not write map in {output_dir}')
    # The generated pixels use this origin; never reuse a SLAM map's YAML.
    (output_dir / 'rescue_map.yaml').write_text(
        'image: rescue_map.pgm\n'
        'mode: trinary\n'
        f'resolution: {resolution}\n'
        f'origin: [-0.2, {origin_y}, 0.0]\n'
        'negate: 0\n'
        'occupied_thresh: 0.65\n'
        'free_thresh: 0.25\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--map-output', type=Path,
        help='Also write a synthetic rescue_map.pgm/YAML pair in this directory. '
             'Omit to preserve the saved navigation map.')
    args = parser.parse_args(argv)
    TEXTURES.mkdir(parents=True, exist_ok=True)
    hazards = [
        ('hazard_fire.png', (25, 25, 220), 'triangle'),
        ('hazard_chemical.png', (0, 125, 245), 'diamond'),
        ('hazard_radiation.png', (0, 225, 235), 'radiation'),
        ('hazard_electrical.png', (220, 80, 20), 'bolt'),
        ('hazard_biohazard.png', (180, 20, 180), 'bio'),
    ]
    for hazard_args in hazards:
        make_hazard(*hazard_args)
    make_tags()
    print(f'Generated textures in {TEXTURES}')
    if args.map_output is not None:
        make_map(args.map_output)
        print(f'Generated map pair in {args.map_output}')


if __name__ == '__main__':
    main()
