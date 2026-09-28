#!/usr/bin/env python3
"""Start an isolated full mission and record independent acceptance evidence."""
import argparse, hashlib, json, math, os, signal, socket, subprocess, time
from pathlib import Path
import cv2, numpy as np
import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import Odometry, OccupancyGrid
from sensor_msgs.msg import Image
from std_msgs.msg import String
from gazebo_msgs.msg import ModelStates
from visualization_msgs.msg import MarkerArray
from tf2_ros import Buffer, TransformListener, TransformException

workspace=Path(__file__).resolve().parents[3]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=workspace/'acceptance'/time.strftime('%Y%m%d_%H%M%S'))
parser.add_argument('--gui',action='store_true')
parser.add_argument('--presentation',action='store_true',help='Use a compact RViz layout for side-by-side recording')
parser.add_argument('--images',action='store_true')
parser.add_argument('--raw-images',action='store_true',help='Save unannotated camera frames with ROS header timestamps at about 5 Hz')
parser.add_argument('--mapping-evidence',action='store_true',help='Record independent online SLAM without changing the navigation map or TF')
args=parser.parse_args()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
print('OUTPUT',out,flush=True)
source=workspace/'src'
manifest={str(path.relative_to(workspace)):hashlib.sha256(path.read_bytes()).hexdigest()
 for path in source.rglob('*') if path.is_file() and '__pycache__' not in path.parts
 and path.suffix not in ('.pyc',)}
(out/'source_sha256.json').write_text(json.dumps(manifest,indent=2))
with socket.socket() as s:
 s.bind(('127.0.0.1',0));port=s.getsockname()[1]
domain=str(80+int(time.time())%100)
os.environ.update(AVS_ROS_DOMAIN_ID=domain,ROS_DOMAIN_ID=domain,AVS_GAZEBO_MASTER_URI=f'http://127.0.0.1:{port}',ROS_LOCALHOST_ONLY='1',ROS_LOG_DIR=str(out/'ros'),GAZEBO_LOG_PATH=str(out/'gazebo'))
for key in ('QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_FONTDIR'):
 if 'cv2' in os.environ.get(key,''):os.environ.pop(key)
log=(out/'launch.log').open('w')
launch_args=[str(workspace/'start.sh'),f'gui:={str(args.gui).lower()}',f'rviz:={str(args.gui).lower()}']
if args.presentation:launch_args.append('rviz_config:='+str(workspace/'src/avs_rescue_sim/rviz/rescue_demo.rviz'))
p=subprocess.Popen(launch_args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
slam_log=None;slam=None
if args.mapping_evidence:
 slam_log=(out/'slam.log').open('w')
 slam=subprocess.Popen(['ros2','run','slam_toolbox','async_slam_toolbox_node','--ros-args',
  '--params-file',str(workspace/'src/avs_rescue_sim/config/slam.yaml'),
  '-p','map_frame:=evaluation_map','-p','transform_publish_period:=0.0',
  '-r','map:=/evaluation/slam_map','-r','map_metadata:=/evaluation/slam_metadata'],
  stdout=slam_log,stderr=subprocess.STDOUT,start_new_session=True)
rclpy.init(); node=Node('full_mission_audit');data={};events=[];poses=[];detections=[];obstacle_detections=[];markers={};last_img=0
last_raw_img=0;raw_images=[]
if args.raw_images:(out/'raw_images').mkdir()
last_preview=0
tf_buffer=Buffer();tf_listener=TransformListener(tf_buffer,node);marker_frames={}
slam_map=None
retained=QoSProfile(depth=20,durability=DurabilityPolicy.TRANSIENT_LOCAL)
def status(m):
 v=json.loads(m.data);data['mission']=v;events.append(dict(wall=time.time(),**v));print('MISSION',v,flush=True)
def odom(m):
 v=m.pose.pose.position;q=m.pose.pose.orientation
 data['odom']=[v.x,v.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))]
def states(m):
 for name,pose in zip(m.name,m.pose):
  if name in ['rescue_rover','push_barrier']:data[name]=[pose.position.x,pose.position.y,pose.position.z,pose.orientation.x,pose.orientation.y,pose.orientation.z,pose.orientation.w]
def image(m):
 global last_img
 now=time.monotonic()
 if not args.images or now-last_img<3:return
 last_img=now
 a=np.frombuffer(m.data,np.uint8).reshape(m.height,m.step)[:,:m.width*3].reshape(m.height,m.width,3)
 if m.encoding=='rgb8':a=cv2.cvtColor(a,cv2.COLOR_RGB2BGR)
 cv2.imwrite(str(out/f'image_{len(poses):04d}.png'),a)
def raw_image(m):
 global last_raw_img
 now=time.monotonic()
 if not args.raw_images or now-last_raw_img<.2:return
 if m.encoding not in ('rgb8','bgr8') or m.step<m.width*3 or len(m.data)!=m.height*m.step:return
 a=np.frombuffer(m.data,np.uint8).reshape(m.height,m.step)[:,:m.width*3].reshape(m.height,m.width,3)
 if m.encoding=='rgb8':a=cv2.cvtColor(a,cv2.COLOR_RGB2BGR)
 filename=f'raw_{len(raw_images):05d}.jpg'
 if not cv2.imwrite(str(out/'raw_images'/filename),a,[cv2.IMWRITE_JPEG_QUALITY,92]):return
 raw_images.append(dict(file=filename,stamp=dict(sec=int(m.header.stamp.sec),nanosec=int(m.header.stamp.nanosec)),
  frame_id=m.header.frame_id,encoding=m.encoding,width=int(m.width),height=int(m.height),step=int(m.step)))
 last_raw_img=now
def camera_preview(m):
 # Show the vision node's processed camera frame, including classifications,
 # AprilTag poses and confirmation status. Never substitute a raw frame.
 # Atomic replacement lets the presentation read a complete frame every time.
 global last_preview
 now=time.monotonic()
 if not args.presentation or now-last_preview<.125:return
 last_preview=now
 if m.encoding not in ('rgb8','bgr8'):return
 a=np.frombuffer(m.data,np.uint8).reshape(m.height,m.step)[:,:m.width*3].reshape(m.height,m.width,3)
 if m.encoding=='rgb8':a=cv2.cvtColor(a,cv2.COLOR_RGB2BGR)
 ok,jpeg=cv2.imencode('.jpg',a,[cv2.IMWRITE_JPEG_QUALITY,85])
 if ok:
  temporary=out/'camera_live.tmp'
  temporary.write_bytes(jpeg.tobytes())
  temporary.replace(out/'camera_live.jpg')
def marker(m):
 try:
  tf=tf_buffer.lookup_transform('map','odom',rclpy.time.Time()).transform
  q=tf.rotation
  registration=[tf.translation.x,tf.translation.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))]
 except TransformException:return
 for v in m.markers:
  if v.ns=='core_hazard':
   markers[v.id]=[v.pose.position.x,v.pose.position.y]
   marker_frames[v.id]=registration
def mapping(m):
 global slam_map
 slam_map=m
node.create_subscription(String,'/mission/status',status,retained)
node.create_subscription(String,'/hazards/detections',lambda m:detections.append(json.loads(m.data)),retained)
node.create_subscription(String,'/obstacles/detections',lambda m:obstacle_detections.append(json.loads(m.data)),10)
node.create_subscription(String,'/safety/status',lambda m:data.update(safety=json.loads(m.data)),10)
node.create_subscription(Odometry,'/odom',odom,qos_profile_sensor_data)
node.create_subscription(ModelStates,'/evaluation/model_states',states,qos_profile_sensor_data)
node.create_subscription(MarkerArray,'/hazards/core_markers',marker,10)
node.create_subscription(Image,'/camera/annotated',image,qos_profile_sensor_data)
if args.raw_images:
 node.create_subscription(Image,'/camera/image_raw',raw_image,qos_profile_sensor_data)
if args.presentation:
 node.create_subscription(Image,'/camera/annotated',camera_preview,qos_profile_sensor_data)
node.create_subscription(OccupancyGrid,'/evaluation/slam_map',mapping,QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
start=time.monotonic();last=0;next_print=10;terminal=None
try:
 while time.monotonic()-start<600:
  rclpy.spin_once(node,timeout_sec=.1)
  t=time.monotonic()-start
  if t-last>.2:
   poses.append(dict(t=t,**data));last=t
  if t>next_print:print('STATE',round(t),data,flush=True);next_print+=10
  if data.get('mission',{}).get('state') in ('complete','failed'):
   terminal=terminal or time.monotonic()
   if time.monotonic()-terminal>3:break
  if p.poll() is not None:raise RuntimeError('launch exited')
  if t>100 and 'mission' not in data:raise RuntimeError('mission node never became ready')
finally:
 if args.raw_images:
  (out/'raw_images'/'manifest.json').write_text(json.dumps(dict(topic='/camera/image_raw',sample_period_s=.2,frames=raw_images),indent=2))
 if slam_map is not None:
  info=slam_map.info;cells=np.asarray(slam_map.data).reshape(info.height,info.width)
  pixels=np.full(cells.shape,205,np.uint8);pixels[(cells>=0)&(cells<=25)]=254;pixels[cells>=65]=0
  cv2.imwrite(str(out/'slam_map.pgm'),np.flipud(pixels))
  q=info.origin.orientation
  map_config=dict(image='slam_map.pgm',mode='trinary',resolution=info.resolution,
   origin=[info.origin.position.x,info.origin.position.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))],
   negate=0,occupied_thresh=.65,free_thresh=.25)
  (out/'slam_map.yaml').write_text(yaml.safe_dump(map_config,sort_keys=False))
  cv2.imwrite(str(out/'slam_map.png'),np.flipud(pixels))
 (out/'result.json').write_text(json.dumps(dict(events=events,poses=poses,detections=detections,obstacle_detections=obstacle_detections,markers=markers,marker_frames=marker_frames,final=data),indent=2))
 node.destroy_node();rclpy.shutdown()
 if p.poll() is None:
  p.send_signal(signal.SIGINT)
  try:p.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=10)
 if slam is not None:
  if slam.poll() is None:
   slam.send_signal(signal.SIGINT)
   try:slam.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(slam.pid,signal.SIGTERM);slam.wait(timeout=10)
  slam_log.close()
 log.close()
print('RESULT',out,data,markers,flush=True)

from evaluate_run import evaluate, render_trace
result=json.loads((out/'result.json').read_text())
report=evaluate(result)
report['barrier_detection_frames']=sum(bool(detection.get('boxes')) for detection in obstacle_detections)
report['passed']=report['passed'] and report['barrier_detection_frames']>0
report['online_slam_recorded']=slam_map is not None
if args.mapping_evidence:report['passed']=report['passed'] and report['online_slam_recorded']
render_trace(result,out/'trajectory.png')
(out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
