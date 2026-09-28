#!/usr/bin/env python3
"""Clear verified free rays in the movable-box region of a saved SLAM map.

The source PGM is never changed. Live obstacle layers still mark the box at its
current location. Only configured non-wall cells may be cleared, and each needs
three independent scans through it, stopping before the measured obstacle.
"""
import math
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener, TransformException


class NavigationMapNode(Node):
    def __init__(self):
        super().__init__('navigation_map_node', automatically_declare_parameters_from_overrides=True)
        if not self.has_parameter('movable_region'):
            self.declare_parameter('movable_region', [1.18, .70, 1.72, 1.70])
        if not self.has_parameter('doorway_free_region'):
            self.declare_parameter('doorway_free_region', [1.30, 2.00, 1.42, 2.11])
        self.region = self.get_parameter('movable_region').value
        self.doorway_free_region = self.get_parameter('doorway_free_region').value
        self.map = None
        self.scan = None
        self.last_scan = None
        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub = self.create_publisher(OccupancyGrid, '/navigation_map', retained)
        self.create_subscription(OccupancyGrid, '/map', self.on_map, retained)
        self.create_subscription(LaserScan, '/scan', lambda m: setattr(self, 'scan', m), qos_profile_sensor_data)
        self.create_timer(.2, self.update)

    def on_map(self, msg):
        self.map = msg
        self.cells = np.asarray(msg.data, dtype=np.int16).reshape(msg.info.height, msg.info.width).copy()
        self.hits = np.zeros_like(self.cells, dtype=np.uint8)
        rows,cols = np.indices(self.cells.shape)
        x = msg.info.origin.position.x+(cols+.5)*msg.info.resolution
        y = msg.info.origin.position.y+(rows+.5)*msg.info.resolution
        # A few saved SLAM pixels at x≈1.34, y≈2.02–2.08 are inside the
        # physical doorway opening. They can mark the rover's centre as lethal
        # on the return trip. The second window is confined to that opening;
        # both windows still require three independent measured free rays.
        self.mask = np.zeros_like(self.cells, dtype=bool)
        for a,b,c,d in (self.region, self.doorway_free_region):
            self.mask |= (x>a)&(x<c)&(y>b)&(y<d)
        self.pub.publish(msg)

    def update(self):
        if self.map is None or self.scan is None or self.scan.header.stamp == self.last_scan:
            return
        try:
            tf = self.tf.lookup_transform(self.map.header.frame_id, self.scan.header.frame_id,
                                         rclpy.time.Time.from_msg(self.scan.header.stamp)).transform
        except TransformException:
            return
        self.last_scan = self.scan.header.stamp
        q=tf.rotation
        yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        scan=self.scan;seen=np.zeros_like(self.mask)
        info=self.map.info
        for i,r in enumerate(scan.ranges):
            if not math.isfinite(r) or r<=scan.range_min:
                continue
            distances=np.arange(0., min(r-.08,4.), info.resolution*.5)
            angle=yaw+scan.angle_min+i*scan.angle_increment
            x=tf.translation.x+distances*np.cos(angle)
            y=tf.translation.y+distances*np.sin(angle)
            cols=np.floor((x-info.origin.position.x)/info.resolution).astype(int)
            rows=np.floor((y-info.origin.position.y)/info.resolution).astype(int)
            valid=(cols>=0)&(cols<info.width)&(rows>=0)&(rows<info.height)
            seen[rows[valid],cols[valid]]=True
        self.hits[seen & self.mask]=np.minimum(3,self.hits[seen & self.mask]+1)
        clear=(self.hits>=3)&self.mask&(self.cells!=0)
        if np.any(clear):
            self.cells[clear]=0
            self.map.data=self.cells.ravel().tolist()
            self.map.header.stamp=self.get_clock().now().to_msg()
            self.pub.publish(self.map)
            self.get_logger().info(f'Cleared {np.count_nonzero(clear)} laser-confirmed movable-obstacle cells')


def main():
    rclpy.init();node=NavigationMapNode()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
