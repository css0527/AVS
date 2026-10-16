"""Planar stopping-envelope checks shared by the command guard and tests."""

import math

import numpy as np


def angle_difference(angle, reference):
    return math.atan2(math.sin(angle - reference), math.cos(angle - reference))


def push_progress(start, current):
    dx, dy = current[0] - start[0], current[1] - start[1]
    c, s = math.cos(start[2]), math.sin(start[2])
    return dx * c + dy * s, -dx * s + dy * c, angle_difference(current[2], start[2])


def points_near_polygon(points, polygon, margin):
    """Include the polygon interior and the Euclidean margin around its edges."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if not len(points):
        return False
    polygon = np.asarray(polygon, dtype=float)
    crosses = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        edge = b - a
        offsets = points - a
        crosses.append(edge[0] * offsets[:, 1] - edge[1] * offsets[:, 0])
        fraction = np.clip((offsets @ edge) / (edge @ edge), 0., 1.)
        separation = offsets - fraction[:, None] * edge
        if np.any(np.sum(separation ** 2, axis=1) <= margin ** 2):
            return True
    crosses = np.asarray(crosses)
    return bool(np.any(np.all(crosses >= 0, axis=0) | np.all(crosses <= 0, axis=0)))


def collision_ahead(points, footprint, linear, angular, *, margin=0.025,
                    reaction_time=0.20, linear_decel=0.5, angular_decel=0.8,
                    pushing=False):
    """Sweep the real footprint through reaction plus conservative braking time.

    During the bounded push action only, contact directly on the front pusher
    with the 30 cm target box is allowed. Side/rear contacts remain forbidden.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    footprint = np.asarray(footprint, dtype=float)
    if pushing and len(points):
        nose = float(footprint[:, 0].max())
        target_contact = ((points[:, 0] >= nose - 0.08) &
                          (points[:, 0] <= nose + 0.15) &
                          (np.abs(points[:, 1]) <= 0.19))
        points = points[~target_contact]
    horizon = reaction_time + max(abs(linear) / linear_decel,
                                  abs(angular) / angular_decel)
    for t in np.linspace(0., horizon, max(2, math.ceil(horizon / 0.04) + 1)):
        yaw = angular * t
        c, s = math.cos(yaw), math.sin(yaw)
        if abs(angular) < 1e-6:
            x, y = linear * t, 0.
        else:
            x, y = linear / angular * s, linear / angular * (1. - c)
        polygon = footprint @ np.array([[c, s], [-s, c]]) + [x, y]
        if points_near_polygon(points, polygon, margin):
            return True
    return False
