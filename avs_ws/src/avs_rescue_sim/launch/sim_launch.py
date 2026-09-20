import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, SetEnvironmentVariable,
                            TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('avs_rescue_sim')
    nav2_share = get_package_share_directory('nav2_bringup')
    world = os.path.join(pkg_share, 'worlds', 'rescue_world.world')
    model = os.path.join(pkg_share, 'models', 'rescue_rover', 'model.sdf')
    models = os.path.join(pkg_share, 'models')
    map_yaml = os.path.join(pkg_share, 'maps', 'rescue_map.yaml')
    nav_params = os.path.join(pkg_share, 'config', 'nav_params.yaml')
    robot_description = Path(pkg_share, 'urdf', 'rescue_rover.urdf').read_text()

    gui = LaunchConfiguration('gui')
    rviz = LaunchConfiguration('rviz')
    navigation = LaunchConfiguration('navigation')
    mission = LaunchConfiguration('mission')

    gazebo_server = ExecuteProcess(
        cmd=['gzserver', '--verbose', '-s', 'libgazebo_ros_init.so',
             '-s', 'libgazebo_ros_factory.so', world],
        output='screen',
    )
    gazebo_client = ExecuteProcess(
        cmd=['gzclient'], output='screen', condition=IfCondition(gui))
    state_publisher = Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        output='screen',
        parameters=[{'use_sim_time': True, 'robot_description': robot_description}],
    )
    spawn = TimerAction(period=2.0, actions=[Node(
        package='gazebo_ros', executable='spawn_entity.py', output='screen',
        arguments=['-entity', 'rescue_rover', '-file', model,
                   '-x', '0.50', '-y', '0.35', '-z', '0.03', '-Y', '1.5708'],
    )])
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
    mission_node = TimerAction(period=4.0, actions=[Node(
        package='avs_rescue_sim', executable='mission_node', name='mission_node',
        output='screen', condition=IfCondition(mission),
        parameters=[os.path.join(pkg_share, 'config', 'mission_params.yaml')],
    )])
    rviz_node = TimerAction(period=4.0, actions=[Node(
        package='rviz2', executable='rviz2', output='screen',
        condition=IfCondition(rviz),
        arguments=['-d', os.path.join(pkg_share, 'rviz', 'rescue.rviz')],
        parameters=[{'use_sim_time': True}],
    )])

    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true',
                              description='Start Gazebo GUI'),
        DeclareLaunchArgument('rviz', default_value='true',
                              description='Start RViz'),
        DeclareLaunchArgument('navigation', default_value='true',
                              description='Start Nav2 localization/navigation'),
        DeclareLaunchArgument('mission', default_value='true',
                              description='Run the autonomous mission'),
        SetEnvironmentVariable(
            'GAZEBO_MODEL_PATH',
            [models, ':', EnvironmentVariable('GAZEBO_MODEL_PATH', default_value='')]),
        gazebo_server,
        gazebo_client,
        state_publisher,
        spawn,
        nav2,
        vision,
        mission_node,
        rviz_node,
    ])
