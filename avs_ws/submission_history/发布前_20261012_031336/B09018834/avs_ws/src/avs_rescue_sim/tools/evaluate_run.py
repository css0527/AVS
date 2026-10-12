#!/usr/bin/env python3
"""Evaluate recorded vehicle trajectories and detection results."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render_trace(result, output):
    canvas = np.full((800, 760, 3), 250, dtype=np.uint8)
    def pixel(point):
        return (int(60 + point[0]*210), int(720 - point[1]*210))
    world = ET.parse(ROOT / 'worlds/rescue_world.world')
    for model in world.findall('./world/model'):
        name = model.get('name')
        x,y = map(float, model.findtext('pose').split()[:2])
        if 'wall' in name or name.startswith('core_north'):
            w,h = map(float, model.findtext('link/collision/geometry/box/size').split()[:2])
            cv2.rectangle(canvas, pixel((x-w/2,y-h/2)), pixel((x+w/2,y+h/2)), (65,65,65), -1)
        if name.startswith('core_tag_'):
            cv2.drawMarker(canvas, pixel((x,y)), (25,25,25), cv2.MARKER_CROSS, 17, 2)
            cv2.putText(canvas, name[-1], pixel((x-.12,y+.05)), cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),1)
    previous = None
    for sample in result['poses']:
        rover=sample.get('rescue_rover')
        if rover is None:continue
        point=pixel(rover)
        step=sample.get('mission',{}).get('step','')
        color=(40,155,50) if 'return' in step or 'exit' in step else (200,105,20)
        if previous is not None:cv2.line(canvas,previous,point,color,2,cv2.LINE_AA)
        previous=point
    for tag,position in result['markers'].items():
        registration=result.get('marker_frames',{}).get(str(tag))
        if registration is not None:
            tx,ty,yaw=registration;c,s=math.cos(yaw),math.sin(yaw)
            position=np.array([[c,s],[-s,c]])@(np.asarray(position)-[tx,ty])
        cv2.circle(canvas,pixel(position),7,(170,40,160),2)
    box=result['final'].get('push_barrier')
    if box:
        cv2.rectangle(canvas,pixel((box[0]-.15,box[1]-.15)),pixel((box[0]+.15,box[1]+.15)),(50,70,210),-1)
    cv2.rectangle(canvas,pixel((1.35,1.75)),pixel((1.65,2.05)),(50,70,210),2)
    cv2.circle(canvas,pixel((.55,.54)),9,(200,100,20),2)
    cv2.putText(canvas,'MEASURED TRAJECTORY / 3 x 3 m', (45,32),cv2.FONT_HERSHEY_SIMPLEX,.7,(35,35,35),2)
    cv2.putText(canvas,'Blue: outbound  Green: return  Purple: estimated tags', (35,765),cv2.FONT_HERSHEY_SIMPLEX,.48,(35,35,35),1)
    cv2.imwrite(str(output),canvas)


def evaluate(result):
    nav = yaml.safe_load((ROOT / 'config/nav_params.yaml').read_text())
    footprint = np.float32(json.loads(nav['local_costmap']['local_costmap']['ros__parameters']['footprint']))
    initial = nav['amcl']['ros__parameters']['initial_pose']
    world = ET.parse(ROOT / 'worlds/rescue_world.world')
    walls, tags = [], {}
    for model in world.findall('./world/model'):
        name = model.get('name')
        xyz = [float(v) for v in model.findtext('pose').split()[:3]]
        if name.startswith('core_tag_'):
            tags[int(name.rsplit('_', 1)[1])] = xyz[:2]
        if 'wall' in name or name.startswith('core_north'):
            x, y = xyz[:2]
            w, h = map(float, model.findtext('link/collision/geometry/box/size').split()[:2])
            walls.append((name, np.float32([[x-w/2,y-h/2],[x+w/2,y-h/2],
                                          [x+w/2,y+h/2],[x-w/2,y+h/2]])))
    overlaps = []
    for sample in result['poses']:
        if 'rescue_rover' not in sample:
            continue
        x,y,z,qx,qy,qz,qw = sample['rescue_rover']
        yaw = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
        c,s = math.cos(yaw), math.sin(yaw)
        polygon = (footprint @ np.float32([[c,s],[-s,c]]) + [x,y]).astype(np.float32)
        for name, wall in walls:
            area, _ = cv2.intersectConvexConvex(polygon, wall)
            if area > 1e-6:
                overlaps.append({'time': sample['t'], 'wall': name, 'area_m2': area})
    final = result['final']
    barrier = final.get('push_barrier', [float('nan')]*2)
    rover = final.get('rescue_rover', [float('nan')]*2)
    raw_errors = {str(i): float(np.linalg.norm(np.asarray(position)-tags[int(i)]))
                  for i,position in result['markers'].items()}
    errors = {}
    for i,position in result['markers'].items():
        registration=result.get('marker_frames',{}).get(str(i))
        if registration is None:
            continue
        tx,ty,yaw=registration
        c,s=math.cos(yaw),math.sin(yaw)
        reference=np.array([[c,-s],[s,c]])@tags[int(i)]+[tx,ty]
        errors[str(i)]=float(np.linalg.norm(np.asarray(position)-reference))
    labels = {d['label'] for d in result['detections'] if d['kind'] == 'corridor_hazard'}
    return_error = math.hypot(rover[0]-initial['x'], rover[1]-initial['y'])
    report = {
        'duration_wall_s': result['poses'][-1]['t'] if result['poses'] else 0.,
        'mission_complete': final.get('mission',{}).get('state') == 'complete',
        'corridor_labels': sorted(labels), 'core_marker_errors_m': errors,
        'raw_world_map_coordinate_difference_m': raw_errors,
        'marker_map_from_odom': result.get('marker_frames',{}),
        'barrier_displacement_m': math.hypot(barrier[0]-1.5, barrier[1]-1.9),
        'return_error_m': return_error, 'wall_overlap_samples': overlaps,
        'note': 'Marker errors compare both positions in map using recorded map<-odom TF. Raw world/map differences include localization offset. Wall overlap uses sampled conservative footprints, not a continuous contact sensor.',
    }
    report['passed'] = (report['mission_complete'] and len(labels)==5 and len(errors)==4
                        and max(errors.values()) < .15 and return_error < .10
                        and report['barrier_displacement_m'] > .50 and not overlaps)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path)
    args=parser.parse_args()
    result=json.loads(args.result.read_text())
    report=evaluate(result)
    render_trace(result,args.result.with_name('trajectory.png'))
    text=json.dumps(report,ensure_ascii=False,indent=2)
    args.result.with_name('evaluation.json').write_text(text)
    print(text)
    raise SystemExit(0 if report['passed'] else 1)
