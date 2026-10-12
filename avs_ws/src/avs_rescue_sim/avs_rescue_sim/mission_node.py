#!/usr/bin/env python3
"""YAML-driven autonomous mission state machine for the rescue task."""

import json
import time
import math
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry, OccupancyGrid
from lifecycle_msgs.srv import GetState
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from std_msgs.msg import Bool, String
from visualization_msgs.msg import Marker
from tf2_ros import Buffer, TransformException, TransformListener

from avs_rescue_sim.motion_safety import angle_difference, push_progress


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
        self.startup_timeout = float(self._param('startup_timeout', 90.0))
        self.observation_timeout = float(self._param('observation_timeout', 5.0))
        self.push_speed = float(self._param('push_speed', 0.10))
        self.push_distance = float(self._param('push_distance', 0.78))
        self.push_timeout = float(self._param('push_timeout', 8.0))
        self.push_settle_time = float(self._param('push_settle_time', 1.0))
        self.release_timeout = float(self._param('release_timeout', 12.0))
        self.release_max_travel = float(self._param('release_max_travel', 0.06))
        self.push_max_lateral_error = float(self._param('push_max_lateral_error', 0.04))
        self.push_max_heading_error = float(self._param('push_max_heading_error', 0.12))
        self.max_outbound_rotation = float(self._param('max_outbound_rotation', 2.2))
        self.max_rotation_travel = float(self._param('max_rotation_travel', 3.6))
        self.max_nav_retries = int(self._param('max_nav_retries', 1))
        self.abort_on_nav_failure = bool(self._param('abort_on_nav_failure', True))
        self.navigation_timeout = float(self._param('navigation_timeout', 35.0))
        if not 0 < self.push_speed <= 0.10 or not 0 < self.push_distance <= 1.10:
            raise ValueError('Rescue doorway push requires speed <= 0.10 m/s and distance <= 1.10 m')
        if self.push_timeout <= 0 or self.push_timeout > 30:
            raise ValueError('Push timeout must be in (0, 30] seconds')
        behavior_tree = self._param(
            'navigation_behavior_tree', 'navigate_to_pose_no_recovery.xml')
        behavior_directory = Path(get_package_share_directory('avs_rescue_sim')) / 'behavior_trees'
        self.navigation_behavior_tree = str(
            behavior_directory / behavior_tree)
        self.precision_navigation_steps = set(self._param('precision_navigation_steps', []))
        self.precision_navigation_behavior_tree = str(behavior_directory / self._param(
            'precision_navigation_behavior_tree', 'navigate_to_pose_precision.xml'))
        self.precision_rotation_behavior_tree = str(behavior_directory / self._param(
            'precision_rotation_behavior_tree', 'turn_at_current_pose_precision.xml'))

        if not (len(self.step_names) == len(self.step_types) == len(self.step_expected)):
            raise ValueError('step_names, step_types and step_expected must have equal lengths')
        self.poses = {}
        for name in self.step_names:
            pose = list(self._param(f'waypoints.{name}', []))
            if len(pose) != 3:
                raise ValueError(f'waypoints.{name} must be [x, y, yaw]')
            self.poses[name] = tuple(float(value) for value in pose)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.lifecycle_clients = {
            name: self.create_client(GetState, f'/{name}/get_state')
            for name in ('amcl', 'controller_server', 'planner_server',
                         'bt_navigator', 'velocity_smoother')}
        self.lifecycle_pending = {}
        self.lifecycle_active = set()
        self.next_readiness_check = 0.0
        self.startup_wall_time = time.monotonic()
        self.navigation_map_received = False
        self.create_subscription(OccupancyGrid, '/navigation_map',
                                 lambda msg: setattr(self, 'navigation_map_received', bool(msg.data)),
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.cmd_pub = self.create_publisher(Twist, self.cmd_topic, 10)
        self.push_active_pub = self.create_publisher(Bool, '/mission/push_active', 10)
        self.release_active_pub = self.create_publisher(Bool, '/mission/release_active', 10)
        retained_qos = QoSProfile(depth=20, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.stop_pub = self.create_publisher(Bool, '/mission/emergency_stop', retained_qos)
        self.stop_pub.publish(Bool(data=False))
        self.status_pub = self.create_publisher(String, '/mission/status', retained_qos)
        self.path_pub = self.create_publisher(Marker, '/mission/planned_route', 10)
        self.create_subscription(Odometry, '/odom', self.odom_callback, qos_profile_sensor_data)
        self.create_subscription(String, '/hazards/detections', self.detection_callback, retained_qos)
        self.create_subscription(String, '/safety/status', self.safety_callback, 10)

        self.detected_hazards = set()
        self.detected_tags = set()
        self.odom_xy = None
        self.odom_pose = None
        self.odom_stamp = -math.inf
        self.odom_speed = (0.0, 0.0)
        self.nav_rotation = 0.0
        self.nav_heading_change = 0.0
        self.safety_blocked_since = None
        self.step_index = -1
        self.state = 'startup'
        self.state_started = self.get_clock().now()
        self.deadline = None
        self.push_start_pose = None
        self.retry_count = 0
        self.goal_handle = None
        self.mission_failed = False
        self.timer = self.create_timer(0.05, self.tick)
        self.route_timer = self.create_timer(1.0, self.publish_route)
        self.report('startup', f'waiting at least {self.startup_delay:.1f}s and for all Nav2 lifecycle nodes to activate')

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
        message = f'[MISSION] {state}: {detail}'
        # rclpy binds one severity to each logging call site.  Using getattr()
        # here crashes when a later timeout is logged at warning severity.
        if level == 'warning':
            self.get_logger().warning(message)
        elif level == 'error':
            self.get_logger().error(message)
        else:
            self.get_logger().info(message)

    def odom_callback(self, msg):
        q = msg.pose.pose.orientation
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        if self.odom_pose is not None and self.state == 'navigating':
            change = angle_difference(yaw, self.odom_pose[2])
            self.nav_rotation += abs(change)
            self.nav_heading_change += change
        self.odom_xy = (msg.pose.pose.position.x, msg.pose.pose.position.y)
        self.odom_pose = (*self.odom_xy, yaw)
        self.odom_stamp = self.now_seconds()
        self.odom_speed = (msg.twist.twist.linear.x, msg.twist.twist.angular.z)

    def safety_callback(self, msg):
        try:
            blocked = json.loads(msg.data).get('blocked', False)
        except (json.JSONDecodeError, AttributeError):
            return
        if blocked and self.safety_blocked_since is None:
            self.safety_blocked_since = self.now_seconds()
        elif not blocked:
            self.safety_blocked_since = None

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
        if self.state == 'navigating' and self.step_types[self.step_index] == 'release':
            # Nav2 turns away from the box while the laser guard still rejects
            # side/rear contact. Permission expires unless renewed each tick.
            self.release_active_pub.publish(Bool(data=True))
            if math.dist(self.odom_pose[:2], self.release_start_pose[:2]) > self.release_max_travel:
                self.fail_mission('pusher release exceeded its bounded travel')
                return
        if self.state in ('navigating', 'pushing') and self.safety_blocked_since is not None:
            if self.now_seconds() - self.safety_blocked_since >= 1.0:
                self.fail_mission('laser command guard blocked motion; no spin/back-up recovery')
                return
        if self.state == 'startup':
            # An action server is discoverable before its lifecycle is active.
            # Also, simulation time starts at zero then jumps on the first clock.
            # Neither server_is_ready() nor a sim-time delay alone is sufficient.
            waiting = time.monotonic() - self.startup_wall_time
            if waiting > self.startup_timeout:
                self.fail_mission('Nav2 lifecycle activation timed out')
                return
            if waiting < self.startup_delay:
                return
            if not self.navigation_ready():
                return
            self.advance_step()
        elif self.state == 'settling':
            self.publish_stop()
            stopped = (self.now_seconds() - self.odom_stamp < 0.35 and
                       abs(self.odom_speed[0]) < 0.015 and abs(self.odom_speed[1]) < 0.04)
            if self.elapsed() >= 0.8 and stopped:
                expected = self.step_expected[self.step_index]
                if expected:
                    self.deadline = self.now_seconds() + self.observation_timeout
                    self.report('observing', f'camera scanning left/right for {expected}; base stopped')
                else:
                    self.advance_step()
            elif self.elapsed() >= 4.0:
                self.fail_mission('vehicle did not settle after navigation')
        elif self.state == 'observing':
            self.publish_stop()
            expected = self.step_expected[self.step_index]
            step_type = self.step_types[self.step_index]
            found = expected in (self.detected_tags if step_type in ('core', 'observe_core') else self.detected_hazards)
            if found and self.elapsed() >= 1.0:
                self.report('observation_complete', f'confirmed {expected}')
                self.advance_step()
            elif self.now_seconds() >= self.deadline:
                self.fail_mission(f'{expected} not confirmed after camera scan')
        elif self.state == 'pushing':
            self.update_push()
        elif self.state == 'push_settling':
            self.publish_stop()
            if self.elapsed() >= self.push_settle_time:
                self.advance_step()
        elif self.state == 'navigating':
            name = self.step_names[self.step_index]
            if self.now_seconds() >= self.deadline:
                self.fail_mission(f'{name}: navigation exceeded {self.navigation_timeout:.1f}s')
            elif self.step_types[self.step_index] not in ('return', 'return_rotate') and (
                    abs(self.nav_heading_change) > self.max_outbound_rotation
                    or self.nav_rotation > self.max_rotation_travel):
                self.fail_mission(f'{name}: unexpected turn; stop instead of circling')

    def navigation_ready(self):
        for name, future in list(self.lifecycle_pending.items()):
            if future.done():
                result = future.result()
                if result is not None and result.current_state.id == 3:
                    self.lifecycle_active.add(name)
                else:
                    self.lifecycle_active.discard(name)
                del self.lifecycle_pending[name]
        if time.monotonic() >= self.next_readiness_check:
            self.next_readiness_check = time.monotonic() + 0.5
            for name, client in self.lifecycle_clients.items():
                if name not in self.lifecycle_pending and client.service_is_ready():
                    self.lifecycle_pending[name] = client.call_async(GetState.Request())
        return (self.navigation_map_received
                and len(self.lifecycle_active) == len(self.lifecycle_clients)
                and self.nav_client.server_is_ready()
                and self.now_seconds() - self.odom_stamp < 0.35)

    def advance_step(self):
        self.publish_stop()
        self.push_active_pub.publish(Bool(data=False))
        self.release_active_pub.publish(Bool(data=False))
        self.step_index += 1
        self.retry_count = 0
        if self.step_index >= len(self.step_names):
            missing_hazards = sorted(set(['FIRE', 'CHEMICAL', 'RADIATION', 'ELECTRICAL', 'BIOHAZARD']) - self.detected_hazards)
            missing_tags = sorted(set(['0', '1', '2', '3']) - self.detected_tags)
            if missing_hazards or missing_tags:
                self.fail_mission(f'incomplete observations: {missing_hazards + missing_tags}')
                return
            detail = (f'finished and returned; corridor={len(self.detected_hazards)}/5, '
                      f'core={len(self.detected_tags)}/4, missing={missing_hazards + missing_tags}')
            self.report('complete', detail)
            self.stop_pub.publish(Bool(data=True))
            self.timer.cancel()
            return
        step_type = self.step_types[self.step_index]
        name = self.step_names[self.step_index]
        if step_type == 'push':
            self.begin_push()
        elif step_type in ('observe', 'observe_core'):
            self.report('settling', f'{name}: observe at current stop')
        else:
            self.send_navigation_goal(name)

    def send_navigation_goal(self, name, align=False):
        if not align:
            self.nav_rotation = 0.0
            self.nav_heading_change = 0.0
        self.nav_phase = 'align' if align else 'travel'
        x, y, yaw = self.poses[name]
        if align or self.step_types[self.step_index] in ('turn', 'release', 'return_rotate'):
            # A second goal at the previous coordinates can lie centimetres
            # behind the stopped rover after AMCL updates. Turn via Nav2 at the
            # current map pose rather than planning a tiny U-turn to that point.
            try:
                pose = self.tf_buffer.lookup_transform(
                    self.map_frame, 'base_link', rclpy.time.Time()).transform.translation
                x, y = pose.x, pose.y
            except TransformException:
                self.fail_mission('current map pose unavailable for doorway turn')
                return
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.map_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        precision = name in self.precision_navigation_steps
        rotating = align or self.step_types[self.step_index] in ('turn', 'return_rotate')
        if rotating:
            goal.behavior_tree = (self.precision_rotation_behavior_tree if precision else
                                  str(Path(self.navigation_behavior_tree).with_name('turn_at_current_pose.xml')))
        else:
            goal.behavior_tree = (self.precision_navigation_behavior_tree if precision else
                                  str(Path(self.navigation_behavior_tree).with_name('approach_pose.xml')))
        releasing = self.step_types[self.step_index] == 'release'
        if releasing:
            self.release_start_pose = self.odom_pose
            goal.behavior_tree = str(Path(self.navigation_behavior_tree).with_name('release_pusher.xml'))
        phase = 'align at current pose' if align else 'approach'
        self.report('navigating', f'{name} {phase} -> ({x:.2f}, {y:.2f}, yaw={yaw:.2f})')
        self.deadline = self.now_seconds() + (self.release_timeout if releasing else self.navigation_timeout)
        future = self.nav_client.send_goal_async(goal)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        try:
            self.goal_handle = future.result()
        except Exception as exc:
            self.navigation_failed(f'action request failed: {exc}')
            return
        if self.mission_failed:
            if self.goal_handle.accepted:
                self.goal_handle.cancel_goal_async()
            return
        if not self.goal_handle.accepted:
            self.navigation_failed('goal rejected')
            return
        result_future = self.goal_handle.get_result_async()
        result_future.add_done_callback(self.navigation_result_callback)

    def navigation_result_callback(self, future):
        if self.mission_failed:
            return
        try:
            wrapped = future.result()
        except Exception as exc:
            self.navigation_failed(f'action result failed: {exc}')
            return
        if wrapped.status != GoalStatus.STATUS_SUCCEEDED:
            self.navigation_failed(f'Nav2 status={wrapped.status}')
            return
        self.goal_handle = None
        self.publish_stop()
        if self.nav_phase == 'travel' and self.step_types[self.step_index] not in ('turn', 'release', 'return_rotate'):
            self.send_navigation_goal(self.step_names[self.step_index], align=True)
            return
        self.report('settling', f'{self.step_names[self.step_index]} reached; braking before next action')

    def navigation_failed(self, reason):
        if self.retry_count < self.max_nav_retries:
            self.retry_count += 1
            name = self.step_names[self.step_index]
            self.report('navigation_retry', f'{name}: {reason}; retry {self.retry_count}', 'warning')
            self.send_navigation_goal(name)
        else:
            name = self.step_names[self.step_index]
            if self.abort_on_nav_failure:
                self.fail_mission(f'{name}: {reason}')
            else:
                self.report('navigation_skipped', f'{name}: {reason}', 'error')
                self.advance_step()

    def fail_mission(self, reason):
        if self.mission_failed:
            return
        self.mission_failed = True
        self.stop_pub.publish(Bool(data=True))
        self.push_active_pub.publish(Bool(data=False))
        self.release_active_pub.publish(Bool(data=False))
        if self.goal_handle is not None:
            self.goal_handle.cancel_goal_async()
        self.publish_stop()
        self.report('failed', f'{reason}; vehicle stopped', 'error')
        self.timer.cancel()

    def begin_push(self):
        if self.odom_pose is None or self.now_seconds() - self.odom_stamp > 0.35:
            self.fail_mission('cannot push without fresh odometry')
            return
        self.push_start_pose = self.odom_pose
        self.report('pushing', f'closed-loop push for {self.push_distance:.2f}m at {self.push_speed:.2f}m/s')

    def update_push(self):
        if self.odom_pose is None or self.now_seconds() - self.odom_stamp > 0.35:
            self.fail_mission('odometry lost during push')
            return
        distance, lateral, heading = push_progress(self.push_start_pose, self.odom_pose)
        if abs(lateral) > self.push_max_lateral_error or abs(heading) > self.push_max_heading_error:
            self.fail_mission('push deviated from doorway centreline')
            return
        if distance >= self.push_distance:
            self.push_active_pub.publish(Bool(data=False))
            self.publish_stop()
            self.report('push_settling', f'barrier clearing completed after {distance:.2f}m')
            return
        if self.elapsed() >= self.push_timeout:
            self.fail_mission(f'push timeout after {distance:.2f}m; doorway not confirmed clear')
            return
        self.push_active_pub.publish(Bool(data=True))
        command = Twist()
        command.linear.x = min(self.push_speed, max(0.02, (self.push_distance - distance) * 0.6))
        command.angular.z = max(-0.10, min(0.10, -1.2 * heading - 0.8 * lateral))
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
        # SIGINT may already have invalidated the ROS context.  Publishing in
        # that state raises RCLError and turns a clean Ctrl-C into a node crash.
        if rclpy.ok():
            node.publish_stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
