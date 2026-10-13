#!/usr/bin/env python3
"""Sweep the camera pan joint; observation never commands the rover's wheels."""

import math

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64


class CameraScanNode(Node):
    def __init__(self):
        super().__init__('camera_scan_node')
        self.declare_parameter('pan_limit', 1.90)
        self.declare_parameter('scan_period', 12.0)
        self.limit = float(self.get_parameter('pan_limit').value)
        self.period = float(self.get_parameter('scan_period').value)
        if not 0 < self.limit <= 1.95 or self.period < 6.0:
            raise ValueError('pan_limit must be in (0, 1.95], scan_period >= 6 s')
        self.publisher = self.create_publisher(Float64, '/camera/pan_target', 1)
        self.started = self.get_clock().now()
        self.create_timer(0.10, self.tick)

    def tick(self):
        elapsed = (self.get_clock().now() - self.started).nanoseconds / 1e9
        angle = self.limit * math.sin(2 * math.pi * elapsed / self.period)
        self.publisher.publish(Float64(data=angle))



def main(args=None):
    rclpy.init(args=args)
    node = CameraScanNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
