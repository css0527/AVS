import os
from pathlib import Path
import uuid
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, EmitEvent, ExecuteProcess,
                            IncludeLaunchDescription, LogInfo, OpaqueFunction, RegisterEventHandler,
                            SetEnvironmentVariable, TimerAction)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit, OnProcessStart
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


def after_success(actions, reason):
    def on_exit(event, context):
        if event.returncode != 0:
            return [LogInfo(msg=reason), EmitEvent(event=Shutdown(reason=reason))]
        return actions
    return on_exit


def generate_launch_description():
    pkg_share = get_package_share_directory('avs_rescue_sim')
    nav2_share = get_package_share_directory('nav2_bringup')
    world = str(Path(pkg_share, 'worlds', 'rescue_world.world').resolve())
    model = str(Path(pkg_share, 'models', 'rescue_rover', 'model.sdf').resolve())
    models = os.path.join(pkg_share, 'models')
    map_yaml = str(Path(pkg_share, 'maps', 'rescue_map.yaml').resolve())
    map_image = str((Path(map_yaml).parent / yaml.safe_load(
        Path(map_yaml).read_text())['image']).resolve())
    if not Path(map_image).is_file():
        raise FileNotFoundError(f'AVS navigation map image missing: {map_image}')
    nav_params = os.path.join(pkg_share, 'config', 'nav_params.yaml')
    config = yaml.safe_load(Path(nav_params).read_text())
    footprint = config['local_costmap']['local_costmap']['ros__parameters']['footprint']
    # Gazebo and AMCL must start at the SAME pose. Keep one source of truth.
    initial_pose = config['amcl']['ros__parameters']['initial_pose']
    # Humble activates BOTH navigators, even for single-pose goals. Leaving
    # through-poses at its default requires Spin/BackUp and aborts all bringup.
    nav_params = RewrittenYaml(
        source_file=nav_params, root_key='', convert_types=True,
        param_rewrites={key: os.path.join(pkg_share, 'behavior_trees', tree)
                        for key, tree in (
                            ('default_nav_to_pose_bt_xml', 'navigate_to_pose_no_recovery.xml'),
                            ('default_nav_through_poses_bt_xml', 'navigate_through_poses_no_recovery.xml'))})
    robot_description = Path(pkg_share, 'urdf', 'rescue_rover.urdf').read_text()

    gui = LaunchConfiguration('gui')
    rviz = LaunchConfiguration('rviz')
    navigation = LaunchConfiguration('navigation')
    mission = LaunchConfiguration('mission')
    demo = LaunchConfiguration('demo')
    # Gazebo 11 also uses Ignition's unscoped /scene_info service. Master URI
    # isolation alone does NOT prevent another gzserver answering that request.
    # This partition must be set before BOTH gzserver and gzclient start.
    scene_partition = 'avs_rescue_' + uuid.uuid4().hex

    gazebo_server = ExecuteProcess(
        cmd=['gzserver', '--verbose', '-s', 'libgazebo_ros_init.so',
             '-s', 'libgazebo_ros_factory.so', world,
             '--ros-args', '--log-level', 'camera_pan:=warn', '--'],
        output='screen',
    )
    gazebo_client = ExecuteProcess(
        cmd=['gzclient', '--verbose'], output='screen', condition=IfCondition(gui))
    stop_if_gazebo_exits = RegisterEventHandler(
        OnProcessExit(
            target_action=gazebo_server,
            on_exit=[EmitEvent(event=Shutdown(reason='Gazebo server exited'))],
        )
    )
    state_publisher = Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        output='screen',
        parameters=[{'use_sim_time': True, 'robot_description': robot_description}],
    )
    verify_world = ExecuteProcess(
        cmd=['python3', '-m', 'avs_rescue_sim.check_world', world], output='screen')
    spawn = Node(
        package='gazebo_ros', executable='spawn_entity.py', output='screen',
        arguments=['-entity', 'rescue_rover', '-file', model,
                   '-x', str(initial_pose['x']), '-y', str(initial_pose['y']),
                   '-z', '0.03', '-Y', str(initial_pose['yaw'])],
    )
    nav2 = TimerAction(period=3.0, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_share, 'launch', 'bringup_launch.py')),
        condition=IfCondition(navigation),
        launch_arguments={
            'map': map_yaml,
            'params_file': nav_params,
            'use_sim_time': 'true',
            'slam': 'False',
            'autostart': 'true',
            'use_composition': 'False',
        }.items(),
    )])
    vision = TimerAction(period=3.0, actions=[Node(
        package='avs_rescue_sim', executable='vision_node', name='vision_node',
        output='screen',
        parameters=[os.path.join(pkg_share, 'config', 'vision_params.yaml')],
    )])
    scanner = Node(
        package='avs_rescue_sim', executable='camera_scan_node', output='screen',
        parameters=[{'use_sim_time': True}])
    safety = Node(
        package='avs_rescue_sim', executable='safety_node', output='screen',
        parameters=[{'use_sim_time': True, 'footprint': footprint}])
    stop_if_guard_exits = RegisterEventHandler(OnProcessExit(
        target_action=safety,
        on_exit=[EmitEvent(event=Shutdown(reason='Laser command guard exited'))]))
    mission_process = Node(
        package='avs_rescue_sim', executable='mission_node', name='mission_node',
        output='screen', condition=IfCondition(mission),
        parameters=[os.path.join(pkg_share, 'config', 'mission_params.yaml')],
    )
    mission_node = TimerAction(period=4.0, actions=[mission_process])
    stop_if_mission_exits = RegisterEventHandler(OnProcessExit(
        target_action=mission_process,
        on_exit=[EmitEvent(event=Shutdown(reason='Mission process exited'))]))
    rviz_process = Node(
        package='rviz2', executable='rviz2', output='screen',
        condition=IfCondition(rviz),
        arguments=['-d', LaunchConfiguration('rviz_config')],
        parameters=[{'use_sim_time': True}],
    )

    # Keep the recorder's original launch timing when demo:=false. Interactive
    # runs open the native views first, then the camera and event windows.
    # Only these process IDs are passed to the best-effort desktop arranger.
    desktop_pids = {'gazebo_pid': 0, 'rviz_pid': 0}

    def viewer():
        return Node(
            package='avs_rescue_sim', executable='demo_viewer',
            name='demo_viewer', output='screen',
            additional_env={'QT_QPA_PLATFORM': 'xcb'},
            parameters=[{'use_sim_time': True, **desktop_pids}],
        )

    def after_gazebo_start(event, context):
        desktop_pids['gazebo_pid'] = event.pid
        if not IfCondition(demo).evaluate(context):
            return []
        following = rviz_process if IfCondition(rviz).evaluate(context) else viewer()
        return [TimerAction(period=1.0, actions=[following])]

    def after_rviz_start(event, context):
        desktop_pids['rviz_pid'] = event.pid
        if not IfCondition(demo).evaluate(context):
            return []
        return [TimerAction(period=1.0, actions=[viewer()])]

    def start_desktop(context):
        if not LaunchConfiguration('rviz_config').perform(context):
            # The full debugging layout has docks that cannot shrink into a
            # quarter-screen slot. Reuse the compact layout from the recorder.
            filename = 'rescue_demo.rviz' if IfCondition(demo).evaluate(context) else 'rescue.rviz'
            context.launch_configurations['rviz_config'] = os.path.join(pkg_share, 'rviz', filename)
        if not IfCondition(demo).evaluate(context):
            return [TimerAction(period=3.0, actions=[gazebo_client]),
                    TimerAction(period=4.0, actions=[rviz_process])]
        # A condition-skipped process never emits OnProcessStart. Begin with
        # the first enabled view so gui:=false / rviz:=false cannot stall us.
        first = (gazebo_client if IfCondition(gui).evaluate(context) else
                 rviz_process if IfCondition(rviz).evaluate(context) else viewer())
        return [LogInfo(msg='AVS live views: Gazebo -> RViz -> onboard camera -> mission events'),
                TimerAction(period=3.0, actions=[first])]


    navigation_map = Node(
        package='avs_rescue_sim', executable='navigation_map_node', output='screen',
        condition=IfCondition(navigation),
        parameters=[os.path.join(pkg_share, 'config', 'navigation_map.yaml')])
    stop_if_map_exits = RegisterEventHandler(OnProcessExit(
        target_action=navigation_map,
        on_exit=[EmitEvent(event=Shutdown(reason='Navigation map updater exited'))]))

    return LaunchDescription([
        stop_if_mission_exits,
        DeclareLaunchArgument('gui', default_value='true',
                              description='Start Gazebo GUI'),
        DeclareLaunchArgument('rviz', default_value='true',
                              description='Start RViz'),
        DeclareLaunchArgument('demo', default_value=gui,
                              description='Open camera and mission-event windows; defaults to gui'),
        DeclareLaunchArgument('rviz_config', default_value='',
                              description='RViz config override; empty selects compact demo or full debug layout'),
        DeclareLaunchArgument('navigation', default_value='true',
                              description='Start Nav2 localization/navigation'),
        DeclareLaunchArgument('mission', default_value='true',
                              description='Run the autonomous mission'),
        SetEnvironmentVariable('IGN_PARTITION', scene_partition),
        SetEnvironmentVariable('GZ_PARTITION', scene_partition),
        SetEnvironmentVariable(
            'GAZEBO_MODEL_PATH',
            [models, ':', EnvironmentVariable('GAZEBO_MODEL_PATH', default_value='')]),
        # All course assets are local. Avoid blocking GUI initialization on
        # the remote model catalog (which can leave the default camera view).
        SetEnvironmentVariable('GAZEBO_MODEL_DATABASE_URI', Path(models).resolve().as_uri()),
        LogInfo(msg=['AVS Gazebo world: ', world]),
        LogInfo(msg=['AVS navigation map: ', map_yaml]),
        LogInfo(msg=['AVS navigation image: ', map_image]),
        LogInfo(msg=['AVS scene transport partition: ', scene_partition]),
        LogInfo(msg=f'AVS spawn / AMCL initial pose: {initial_pose}'),
        LogInfo(msg=['AVS Gazebo server/client master: ',
                     EnvironmentVariable('GAZEBO_MASTER_URI', default_value='http://localhost:11345')]),
        stop_if_gazebo_exits,
        RegisterEventHandler(OnProcessStart(
            target_action=gazebo_client, on_start=after_gazebo_start)),
        RegisterEventHandler(OnProcessStart(
            target_action=rviz_process, on_start=after_rviz_start)),
        RegisterEventHandler(OnProcessExit(
            target_action=verify_world,
            on_exit=after_success([spawn], 'AVS world verification failed'))),
        RegisterEventHandler(OnProcessExit(
            target_action=spawn,
            on_exit=after_success([OpaqueFunction(function=start_desktop),
                                  nav2, vision, scanner, mission_node],
                                  'AVS rover spawn failed'))),
        gazebo_server,
        verify_world,
        state_publisher,
        stop_if_map_exits,
        navigation_map,
        stop_if_guard_exits,
        safety,
    ])
