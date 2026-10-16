"""Check the complete rotating footprint against world walls AND saved pixels."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_collision_footprint_contains_physical_pusher_and_wheels():
    nav=yaml.safe_load((ROOT/'config/nav_params.yaml').read_text())
    polygon=np.float32(json.loads(nav['local_costmap']['local_costmap']['ros__parameters']['footprint']))
    model=ET.parse(ROOT/'models/rescue_rover/model.sdf')
    for collision in model.findall(".//link[@name='pusher']/collision"):
        x,y,z,r,p,yaw=map(float,collision.findtext('pose').split())
        w,h,_=map(float,collision.findtext('geometry/box/size').split())
        c,s=math.cos(yaw),math.sin(yaw)
        for dx,dy in [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]:
            point=(x+c*dx-s*dy,y+s*dx+c*dy)
            assert cv2.pointPolygonTest(polygon,point,True) >= -.0001
    assert max(abs(v[1]) for v in polygon) >= .1424


def test_start_has_clearance_for_every_heading():
    nav = yaml.safe_load((ROOT / 'config/nav_params.yaml').read_text())
    pose = nav['amcl']['ros__parameters']['initial_pose']
    footprint = np.array(json.loads(nav['local_costmap']['local_costmap']['ros__parameters']['footprint']))
    # The circumscribed disk includes the chassis, wheels and all pusher tips.
    radius = np.linalg.norm(footprint, axis=1).max() + .035
    origin = np.array([pose['x'], pose['y']])
    world = ET.parse(ROOT / 'worlds/rescue_world.world')
    for model in world.findall('.//world/model'):
        if 'wall' not in model.get('name') and not model.get('name').startswith('core_north'):
            continue
        centre = np.array([float(v) for v in model.findtext('pose').split()[:2]])
        size = np.array([float(v) for v in model.findtext('link/collision/geometry/box/size').split()[:2]])
        distance = np.linalg.norm(np.maximum(np.abs(origin - centre) - size / 2, 0))
        assert distance > radius, model.get('name')

    meta = yaml.safe_load((ROOT / 'maps/rescue_map.yaml').read_text())
    image = cv2.imread(str(ROOT / 'maps' / meta['image']), cv2.IMREAD_GRAYSCALE)
    rows, cols = np.indices(image.shape)
    x = meta['origin'][0] + (cols + .5) * meta['resolution']
    y = meta['origin'][1] + (image.shape[0] - rows - .5) * meta['resolution']
    disk = np.hypot(x - pose['x'], y - pose['y']) <= radius
    assert np.all(image[disk] > 240), 'Start rotation intersects occupied/unknown saved-map cells'

    zone = world.find(".//model[@name='start_zone']/pose")
    assert np.allclose([float(v) for v in zone.text.split()[:2]], origin)
    mission = yaml.safe_load((ROOT / 'config/mission_params.yaml').read_text())['mission_node']['ros__parameters']
    assert np.allclose(mission['waypoints.return_start'][:2], origin)
    first = mission['waypoints.corridor_entry']
    assert first[1] > pose['y'] and math.isclose(first[2], pose['yaw'])
