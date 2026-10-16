import numpy as np
import pytest

from avs_rescue_sim.hazard_tracker import HazardTracker


def detection(x=100, y=80, width=40, height=60, score=.9):
    polygon = np.float32([[x, y], [x+width, y], [x+width, y+height], [x, y+height]])
    return 'RADIATION', polygon.reshape(-1, 1, 2), score, width*height


def test_panning_small_sign_associates_without_overlap_and_centre_lag():
    tracker = HazardTracker()
    assert tracker.update([detection()], (480, 640, 3))[0].streak == 1
    moved = tracker.update([detection(x=180, width=42)], (480, 640, 3))[0]
    assert moved.streak == 2
    assert moved.polygon.reshape(-1, 2).mean(axis=0).tolist() == pytest.approx([201, 110])
    assert np.ptp(moved.polygon.reshape(-1, 2), axis=0)[0] == pytest.approx(41.3)


def test_missing_observation_clears_box_and_consecutive_confirmation():
    tracker = HazardTracker()
    tracker.update([detection()], (480, 640, 3))
    tracker.update([detection()], (480, 640, 3))
    assert tracker.update([], (480, 640, 3)) == []
    assert tracker.tracks == {}
    assert tracker.update([detection()], (480, 640, 3))[0].streak == 1


def test_teleporting_or_extreme_scale_candidate_starts_new_track():
    tracker = HazardTracker()
    tracker.update([detection()], (480, 640, 3))
    assert tracker.update([detection(x=450)], (480, 640, 3))[0].streak == 1
    assert tracker.update([detection(x=450, width=8, height=8)], (480, 640, 3))[0].streak == 1


def test_distant_tiny_sign_cannot_jump_by_many_own_widths():
    tracker = HazardTracker()
    tracker.update([detection(width=12, height=12)], (480, 640, 3))
    assert tracker.update([detection(x=175, width=12, height=12)], (480, 640, 3))[0].streak == 1


def test_approaching_panel_adapts_immediately_instead_of_drawing_old_size():
    tracker = HazardTracker(smoothing_alpha=.5)
    tracker.update([detection()], (480, 640, 3))
    result = tracker.update([detection(width=60, height=90)], (480, 640, 3))[0]
    assert result.streak == 2
    assert np.ptp(result.polygon.reshape(-1, 2), axis=0).tolist() == [60, 90]


def test_invalid_smoothing_configuration_is_rejected():
    with pytest.raises(ValueError):
        HazardTracker(smoothing_alpha=0)
