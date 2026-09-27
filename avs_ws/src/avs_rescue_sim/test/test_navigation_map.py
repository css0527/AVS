from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Transform
from avs_rescue_sim.navigation_map_node import NavigationMapNode


def test_free_rays_clear_only_the_movable_region_after_three_scans():
    msg=OccupancyGrid();msg.header.frame_id='map';msg.info.width=40;msg.info.height=10
    msg.info.resolution=.1;msg.data=[100]*400
    scan=LaserScan();scan.header.frame_id='laser';scan.range_min=.05;scan.ranges=[2.0]
    transform=Transform();transform.translation.y=.55;transform.rotation.w=1.
    clock=Mock();clock.now().to_msg.return_value=msg.header.stamp
    state=SimpleNamespace(region=[.5,.4,2.5,.7],pub=Mock(),scan=scan,last_scan=None,
                          tf=Mock(),get_clock=lambda:clock,get_logger=lambda:Mock())
    state.tf.lookup_transform.return_value=SimpleNamespace(transform=transform)
    NavigationMapNode.on_map(state,msg)
    for stamp in [1,2]:
        scan.header.stamp.sec=stamp
        NavigationMapNode.update(state)
        # rclpy messages are immutable in normal subscription delivery; emulate.
        from copy import deepcopy
        state.last_scan=deepcopy(scan.header.stamp)
        assert np.all(state.cells==100)
    scan.header.stamp.sec=3
    NavigationMapNode.update(state)
    assert state.cells[5,10]==0     # observed free, eligible region
    assert state.cells[5,3]==100    # structural cells outside region retained
    assert state.cells[5,20]==100   # measured obstacle endpoint retained
    assert state.cells[5,23]==100   # unseen behind obstacle retained
    assert state.cells[2,10]==100   # never observed ray retained
