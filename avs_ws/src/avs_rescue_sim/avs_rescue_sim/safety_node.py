#!/usr/bin/env python3
"""Fail-closed laser guard after Nav2 smoothing and before the simulated wheels."""

import json
import math

import numpy as np
import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformException, TransformListener

from avs_rescue_sim.motion_safety import collision_ahead


class SafetyNode(Node):
    def __init__(self):
        super().__init__('safety_node', automatically_declare_parameters_from_overrides=True)
        self.footprint = np.asarray(json.loads(self.declare_if_missing(
            'footprint', '[[-0.21,-0.12],[0.191,-0.194],[0.29,-0.16],'
            '[0.353,-0.116],[0.353,0.116],[0.29,0.16],[0.191,0.194],[-0.21,0.12]]')))
        self.margin = float(self.declare_if_missing('clearance', 0.035))
        self.timeout = float(self.declare_if_missing('sensor_timeout', 0.35))
        self.max_linear_velocity = float(self.declare_if_missing('max_linear_velocity', 0.12))
        self.max_angular_velocity = float(self.declare_if_missing('max_angular_velocity', 0.4))
        if not all(math.isfinite(limit) and limit > 0. for limit in
                   (self.max_linear_velocity, self.max_angular_velocity)):
            raise ValueError('Speed limits must be finite and positive')
        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        self.scan = None
        self.scan_received = self.command_received = self.odom_received = -math.inf
        self.push_received = -math.inf
        self.push_requested = False
        self.emergency_stop = False
        self.command = Twist()
        self.velocity = (0., 0.)
        self.odom_pose = None
        self.release_start = None
        self.release_received = -math.inf
        self.release_started = -math.inf
        self.last_reason = None
        self.output = self.create_publisher(Twist, '/cmd_vel_safe', 10)
        self.status = self.create_publisher(String, '/safety/status', 10)
        self.create_subscription(Twist, '/cmd_vel', self.command_callback, 10)
        self.create_subscription(LaserScan, '/scan', self.scan_callback, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.odom_callback, qos_profile_sensor_data)
        self.create_subscription(Bool, '/mission/push_active', self.push_callback, 10)
        self.create_subscription(Bool, '/mission/release_active', self.release_callback, 10)
        self.create_subscription(Bool, '/mission/emergency_stop', self.stop_callback,
                                 QoSProfile(depth=20, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(0.05, self.tick)

    def declare_if_missing(self, name, default):
        if not self.has_parameter(name):
            self.declare_parameter(name, default)
        return self.get_parameter(name).value

    def seconds(self):
        return self.get_clock().now().nanoseconds / 1e9

    def command_callback(self, msg):
        self.command, self.command_received = msg, self.seconds()

    def scan_callback(self, msg):
        self.scan, self.scan_received = msg, self.seconds()

    def odom_callback(self, msg):
        self.velocity = (msg.twist.twist.linear.x, msg.twist.twist.angular.z)
        self.odom_received = self.seconds()
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        self.odom_pose = (p.x, p.y, math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)))

    def release_callback(self, msg):
        if msg.data and self.release_start is None:
            self.release_start = self.odom_pose
            self.release_started = self.seconds()
        elif not msg.data:
            self.release_start = None
        self.release_received = self.seconds()

    def release_points(self, points, now, linear):
        if (self.release_start is None or self.odom_pose is None
                or now-self.release_received >= self.timeout
                or now-self.release_started > 12.0 or abs(linear) > .01):
            return points
        x,y,yaw = self.odom_pose
        sx,sy,syaw = self.release_start
        if math.hypot(x-sx,y-sy) > .06:
            return points
        c,s = math.cos(yaw), math.sin(yaw)
        world = points @ np.array([[c,s],[-s,c]]) + [x,y]
        c,s = math.cos(syaw), math.sin(syaw)
        original = (world-[sx,sy]) @ np.array([[c,-s],[s,c]])
        nose = self.footprint[:,0].max()
        # Contact exception stays fixed on the box left at the end of the push;
        # it does not rotate onto a wall as the vehicle turns away.
        box = ((original[:,0] > nose-.08) & (original[:,0] < nose+.36)
               & (np.abs(original[:,1]) < .19))
        return points[~box]

    def push_callback(self, msg):
        self.push_requested, self.push_received = msg.data, self.seconds()

    def stop_callback(self, msg):
        self.emergency_stop = msg.data

    def scan_points(self):
        transform = self.tf.lookup_transform('base_link', self.scan.header.frame_id,
                                            rclpy.time.Time()).transform
        q = transform.rotation
        # The fixed planar scanner's XY rotation and translation in base_link.
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        ranges = np.asarray(self.scan.ranges)
        valid = np.isfinite(ranges) & (ranges >= self.scan.range_min) & (ranges < self.scan.range_max)
        angles = self.scan.angle_min + np.arange(len(ranges)) * self.scan.angle_increment + yaw
        return np.column_stack((ranges[valid] * np.cos(angles[valid]) + transform.translation.x,
                                ranges[valid] * np.sin(angles[valid]) + transform.translation.y))

    def tick(self):
        now = self.seconds()
        output = Twist()
        v, w = self.command.linear.x, self.command.angular.z
        pushing = self.push_requested and 0 <= now - self.push_received < self.timeout
        reason = ''
        if self.emergency_stop:
            reason = 'mission_stopped'
        elif not (0 <= now - self.command_received < self.timeout):
            reason = 'command_timeout'
        elif self.scan is None or not (0 <= now - self.scan_received < self.timeout):
            reason = 'scan_timeout'
        elif not (0 <= now - self.odom_received < self.timeout):
            reason = 'odometry_timeout'
        elif not math.isfinite(v) or not math.isfinite(w):
            reason = 'invalid_command'
        elif not all(math.isfinite(value) for value in self.velocity):
            reason = 'invalid_odometry'
        elif v < -1e-4:
            reason = 'reverse_disabled'
        else:
            try:
                points = self.scan_points()
                if self.release_start is not None:
                    points = self.release_points(points, now, v)
                # Reject a broken/empty scan, but accept valid max-range returns.
                ranges = np.asarray(self.scan.ranges)
                valid = np.isposinf(ranges) | (np.isfinite(ranges) & (ranges > 0))
                if not len(ranges) or not np.any(valid):
                    reason = 'invalid_scan'
                else:
                    # Navigation follows the smoother's configured limits, while
                    # the contact exception retains its original low push speed.
                    linear_limit = min(self.max_linear_velocity, .10) if pushing else self.max_linear_velocity
                    v = min(max(v, 0.), linear_limit)
                    w = min(max(w, -self.max_angular_velocity), self.max_angular_velocity)
                    # Do not clamp measured velocity: existing inertia can be
                    # greater than the current requested or permitted speed.
                    candidates = [(v, w), self.velocity]
                    if any(collision_ahead(points, self.footprint, a, b,
                                           margin=self.margin, pushing=pushing)
                           for a, b in candidates):
                        reason = 'obstacle_in_stopping_envelope'
                    else:
                        output.linear.x, output.angular.z = v, w
            except TransformException:
                reason = 'laser_transform_unavailable'
            except (ValueError, OverflowError):
                reason = 'invalid_sensor_data'
        self.output.publish(output)
        moving_request = abs(v) > 1e-4 or abs(w) > 1e-4
        self.status.publish(String(data=json.dumps({
            'blocked': bool(reason) and moving_request, 'reason': reason, 'pushing': pushing})))
        if reason != self.last_reason:
            self.get_logger().info(f'Command guard: {reason or "clear"}')
            self.last_reason = reason


def main(args=None):
    rclpy.init(args=args)
    node = SafetyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            try:
                node.output.publish(Twist())
            except rclpy._rclpy_pybind11.RCLError:
                # SIGINT can invalidate the context after the ok() check.
                pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
