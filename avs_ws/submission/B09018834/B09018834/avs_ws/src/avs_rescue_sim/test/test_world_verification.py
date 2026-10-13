from types import SimpleNamespace

from avs_rescue_sim.check_world import validate_models


def test_correct_course_is_confirmed():
    response = SimpleNamespace(success=True, model_names=['start_zone', 'west_wall'])
    assert validate_models(response, {'west_wall', 'start_zone'})


def test_other_course_is_rejected():
    response = SimpleNamespace(success=True, model_names=['ground_plane', 'maze'])
    assert not validate_models(response, {'west_wall', 'start_zone'})


def test_unavailable_or_failed_world_is_rejected():
    assert not validate_models(None, {'start_zone'})
    response = SimpleNamespace(success=False, model_names=['start_zone'])
    assert not validate_models(response, {'start_zone'})


def test_stale_rover_or_additional_course_is_rejected():
    response = SimpleNamespace(success=True, model_names=['start_zone', 'rescue_rover'])
    assert not validate_models(response, {'start_zone'})
