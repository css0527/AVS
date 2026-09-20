#!/usr/bin/env python3
"""YAML-driven autonomous mission state machine for the rescue task."""

import json
import math

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String
from visualization_msgs.msg import Marker


class MissionNode(Node):
    def __init__(self):
        super().__init__(
            'mission_node',
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )
        self.map_frame = self._param('map_frame', 'map')
        self.cmd_topic = self._param('push_command_topic', '/cmd_vel_nav')
        self.step_names = list(self._param('step_names', []))
        self.step_types = list(self._param('step_types', []))
        self.step_expected = list(self._param('step_expected', []))
        self.startup_delay = float(self._param('startup_delay', 7.0))
        self.observation_timeout = float(self._param('observation_timeout', 5.0))
        self.push_speed = float(self._param('push_speed', 0.22))
        self.push_distance = float(self._param('push_distance', 0.78))
        self.push_timeout = float(self._param('push_timeout', 8.0))
        self.push_settle_time = float(self._param('push_settle_time', 1.0))
        self.max_nav_retries = int(self._param('max_nav_retries', 1))

        if not (len(self.step_names) == len(self.step_types) == len(self.step_expected)):
            raise ValueError('step_names, step_types and step_expected must have equal lengths')
        self.poses = {}
        for name in self.step_names:
            pose = list(self._param(f'waypoints.{name}', []))
            if len(pose) != 3:
                raise ValueError(f'waypoints.{name} must be [x, y, yaw]')
            self.poses[name] = tuple(float(value) for value in pose)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.cmd_pub = self.create_publisher(Twist, self.cmd_topic, 10)
        self.status_pub = self.create_publisher(String, '/mission/status', 10)
        self.path_pub = self.create_publisher(Marker, '/mission/planned_route', 10)
        self.create_subscription(Odometry, '/odom', self.odom_callback, 20)
        self.create_subscription(String, '/hazards/detections', self.detection_callback, 20)

        self.detected_hazards = set()
        self.detected_tags = set()
        self.odom_xy = None
        self.step_index = -1
        self.state = 'startup'
        self.state_started = self.get_clock().now()
        self.deadline = None
        self.push_start_xy = None
        self.retry_count = 0
        self.goal_handle = None
        self.timer = self.create_timer(0.05, self.tick)
        self.route_timer = self.create_timer(1.0, self.publish_route)
        self.report('startup', f'waiting {self.startup_delay:.1f}s for simulator and Nav2')

    def _param(self, name, default):
        parameter = self.get_parameter(name)
        return parameter.value if parameter.type_ != parameter.Type.NOT_SET else default

    def now_seconds(self):
        return self.get_clock().now().nanoseconds / 1e9

    def elapsed(self):
        return (self.get_clock().now() - self.state_started).nanoseconds / 1e9

    def report(self, state, detail, level='info'):
        self.state = state
        self.state_started = self.get_clock().now()
        payload = {
            'state': state,
            'step': self.step_names[self.step_index] if 0 <= self.step_index < len(self.step_names) else '',
            'detail': detail,
            'corridor_detected': len(self.detected_hazards),
            'core_detected': len(self.detected_tags),
        }
        self.status_pub.publish(String(data=json.dumps(payload)))
        getattr(self.get_logger(), level)(f'[MISSION] {state}: {detail}')

    def odom_callback(self, msg):
        self.odom_xy = (msg.pose.pose.position.x, msg.pose.pose.position.y)

    def detection_callback(self, msg):
        try:
            event = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if event.get('kind') == 'corridor_hazard':
            self.detected_hazards.add(str(event.get('label')))
        elif event.get('kind') == 'core_hazard':
            self.detected_tags.add(str(event.get('tag_id')))

    def tick(self):
        if self.state == 'startup':
            if self.elapsed() < self.startup_delay:
                return
            if not self.nav_client.server_is_ready():
                if int(self.elapsed()) % 5 == 0:
                    self.get_logger().info('[MISSION] waiting for navigate_to_pose action server')
                return
            self.advance_step()
        elif self.state == 'observing':
            expected = self.step_expected[self.step_index]
            step_type = self.step_types[self.step_index]
            found = expected in (self.detected_tags if step_type == 'core' else self.detected_hazards)
            if found:
                self.report('observation_complete', f'confirmed {expected}')
                self.advance_step()
            elif self.now_seconds() >= self.deadline:
                self.report('observation_timeout', f'{expected} not confirmed; continuing mission', 'warning')
                self.advance_step()
        elif self.state == 'pushing':
            self.update_push()
        elif self.state == 'push_settling' and self.elapsed() >= self.push_settle_time:
            self.advance_step()

    def advance_step(self):
        self.publish_stop()
        self.step_index += 1
        self.retry_count = 0
        if self.step_index >= len(self.step_names):
            missing_hazards = sorted(set(['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']) - self.detected_hazards)
            missing_tags = sorted(set(['0', '1', '2', '3']) - self.detected_tags)
            detail = (f'finished and returned; corridor={len(self.detected_hazards)}/5, '
                      f'core={len(self.detected_tags)}/4, missing={missing_hazards + missing_tags}')
            self.report('complete', detail)
            self.timer.cancel()
            return
        step_type = self.step_types[self.step_index]
        name = self.step_names[self.step_index]
        if step_type == 'push':
            self.begin_push()
        else:
            self.send_navigation_goal(name)

    def send_navigation_goal(self, name):
        x, y, yaw = self.poses[name]
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.map_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        self.report('navigating', f'{name} -> ({x:.2f}, {y:.2f}, yaw={yaw:.2f})')
        future = self.nav_client.send_goal_async(goal)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        try:
            self.goal_handle = future.result()
        except Exception as exc:
            self.navigation_failed(f'action request failed: {exc}')
            return
        if not self.goal_handle.accepted:
            self.navigation_failed('goal rejected')
            return
        result_future = self.goal_handle.get_result_async()
        result_future.add_done_callback(self.navigation_result_callback)

    def navigation_result_callback(self, future):
        try:
            wrapped = future.result()
        except Exception as exc:
            self.navigation_failed(f'action result failed: {exc}')
            return
        if wrapped.status != GoalStatus.STATUS_SUCCEEDED:
            self.navigation_failed(f'Nav2 status={wrapped.status}')
            return
        expected = self.step_expected[self.step_index]
        if expected:
            self.deadline = self.now_seconds() + self.observation_timeout
            self.report('observing', f'waiting for visual confirmation of {expected}')
        else:
            self.report('navigation_complete', self.step_names[self.step_index])
            self.advance_step()

    def navigation_failed(self, reason):
        if self.retry_count < self.max_nav_retries:
            self.retry_count += 1
            name = self.step_names[self.step_index]
            self.report('navigation_retry', f'{name}: {reason}; retry {self.retry_count}', 'warning')
            self.send_navigation_goal(name)
        else:
            name = self.step_names[self.step_index]
            self.report('navigation_skipped', f'{name}: {reason}', 'error')
            self.advance_step()

    def begin_push(self):
        if self.odom_xy is None:
            self.report('push_waiting', 'waiting for odometry')
            self.create_timer(0.5, self.retry_begin_push)
            return
        self.push_start_xy = self.odom_xy
        self.report('pushing', f'closed-loop push for {self.push_distance:.2f}m at {self.push_speed:.2f}m/s')

    def retry_begin_push(self):
        if self.state == 'push_waiting' and self.odom_xy is not None:
            self.begin_push()

    def update_push(self):
        if self.odom_xy is None or self.push_start_xy is None:
            return
        distance = math.hypot(self.odom_xy[0] - self.push_start_xy[0],
                              self.odom_xy[1] - self.push_start_xy[1])
        if distance >= self.push_distance:
            self.publish_stop()
            self.report('push_settling', f'barrier clearing completed after {distance:.2f}m')
            return
        if self.elapsed() >= self.push_timeout:
            self.publish_stop()
            self.report('push_settling', f'push timeout after {distance:.2f}m', 'warning')
            return
        command = Twist()
        command.linear.x = self.push_speed
        self.cmd_pub.publish(command)

    def publish_stop(self):
        self.cmd_pub.publish(Twist())

    def publish_route(self):
        marker = Marker()
        marker.header.frame_id = self.map_frame
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = 'mission_route'
        marker.id = 0
        marker.type = Marker.LINE_STRIP
        marker.action = Marker.ADD
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.025
        marker.color.r = 0.05
        marker.color.g = 0.85
        marker.color.b = 0.95
        marker.color.a = 0.80
        for name, step_type in zip(self.step_names, self.step_types):
            if step_type == 'push':
                continue
            x, y, _ = self.poses[name]
            point = PoseStamped().pose.position
            point.x, point.y, point.z = x, y, 0.04
            marker.points.append(point)
        self.path_pub.publish(marker)


def main(args=None):
    rclpy.init(args=args)
    node = MissionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.publish_stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
