import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('avs_rescue_sim')
    launch_dir = os.path.join(pkg_share, 'launch')
    gui = LaunchConfiguration('gui')
    rviz = LaunchConfiguration('rviz')
    simulation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'sim_launch.py')),
        launch_arguments={'gui': gui, 'rviz': 'false', 'navigation': 'false', 'mission': 'false'}.items(),
    )
    slam = TimerAction(period=3.0, actions=[Node(
        package='slam_toolbox', executable='async_slam_toolbox_node', name='slam_toolbox',
        output='screen', parameters=[os.path.join(pkg_share, 'config', 'slam.yaml')],
    )])
    rviz_node = TimerAction(period=4.0, actions=[Node(
        package='rviz2', executable='rviz2', output='screen', condition=IfCondition(rviz),
        arguments=['-d', os.path.join(pkg_share, 'rviz', 'rescue.rviz')],
        parameters=[{'use_sim_time': True}],
    )])
    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        simulation, slam, rviz_node,
    ])
