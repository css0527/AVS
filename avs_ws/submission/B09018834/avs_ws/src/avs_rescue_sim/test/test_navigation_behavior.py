"""Exercise command interlocks and mission transitions without starting DDS."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip('rclpy')
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from avs_rescue_sim.mission_node import MissionNode
from avs_rescue_sim.safety_node import SafetyNode


@pytest.fixture
def guard():
    scan = LaserScan()
    scan.ranges = [float('inf')] * 20
    cmd = Twist()
    cmd.linear.x = .1
    return SimpleNamespace(
        seconds=lambda: 10., command=cmd, command_received=10.,
        scan=scan, scan_received=10., odom_received=10., push_requested=False,
        push_received=10., emergency_stop=False, velocity=(0., 0.),
        timeout=.35, margin=.035, last_reason=None, release_start=None,
        max_linear_velocity=.24, max_angular_velocity=.6,
        footprint=[[-.21,-.12],[.353,-.194],[.353,.194],[-.21,.12]],
        scan_points=lambda: np.array([[.8, 0.]]), output=Mock(), status=Mock(),
        get_logger=lambda: Mock())


@pytest.mark.parametrize('fault', ['reverse', 'stale_scan', 'stale_odom', 'stale_command',
                                 'stop', 'nan', 'bad_odom', 'empty_scan'])
def test_guard_stops_on_fault(guard, fault):
    if fault == 'reverse': guard.command.linear.x = -.1
    if fault == 'stale_scan': guard.scan_received = 9.
    if fault == 'stale_odom': guard.odom_received = 9.
    if fault == 'stale_command': guard.command_received = 9.
    if fault == 'stop': guard.emergency_stop = True
    if fault == 'nan': guard.command.angular.z = float('nan')
    if fault == 'bad_odom': guard.velocity = (float('nan'), 0.)
    if fault == 'empty_scan': guard.scan.ranges = [float('-inf')] * 20
    SafetyNode.tick(guard)
    sent = guard.output.publish.call_args.args[0]
    assert sent.linear.x == 0. and sent.angular.z == 0.


def test_guard_passes_clear_forward_command(guard):
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .1


@pytest.mark.parametrize('angular', [-2., 2.])
@pytest.mark.parametrize('linear_limit,angular_limit', [(.24, .6), (.30, .75)])
def test_guard_applies_configured_limits_in_both_turn_directions(
        guard, angular, linear_limit, angular_limit):
    guard.max_linear_velocity = linear_limit
    guard.max_angular_velocity = angular_limit
    guard.command.linear.x = .8
    guard.command.angular.z = angular
    guard.scan_points = lambda: np.array([[2., 0.]])
    SafetyNode.tick(guard)
    sent = guard.output.publish.call_args.args[0]
    assert sent.linear.x == linear_limit
    assert sent.angular.z == np.sign(angular) * angular_limit


def test_fast_command_passes_clear_space_and_stops_for_its_braking_distance(guard):
    guard.max_linear_velocity = .30
    guard.command.linear.x = .30
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .30
    guard.scan_points = lambda: np.array([[.58, 0.]])
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == 0.


def test_faster_navigation_keeps_push_speed_limited(guard):
    guard.command.linear.x = .24
    guard.push_requested = True
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .10


def test_faster_command_checks_a_longer_stopping_envelope(guard):
    guard.scan_points = lambda: np.array([[.50, 0.]])
    guard.command.linear.x = .12
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .12
    guard.command.linear.x = .24
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == 0.


def test_actual_velocity_is_not_clamped_to_the_requested_limit(guard):
    guard.scan_points = lambda: np.array([[.58, 0.]])
    guard.command.linear.x = .05
    guard.velocity = (.24, 0.)
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .05
    guard.velocity = (.30, 0.)
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == 0.


def test_stale_push_permission_cannot_bypass_obstacle(guard):
    guard.push_requested = True
    guard.scan_points = lambda: np.array([[.36, 0.]])
    guard.push_received = 9.
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == 0.
    guard.push_received = 10.
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .1


def test_push_allows_box_corner_within_pusher_but_not_door_frame(guard):
    guard.push_requested = True
    guard.scan_points = lambda: np.array([[.32, .185]])
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == .1
    guard.scan_points = lambda: np.array([[.32, .22]])
    SafetyNode.tick(guard)
    assert guard.output.publish.call_args.args[0].linear.x == 0.


def test_camera_observation_never_drives_the_base():
    mission = SimpleNamespace(
        state='observing', publish_stop=Mock(), step_expected=['FIRE'],
        step_types=['corridor'], step_index=0, detected_hazards=set(),
        detected_tags=set(), elapsed=lambda: 2., now_seconds=lambda: 10.,
        deadline=20., fail_mission=Mock(), advance_step=Mock(), report=Mock())
    MissionNode.tick(mission)
    mission.publish_stop.assert_called_once()
    mission.advance_step.assert_not_called()
    mission.now_seconds = lambda: 21.
    MissionNode.tick(mission)
    mission.fail_mission.assert_called_once()


def test_core_observation_uses_tags_without_moving():
    mission = SimpleNamespace(
        state='observing', publish_stop=Mock(), step_expected=['2'],
        step_types=['observe_core'], step_index=0, detected_hazards=set(),
        detected_tags={'2'}, elapsed=lambda: 2., now_seconds=lambda: 10.,
        deadline=20., fail_mission=Mock(), advance_step=Mock(), report=Mock())
    MissionNode.tick(mission)
    mission.publish_stop.assert_called_once()
    mission.advance_step.assert_called_once()
    mission.fail_mission.assert_not_called()


def test_return_rotation_targets_current_pose_not_old_waypoint():
    from rclpy.time import Time
    tf=Mock()
    tf.lookup_transform.return_value.transform.translation=SimpleNamespace(x=1.65,y=1.34)
    mission=SimpleNamespace(poses={'align':(1.62,1.46,1.5708)},
        step_types=['return_rotate'],step_index=0,tf_buffer=tf,map_frame='map',
        get_clock=lambda: SimpleNamespace(now=lambda: Time(seconds=10.)),
        navigation_behavior_tree='/trees/navigate_to_pose_no_recovery.xml',
        precision_navigation_steps=set(),
        report=Mock(),now_seconds=lambda:10.,navigation_timeout=60.,
        nav_client=Mock(),goal_response_callback=Mock(),fail_mission=Mock())
    MissionNode.send_navigation_goal(mission,'align')
    goal=mission.nav_client.send_goal_async.call_args.args[0]
    assert goal.pose.pose.position.x == 1.65
    assert goal.pose.pose.position.y == 1.34
    assert goal.behavior_tree.endswith('/turn_at_current_pose.xml')


@pytest.mark.parametrize('step_type,align,precision,tree,current_pose', [
    ('navigate', False, False, '/trees/approach_pose.xml', False),
    ('navigate', True, False, '/trees/turn_at_current_pose.xml', True),
    ('return', False, True, '/custom/precision_navigation.xml', False),
    ('return', True, True, '/custom/precision_rotation.xml', True),
    ('turn', False, True, '/custom/precision_rotation.xml', True),
    ('return_rotate', False, True, '/custom/precision_rotation.xml', True),
    ('release', False, True, '/trees/release_pusher.xml', True),
    ('release', False, False, '/trees/release_pusher.xml', True),
])
def test_mission_selects_bounded_passage_controller_without_changing_release(
        step_type, align, precision, tree, current_pose):
    from rclpy.time import Time
    tf = Mock()
    tf.lookup_transform.return_value.transform.translation = SimpleNamespace(x=1.63, y=1.51)
    mission = SimpleNamespace(
        poses={'waypoint': (1.50, 2.40, 1.75)}, step_types=[step_type], step_index=0,
        tf_buffer=tf, map_frame='map',
        get_clock=lambda: SimpleNamespace(now=lambda: Time(seconds=10.)),
        navigation_behavior_tree='/trees/navigate_to_pose_no_recovery.xml',
        precision_navigation_steps={'waypoint'} if precision else set(),
        precision_navigation_behavior_tree='/custom/precision_navigation.xml',
        precision_rotation_behavior_tree='/custom/precision_rotation.xml',
        odom_pose=(1.63, 1.51, 1.75), release_timeout=12., navigation_timeout=60.,
        report=Mock(), now_seconds=lambda: 10., nav_client=Mock(),
        goal_response_callback=Mock(), fail_mission=Mock())
    MissionNode.send_navigation_goal(mission, 'waypoint', align=align)
    goal = mission.nav_client.send_goal_async.call_args.args[0]
    assert goal.behavior_tree == tree
    assert (goal.pose.pose.position.x, goal.pose.pose.position.y) == (
        (1.63, 1.51) if current_pose else (1.50, 2.40))
    assert mission.deadline == (22. if step_type == 'release' else 70.)
    mission.fail_mission.assert_not_called()


@pytest.mark.parametrize('filename,goal_checker', [
    ('navigate_to_pose_precision.xml', 'position_goal_checker'),
    ('turn_at_current_pose_precision.xml', 'turn_goal_checker'),
])
def test_precision_trees_preserve_goal_checks_and_disable_recovery(filename, goal_checker):
    import xml.etree.ElementTree as ET
    root = ET.parse(Path(__file__).resolve().parents[1] / 'behavior_trees' / filename)
    follow = root.find('.//FollowPath')
    assert follow.get('controller_id') == 'PrecisionPath'
    assert follow.get('goal_checker_id') == goal_checker
    assert root.find('.//ComputePathToPose').get('planner_id') == 'GridBased'
    assert not {element.tag for element in root.iter()} & {'Spin', 'BackUp', 'RecoveryNode'}


def test_position_arrival_aligns_before_reporting_waypoint_reached():
    from action_msgs.msg import GoalStatus
    future=Mock()
    future.result.return_value=SimpleNamespace(status=GoalStatus.STATUS_SUCCEEDED)
    node=SimpleNamespace(mission_failed=False,nav_phase='travel',step_index=0,
        step_types=['navigate'],step_names=['top_corner'],publish_stop=Mock(),
        send_navigation_goal=Mock(),report=Mock())
    MissionNode.navigation_result_callback(node,future)
    node.send_navigation_goal.assert_called_once_with('top_corner',align=True)
    node.report.assert_not_called()
    node.nav_phase='align'
    MissionNode.navigation_result_callback(node,future)
    assert node.report.call_args.args[0] == 'settling'


def test_one_transient_navigation_failure_replans_then_stops_on_repeat():
    mission = SimpleNamespace(
        retry_count=0, max_nav_retries=1, step_index=0,
        step_names=['room_exit_outside'], abort_on_nav_failure=True,
        report=Mock(), send_navigation_goal=Mock(), fail_mission=Mock())
    MissionNode.navigation_failed(mission, 'Nav2 status=6')
    mission.send_navigation_goal.assert_called_once_with('room_exit_outside')
    mission.fail_mission.assert_not_called()
    MissionNode.navigation_failed(mission, 'Nav2 status=6')
    mission.fail_mission.assert_called_once_with('room_exit_outside: Nav2 status=6')


def test_return_doorway_destination_is_on_passage_centreline():
    from pathlib import Path
    import yaml
    config = yaml.safe_load((Path(__file__).resolve().parents[1] /
                             'config/mission_params.yaml').read_text())
    waypoint = config['mission_node']['ros__parameters']['waypoints.room_exit_outside']
    assert abs(waypoint[0] - 1.50) <= .02
    assert waypoint[1] > 2.10


def test_unexpected_outbound_turn_stops_instead_of_circling():
    mission = SimpleNamespace(
        state='navigating', safety_blocked_since=None, step_names=['corridor_fire'],
        step_types=['corridor'], step_index=0, now_seconds=lambda: 10., deadline=20.,
        nav_rotation=2.5, nav_heading_change=2.5, max_outbound_rotation=2.2,
        max_rotation_travel=3.6, fail_mission=Mock())
    MissionNode.tick(mission)
    mission.fail_mission.assert_called_once()


def test_push_timeout_is_failure_not_success():
    mission = SimpleNamespace(
        odom_pose=(1.5, 2.5, -1.5708), odom_stamp=10., now_seconds=lambda: 10.,
        push_start_pose=(1.5, 2.5, -1.5708), push_max_lateral_error=.04,
        push_max_heading_error=.12, push_distance=1.08, push_timeout=18.,
        elapsed=lambda: 19., fail_mission=Mock(), cmd_pub=Mock())
    MissionNode.update_push(mission)
    mission.fail_mission.assert_called_once()
    mission.cmd_pub.publish.assert_not_called()


@pytest.mark.parametrize('parameter,planner', [
    ('default_nav_to_pose_bt_xml', 'ComputePathToPose'),
    ('default_nav_through_poses_bt_xml', 'ComputePathThroughPoses'),
])
def test_launch_uses_no_recovery_tree_for_both_navigators(tmp_path, monkeypatch, parameter, planner):
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros_logs'))
    from launch import LaunchContext
    root = Path(__file__).resolve().parents[1]
    path = root / 'launch/sim_launch.py'
    spec = importlib.util.spec_from_file_location('avs_launch_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rewritten = []
    constructor = module.RewrittenYaml
    def capture(**kwargs):
        result = constructor(**kwargs)
        rewritten.append(result)
        return result
    module.RewrittenYaml = capture
    nodes = []
    node_constructor = module.Node
    def capture_node(**kwargs):
        nodes.append(kwargs)
        return node_constructor(**kwargs)
    module.Node = capture_node
    module.generate_launch_description()
    output = Path(rewritten[0].perform(LaunchContext()))
    data = yaml.safe_load(output.read_text())
    tree = Path(data['bt_navigator']['ros__parameters'][parameter])
    assert tree.is_file()
    import xml.etree.ElementTree as ET
    tags = {e.tag for e in ET.parse(tree).iter()}
    assert {'FollowPath', planner} <= tags
    assert not tags & {'Spin', 'BackUp', 'RecoveryNode'}
    # A later change of initial_pose cannot silently leave Gazebo at old coordinates.
    spawn = next(n for n in nodes if n['executable'] == 'spawn_entity.py')['arguments']
    initial = data['amcl']['ros__parameters']['initial_pose']
    for flag, field in [('-x', 'x'), ('-y', 'y'), ('-Y', 'yaw')]:
        assert float(spawn[spawn.index(flag) + 1]) == initial[field]
    guard_params = next(n for n in nodes if n['executable'] == 'safety_node')['parameters'][0]
    limits = data['velocity_smoother']['ros__parameters']
    assert guard_params['max_linear_velocity'] == limits['max_velocity'][0]
    assert guard_params['max_angular_velocity'] == min(limits['max_velocity'][2],
                                                       -limits['min_velocity'][2])

    actions = [object()]
    callback = module.after_success(actions, 'verification failed')
    assert callback(SimpleNamespace(returncode=0), None) is actions
    failure = callback(SimpleNamespace(returncode=1), None)
    from launch.actions import EmitEvent
    assert any(isinstance(action, EmitEvent) for action in failure)
    assert all(action not in failure for action in actions)


def test_scene_transport_is_isolated_even_with_an_inherited_partition(tmp_path, monkeypatch):
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros_logs'))
    monkeypatch.setenv('IGN_PARTITION', 'old_project')
    monkeypatch.setenv('GZ_PARTITION', 'old_project')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('avs_partition_test', root / 'launch/sim_launch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environments = []
    real_setenv = module.SetEnvironmentVariable

    def capture(name, value):
        environments.append((name, value))
        return real_setenv(name, value)

    monkeypatch.setattr(module, 'SetEnvironmentVariable', capture)
    partitions = []
    for _ in range(2):
        environments.clear()
        module.generate_launch_description()
        env = dict(environments)
        assert env['IGN_PARTITION'] == env['GZ_PARTITION']
        assert env['IGN_PARTITION'] != 'old_project'
        partitions.append(env['IGN_PARTITION'])
    assert partitions[0] != partitions[1]


def test_discoverable_but_inactive_nav2_is_not_ready():
    from concurrent.futures import Future
    clients = {name: Mock() for name in ['bt_navigator', 'velocity_smoother']}
    future = Future()
    future.set_result(SimpleNamespace(current_state=SimpleNamespace(id=2)))
    mission = SimpleNamespace(lifecycle_clients=clients,
        lifecycle_pending={'bt_navigator': future}, lifecycle_active={'bt_navigator'},
        next_readiness_check=float('inf'), nav_client=Mock(), navigation_map_received=True,
        now_seconds=lambda: 10., odom_stamp=10.)
    assert not MissionNode.navigation_ready(mission)
    assert 'bt_navigator' not in mission.lifecycle_active
    # All components must be active AND odometry fresh.
    mission.lifecycle_active = set(clients)
    assert MissionNode.navigation_ready(mission)
    mission.odom_stamp = 9.
    assert not MissionNode.navigation_ready(mission)


def test_missing_detections_never_report_mission_complete():
    mission = SimpleNamespace(publish_stop=Mock(), push_active_pub=Mock(), release_active_pub=Mock(),
        step_index=0, step_names=['return_start'], retry_count=0,
        detected_hazards={'FIRE'}, detected_tags=set(), fail_mission=Mock(), report=Mock())
    MissionNode.advance_step(mission)
    mission.fail_mission.assert_called_once()
    mission.report.assert_not_called()


def test_release_exception_stays_on_the_original_box_and_expires():
    # Turning left leaves the original box to the right of the chassis.
    guard=SimpleNamespace(release_start=(0.,0.,0.),odom_pose=(0.,0.,.7),
        release_received=10.,release_started=9.,timeout=.35,
        footprint=np.array([[.353,-.12],[.353,.12],[-.21,.12],[-.21,-.12]]))
    original=np.array([[.35,0.],[.05,.4],[.5,.4]])
    import math
    c,s=math.cos(.7),math.sin(.7)
    points=original@np.array([[c,-s],[s,c]])
    kept=SafetyNode.release_points(guard,points,10.,0.)
    assert np.allclose(kept,points[1:])
    assert np.array_equal(SafetyNode.release_points(guard,points,10.5,0.),points)
    assert np.array_equal(SafetyNode.release_points(guard,points,10.,.05),points)
    guard.odom_pose=(.1,0.,.7)
    assert np.array_equal(SafetyNode.release_points(guard,points,10.,0.),points)
