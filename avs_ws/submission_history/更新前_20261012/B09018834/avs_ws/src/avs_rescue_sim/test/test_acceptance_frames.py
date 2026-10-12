"""A SLAM map frame is not the Gazebo world frame."""
import importlib.util
import math
from pathlib import Path
import pytest

path=Path(__file__).resolve().parents[1]/'tools/evaluate_run.py'
spec=importlib.util.spec_from_file_location('evaluate_run',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_marker_error_compares_registered_coordinates():
    angle=.12;tx,ty=.03,.14;x,y=2.942,1.45
    position=[math.cos(angle)*x-math.sin(angle)*y+tx,
              math.sin(angle)*x+math.cos(angle)*y+ty]
    result=dict(poses=[],markers={'0':position},marker_frames={'0':[tx,ty,angle]},
                detections=[],final={})
    report=module.evaluate(result)
    assert report['core_marker_errors_m']['0'] == pytest.approx(0.,abs=1e-12)
    assert report['raw_world_map_coordinate_difference_m']['0'] > .15
    assert not report['passed']


def test_missing_registration_is_not_assumed_identity():
    report=module.evaluate(dict(poses=[],markers={'0':[2.942,1.45]},detections=[],final={}))
    assert not report['core_marker_errors_m']
    assert not report['passed']
