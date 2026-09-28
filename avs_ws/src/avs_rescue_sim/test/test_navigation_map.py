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
    state=SimpleNamespace(region=[.5,.4,2.5,.7],doorway_free_region=[3.,3.,3.5,3.5],
                          pub=Mock(),scan=scan,last_scan=None,
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


def test_doorway_cleanup_window_is_inside_physical_opening_and_covers_saved_ghost():
    from pathlib import Path
    import cv2
    import yaml
    root=Path(__file__).resolve().parents[1]
    params=yaml.safe_load((root/'config/navigation_map.yaml').read_text())
    a,b,c,d=params['navigation_map_node']['ros__parameters']['doorway_free_region']
    # World north-wall segments end at x=1.25 and begin at x=1.75; the
    # doorway is y=1.85..1.95. This strictly interior map window cannot
    # remove either real wall, even when AMCL/map alignment drifts.
    assert 1.25<a<c<1.75 and b>1.95 and d<2.15
    image=cv2.imread(str(root/'maps/rescue_map.pgm'),cv2.IMREAD_GRAYSCALE)
    assert image is not None
    origin=(-.104,-.0121); resolution=.02
    x,y=1.34,2.06
    col=int((x-origin[0])/resolution)
    row=image.shape[0]-1-int((y-origin[1])/resolution)
    assert a<x<c and b<y<d and image[row,col]<90
