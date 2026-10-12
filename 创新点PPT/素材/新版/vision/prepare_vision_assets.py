from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json, shutil, hashlib, math
ROOT=Path('/home/c/AVS')
OUT=ROOT/'创新点PPT/素材/新版/vision'
RUN=ROOT/'avs_ws/acceptance/speed_mixed_020_20261012_run2'
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
RESAMPLE=getattr(Image,'Resampling',Image).LANCZOS
BG='#101B2C'; WHITE='#F4F7FC'; TEAL='#42D5BB'; MUTED='#A6B7CE'
manifest={'review_scope':{'annotated_acceptance_images':696,'batches':8,'method':'全部 annotated image_*.png 分批缩略图检查；入选单图原分辨率核对；不重画或添加检测框。raw图片由主审另行全盘盘点。'},'assets':[], 'old_ppt_errors':[
 {'source':'recording_yolov5_smac_v19/evidence/image_0113.png','issue':'有 FIRE 图案，无绿色分类框，不可标作 FIRE 检测结果。'},
 {'source':'recording_yolov5_smac_v19/evidence/image_0588.png','issue':'BIOHAZARD 被画面左边截断、无分类框，不可标作完整检测结果。'},
 {'source':'recording_yolov5_smac_v19/evidence/image_0416.png','issue':'蓝色起点及墙面图案真实；FIRE 有 0.95 分类框。'},
 {'source':'recording_yolov5_smac_v19/evidence/image_0573.png','issue':'黄色物体是核心房间地面，非黄色车身；红箱紫色 PUSH BARRIER 框属于专用障碍检测器。'},
 {'source':'recording_yolov5_smac_v19/evidence/image_1607.png','issue':'画面有 CHEMICAL、FIRE、蓝色起点，无红箱。'},
 {'source':'01 扫描页 image_0207 / image_0447 / image_0528','issue':'不是同一停车点连续观察，首图同时有 ELECTRICAL 和 BIOHAZARD；不能作为同目标多帧确认序列。'}]}
def f(n):return ImageFont.truetype(FONT,n)
def add(dest,sources,meaning,transformation='原图完整复制',**extra):
 manifest['assets'].append(dict(file=str(dest.relative_to(ROOT)),sources=[str(p.relative_to(ROOT)) for p in sources],meaning=meaning,transformation=transformation,visual_review='已原分辨率查看所含原图；保留原识别结果，无新画检测框。',**extra))
def copy(src,destname,meaning,**extra):
 dest=OUT/destname;shutil.copyfile(src,dest);add(dest,[src],meaning,source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),**extra);return dest
items=[('0092','fire','FIRE｜火灾类别'),('0077','chemical','CHEMICAL｜化学危险'),('0213','radiation','RADIATION｜辐射危险'),('0335','electrical','ELECTRICAL｜电气危险'),('0320','biohazard','BIOHAZARD｜生物危险')]
for n,name,label in items:copy(RUN/f'image_{n}.png',f'{name}.png',label+'，当前帧有真实绿色分类框；截图是单帧样例，并非准确率统计。')
canvas=Image.new('RGB',(1920,1080),BG);d=ImageDraw.Draw(canvas)
positions=[(20,12),(660,12),(1300,12),(340,535),(980,535)]
for (n,name,label),(x,y) in zip(items,positions):
 d.text((x,y),label,font=f(27),fill=TEAL)
 im=Image.open(RUN/f'image_{n}.png').convert('RGB').resize((600,450),RESAMPLE);canvas.paste(im,(x,y+42))
 d.text((x,y+492),f'run2 / image_{n}.png',font=f(18),fill=MUTED)
d.text((24,1051),'同一次成功运行的五类样例；保留真实检测框。不同时间/视角的拼图，不表示连续识别序列。',font=f(20),fill=MUTED)
canvas.save(OUT/'hazards_five_verified.png');add(OUT/'hazards_five_verified.png',[RUN/f'image_{n}.png' for n,_,_ in items],'五类清晰分类框拼图','五张完整原图等比例缩小拼接；新增中文类名与来源编号。')
# 固定停车点：两张稀疏验收采样，不能当作连续处理帧。
j=json.load(open(RUN/'result.json'));pa=j['poses'][379];pb=j['poses'][394]
dist=math.dist(pa['odom'][:2],pb['odom'][:2]);yaw=abs(pa['odom'][2]-pb['odom'][2])
scan_sources=[RUN/'image_0380.png',RUN/'image_0395.png']
for src,dest,label in zip(scan_sources,['scan_stop_A.png','scan_stop_B.png'],['同一停车点视角 A：BIOHAZARD，停车稳定阶段。图案靠近图像边缘，有真实分类框。','同一停车点视角 B：ELECTRICAL 与 BIOHAZARD，BIOHAZARD 停车观察阶段；非连续确认帧。']):copy(src,dest,label)
c=Image.new('RGB',(1440,680),BG);d=ImageDraw.Draw(c)
for i,(src,label) in enumerate(zip(scan_sources,['视角 A：生物危险牌','视角 B：电气牌与生物危险牌'])):
 x=32+i*704;d.text((x,15),label,font=f(29),fill=TEAL);c.paste(Image.open(src).convert('RGB'),(x,66));d.text((x,557),f'run2 / {src.name}',font=f(22),fill=MUTED)
d.text((32,606),f'同一停车点，相隔约 {pb["t"]-pa["t"]:.1f} s；里程计位移约 {dist*1000:.1f} mm。',font=f(24),fill=WHITE)
d.text((32,642),'画面用于展示云台视角变化；不将两张稀疏采样标成连续 3 帧确认。',font=f(22),fill=MUTED)
c.save(OUT/'scan_stop_pair.png');add(OUT/'scan_stop_pair.png',scan_sources,'同一走廊停车点，云台视角发生变化','两张完整原图拼接；新增中文说明及来源。',pose_evidence={'record':str((RUN/'result.json').relative_to(ROOT)),'image_filename_rule':'image_NNNN.png 由当前 poses 长度命名，最近记录为 poses[NNNN-1]。','pose_A':pa,'pose_B':pb,'odom_translation_m':dist,'odom_yaw_change_rad':yaw,'limitation':'时间为验收接收采样时间；有约 3 mm 自然漂移、约 1.6° 偏航变化。两张图展示不同图案，未声称同目标连续确认。'})
# 原始红牌扫视：补充可视化，无识别框，不添加任何结果。
raw_manifest=json.load(open(RUN/'raw_images/manifest.json'))['frames'];rawnums=[6,16,18]
c=Image.new('RGB',(1920,660),BG);d=ImageDraw.Draw(c)
for i,n in enumerate(rawnums):
 m=raw_manifest[n];src=RUN/'raw_images'/m['file'];dest=copy(src,f'scan_fire_raw_{i+1}.jpg','启动点附近，同一 FIRE 标识在云台扫视中的原始相机画面；无识别框，不作为连续确认结果。',header_stamp=m['stamp']);x=20+i*640
 im=Image.open(src).convert('RGB').resize((620,465),RESAMPLE);c.paste(im,(x,46));d.text((x,5),f'同一红牌｜视角 {i+1}',font=f(28),fill=TEAL);stamp=m['stamp']['sec']+m['stamp']['nanosec']/1e9;d.text((x,522),f"{m['file']} / ROS {stamp:.3f} s",font=f(21),fill=MUTED)
d.text((24,582),'启动阶段同一红色标识的原始扫视画面；仅展示视角变化，未添加检测框。',font=f(26),fill=WHITE)
d.text((24,621),'原始帧时间戳与 result 的接收时间不同，不用它们证明连续 3 帧确认。',font=f(22),fill=MUTED)
c.save(OUT/'scan_fire_raw_triptych.png');add(OUT/'scan_fire_raw_triptych.png',[RUN/'raw_images'/raw_manifest[n]['file'] for n in rawnums],'同一红色标识的原始云台视角变化，启动位置附近','三张完整原图等比例缩小拼接，标明原始帧与 ROS 时间；未添加识别结果。')
# 四类核心标记：单张完整副本及展示 ID、坐标和目标的可追溯局部裁剪。
tags=[('0639',0,'坍塌',(100,140,390,380)),('0745',1,'有毒泄漏',(245,110,565,415)),('0761',2,'被困人员',(5,100,350,475)),('0870',3,'高温',(45,150,310,335))]
c=Image.new('RGB',(1920,620),BG);d=ImageDraw.Draw(c)
for i,(n,idx,ch,crop) in enumerate(tags):
 src=RUN/f'image_{n}.png';copy(src,f'tag_{idx}_full.png',f'T{idx}｜{ch}：有 ID、位姿轴及地图坐标标签；当前画面位置数据保留。')
 im=Image.open(src).convert('RGB').crop(crop);im.save(OUT/f'tag_{idx}_crop.png');add(OUT/f'tag_{idx}_crop.png',[src],f'T{idx}｜{ch}局部，保留完整标识、 ID 与地图坐标显示。','仅裁去周边背景，裁剪坐标为 [left, top, right, bottom]。',crop=crop)
 x=20+i*480;d.text((x,12),f'T{idx}｜{ch}',font=f(32),fill=TEAL);im.thumbnail((440,440),RESAMPLE);c.paste(im,(x+(440-im.width)//2,70+(440-im.height)//2));d.text((x,527),f'run2 / image_{n}.png',font=f(21),fill=MUTED)
d.text((24,579),'真实图像中的 Tag ID、位姿轴与 map 坐标；仅裁剪背景，未重画框或修改坐标。',font=f(24),fill=MUTED)
c.save(OUT/'core_tags_four_verified.png');add(OUT/'core_tags_four_verified.png',[RUN/f'image_{n}.png' for n,_,_,_ in tags],'四类核心 AprilTag 与地图坐标拼图','四张原图按 manifest 指定坐标裁剪背景后等比例拼接；原识别标签保留。')
copy(RUN/'image_0775.png','real_red_box.png','真实红色推障箱被专用障碍检测器框为 PUSH BARRIER，紫框不是 FIRE 灾害类别；黄色背景为核心房间地面。')
copy(RUN/'image_1209.png','blue_start_and_hazards.png','蓝色起点地面与 CHEMICAL、FIRE 同时可见；绿色类别框属于墙上标识。此帧不含红箱。')
# 有来源的同帧算法回放。现存对比左半图逐像素精确匹配 v19 / image_0462。
recovery=ROOT/'avs_ws/docs/vision_recovery_example.png';v19=ROOT/'avs_ws/acceptance/recording_yolov5_smac_v19/evidence/image_0462.png';srcim=Image.open(recovery).convert('RGB');assert srcim.crop((0,0,640,480)).tobytes()==Image.open(v19).convert('RGB').tobytes()
record=next(x for x in json.load(open(ROOT/'avs_ws/docs/vision_recovery_replay.json')) if x['frame']=='image_0462.png');assert record['before']==[] and record['after']==['ELECTRICAL']
copy(recovery,'recovery_comparison_original.png','同一 v19 image_0462 的算法离线回放：原链未框出，恢复链框出 ELECTRICAL 0.35；非两次现场运行，不代表总体召回率。',replay_record=record)
for i,name in enumerate(['recovery_before.png','recovery_after.png']):
 dest=OUT/name;srcim.crop((i*640,0,(i+1)*640,480)).save(dest);add(dest,[recovery,v19],'同帧算法回放的'+('原链无检测结果' if i==0 else '恢复链 ELECTRICAL 0.35 检测结果'),'从既有真实算法回放对比图拆分左右半图，不改框。',replay_record=record)
c=Image.new('RGB',(1360,630),BG);d=ImageDraw.Draw(c)
for i,(label,name) in enumerate([('原链：未检出','recovery_before.png'),('增加恢复链：ELECTRICAL 0.35','recovery_after.png')]):
 x=20+i*680;d.text((x,10),label,font=f(28),fill=TEAL);c.paste(Image.open(OUT/name),(x,65))
d.text((22,565),'同一帧离线回放｜v19 / image_0462.png｜before=[]，after=[ELECTRICAL]',font=f(23),fill=WHITE)
d.text((22,601),'来源：docs/vision_recovery_example.png + vision_recovery_replay.json；不是全程准确率对比。',font=f(21),fill=MUTED)
c.save(OUT/'recovery_same_frame_verified.png');add(OUT/'recovery_same_frame_verified.png',[recovery,v19,ROOT/'avs_ws/docs/vision_recovery_replay.json'],'同一帧在有/无图案核验恢复链时的真实离线回放结果','在既有对比图上下增加中文说明与来源；保持左右两帧与识别结果不变。',replay_record=record)
manifest['review_sheets']=[str(p.relative_to(ROOT)) for p in sorted(OUT.glob('audit_*.jpg'))]
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('Prepared',len(manifest['assets']),'assets in',OUT)
