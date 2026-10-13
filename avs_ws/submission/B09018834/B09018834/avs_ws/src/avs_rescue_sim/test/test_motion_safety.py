import math
from pathlib import Path
import sys

import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from avs_rescue_sim.motion_safety import collision_ahead, push_progress


@pytest.fixture
def footprint():
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config/nav_params.yaml').read_text())
    return yaml.safe_load(config['local_costmap']['local_costmap']['ros__parameters']['footprint'])


def test_front_obstacle_stops_before_contact(footprint):
    assert collision_ahead([[0.40, 0.0]], footprint, 0.12, 0.0)
    assert not collision_ahead([[0.70, 0.0]], footprint, 0.12, 0.0)


def test_higher_speed_requires_more_forward_clearance(footprint):
    assert not collision_ahead([[.50, 0.]], footprint, .12, 0., margin=.035)
    assert collision_ahead([[.50, 0.]], footprint, .24, 0., margin=.035)


def test_faster_turn_checks_a_larger_pusher_sweep(footprint):
    assert not collision_ahead([[.12, .21]], footprint, 0., .35, margin=.035)
    assert collision_ahead([[.12, .21]], footprint, 0., .55, margin=.035)


def test_clear_corridor_allows_forward_and_turning(footprint):
    x = np.linspace(-.8, .8, 100)
    walls = np.vstack([np.column_stack([x, np.full_like(x, y)]) for y in [-.5, .5]])
    assert not collision_ahead(walls, footprint, .12, 0.)
    assert not collision_ahead(walls, footprint, 0., .4)


def test_rotation_checks_front_pusher_sweep(footprint):
    point = [[0.33, 0.14]]
    assert not collision_ahead(point, footprint, 0., 0.)
    assert collision_ahead(point, footprint, 0., .4)


def test_push_exception_only_allows_target_front_contact(footprint):
    target = [[.36, 0.], [.37, .14]]
    assert collision_ahead(target, footprint, .10, 0., pushing=False)
    assert not collision_ahead(target, footprint, .10, 0., pushing=True)
    # A wall beside the pusher must still stop the robot during a push.
    assert collision_ahead([[.19, .16]], footprint, .10, 0., pushing=True)
    assert collision_ahead([[-.21, 0.]], footprint, .10, 0., pushing=True)


def test_signed_push_progress_does_not_count_lateral_or_reverse_motion():
    assert push_progress((1., 2., 0.), (1., 2.5, 0.)) == (0., .5, 0.)
    assert push_progress((1., 2., 0.), (.8, 2., 0.))[0] < 0.
    forward, sideways, yaw = push_progress((1.5, 2.55, -math.pi/2), (1.52, 1.55, -math.pi/2+.05))
    assert forward == pytest.approx(1.)
    assert sideways == pytest.approx(.02)
    assert yaw == pytest.approx(.05)
