#!/usr/bin/env python3
"""Build a picture-led defense from source-backed assets and the current run."""
from pathlib import Path
import sys,json,hashlib,re,shutil
sys.path.insert(0,'/tmp/avs_defense_ppt_deps')
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE,MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN,MSO_ANCHOR
from pptx.util import Inches,Pt
from pptx.oxml.xmlchemy import OxmlElement
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'国赛答辩';ASSET=OUT/'素材';SCENE=ASSET/'新版场景';CAMERA=ASSET/'新版大图'
INNOV=ROOT/'创新点PPT/素材/新版';RUN=ROOT/'avs_ws/acceptance/recording_submission_20261013_gimbal_run2'
BG='101B2C';WHITE='F4F7FC';MUTED='B8C7DC';TEAL='42D5BB';GOLD='FFC466';BLUE='7AABFF';CARD='1D2C42'
FONT='Noto Sans CJK SC'
r=Presentation();r.slide_width=Inches(13.333333);r.slide_height=Inches(7.5)
r.core_properties.title='救援无人车仿真系统｜国赛答辩';r.core_properties.author='Simulator · B09018834'
slides=[]

def shape(s,x,y,w,h,color=CARD,kind=MSO_SHAPE.RECTANGLE):
 q=s.shapes.add_shape(kind,Inches(x),Inches(y),Inches(w),Inches(h));q.fill.solid();q.fill.fore_color.rgb=RGBColor.from_string(color);q.line.fill.background();return q

def text(s,value,x,y,w,h,size=24,color=WHITE,bold=False,align=PP_ALIGN.LEFT):
 q=s.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h));tf=q.text_frame;tf.word_wrap=True;tf.margin_left=tf.margin_right=0;tf.margin_top=tf.margin_bottom=0
 for i,v in enumerate(value.split('\n')):
  p=tf.paragraphs[0] if i==0 else tf.add_paragraph();p.text=v;p.font.name=FONT;p.font.size=Pt(size);p.font.bold=bold;p.font.color.rgb=RGBColor.from_string(color);p.alignment=align;p.space_after=Pt(4);p.line_spacing=1.07
 return q

def new(title,subtitle,source,notes='',backup=False):
 s=r.slides.add_slide(r.slide_layouts[6]);s.background.fill.solid();s.background.fill.fore_color.rgb=RGBColor.from_string(BG)
 text(s,title,.34,.18,12.65,.56,31,bold=True)
 text(s,subtitle,.35,.86,12.6,.32,18,MUTED)
 shape(s,.35,7.1,12.63,.014,'3B4C64')
 text(s,source,.35,7.18,12.0,.23,10.2,MUTED)
 text(s,f'{len(slides)+1:02d}',12.49,7.15,.45,.28,12,TEAL,True,PP_ALIGN.RIGHT)
 if backup:s._element.set('show','0')
 slides.append(dict(page=len(slides)+1,title=title,subtitle=subtitle,source=source,backup=backup,pictures=[]))
 s.notes_slide.notes_text_frame.text=notes
 return s

def pic(s,path,x,y,w,h,meaning,crop=None):
 path=Path(path);im=Image.open(path);iw,ih=im.size
 if crop:
  dest=ASSET/'版式裁剪'/f'{path.stem}_{"_".join(map(str,crop))}.png';dest.parent.mkdir(exist_ok=True);im.crop(crop).save(dest);path=dest;iw,ih=im.crop(crop).size
 k=min(w/iw,h/ih);nw,nh=iw*k,ih*k
 q=s.shapes.add_picture(str(path),Inches(x+(w-nw)/2),Inches(y+(h-nh)/2),Inches(nw),Inches(nh))
 slides[-1]['pictures'].append(dict(file=str(path.relative_to(ROOT)),meaning=meaning,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pixels=[iw,ih],crop=crop,box_inches=[x+(w-nw)/2,y+(h-nh)/2,nw,nh]))
 return q

def strip(s,value,y=6.55,size=24):
 shape(s,.35,y,12.63,.48,CARD);text(s,value,.51,y+.055,12.30,.38,size,TEAL,True,PP_ALIGN.CENTER)

def metric(s,value,label,x,y,w=3.2,h=1.1):
 shape(s,x,y,w,h);text(s,value,x+.17,y+.1,w-.34,.52,32,TEAL,True);text(s,label,x+.17,y+.72,w-.34,.32,18,MUTED)

def line(s,x1,y1,x2,y2,color=TEAL,width=2):
 q=s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Inches(x1),Inches(y1),Inches(x2),Inches(y2));q.line.color.rgb=RGBColor.from_string(color);q.line.width=Pt(width)
 return q

def label(s,value,x,y,w,px,py):
 shape(s,x-.05,y-.035,w+.1,.43,BG);text(s,value,x,y,w,.36,22,TEAL,True);line(s,x+w/2,y+.39,px,py);shape(s,px-.04,py-.04,.08,.08,TEAL,MSO_SHAPE.OVAL)

def table(s,headers,rows,widths,x=.4,y=1.45,total_w=12.5,row_h=.69,size=22):
 q=s.shapes.add_table(len(rows)+1,len(headers),Inches(x),Inches(y),Inches(total_w),Inches(row_h*(len(rows)+1)))
 t=q.table
 for col,v in enumerate(widths):t.columns[col].width=Inches(v)
 for i,row in enumerate([headers]+rows):
  for j,v in enumerate(row):
   c=t.cell(i,j);c.fill.solid();c.fill.fore_color.rgb=RGBColor.from_string('263D58' if i==0 else (CARD if i%2 else '17253A'))
   c.margin_left=c.margin_right=Inches(.13);c.margin_top=Inches(.08);c.margin_bottom=Inches(.04)
   c.text=str(v);c.vertical_anchor=MSO_ANCHOR.MIDDLE
   for p in c.text_frame.paragraphs:p.font.name=FONT;p.font.size=Pt(size);p.font.bold=i==0;p.font.color.rgb=RGBColor.from_string(TEAL if i==0 else WHITE)
 return t

# 01 Cover: preserve the team information from the previous defense.
s=new('救援无人车仿真系统','第十九届先进机器人及仿真技术大赛 · 无人车仿真组','车辆结构：当前 SDF 几何渲染，与 URDF 可视结构对应。')
pic(s,ROOT/'avs_ws/docs/report_assets/vehicle_model.png',5.05,1.2,7.9,5.84,'新版完整车辆结构，按当前 SDF 渲染')
text(s,'巡检 · 实体清障\n地图标定 · 自主返航',.55,1.75,5.6,1.4,29,bold=True)
text(s,'Simulator  /  B09018834',.55,3.55,5.8,.5,24,TEAL,True)
text(s,'队长  陈莎莎\n队员  梁辰瑜、赖丽燕、初冉\n指导教师  蒋玉莲、王俊',.55,4.35,5.6,1.42,20,MUTED)

# 02 Show the scene and the measured online map at near-equal scale.
s=new('自建厂区：走廊巡检 → 清障入室 → 标定 → 返航','本队场地 3 × 3 m，入口宽 0.50 m；九块标识图案各不相同','图：2026-10-13 同次 Gazebo 录屏及独立 slam_toolbox 留档；评分见本地 B09 规则。')
pic(s,SCENE/'scene.png',.35,1.34,7.12,4.92,'新版 Gazebo 自建厂区布局')
pic(s,RUN/'evidence/slam_map.png',7.68,1.34,5.3,4.92,'同次运行独立在线 SLAM 占据栅格地图')
text(s,'自建 Gazebo 场景',.6,6.25,6.7,.4,24,TEAL,True,PP_ALIGN.CENTER);text(s,'在线 SLAM 地图留档',7.75,6.25,5.17,.4,24,TEAL,True,PP_ALIGN.CENTER)

# 03 The movie gets the largest usable 16:9 rectangle; no crop of the recording.
s=new('完整任务演示','点击画面播放 · 2 分 51 秒 · 全程 2 倍速 · 无配音','同次录屏：recording_submission_20261013_gimbal_run2；旁路日志与验收记录保留。')
video=ROOT/'avs_ws/submission/B09018834.mp4';shutil.copy2(video,OUT/'B09018834_完整演示.mp4')
# Full-frame movie preserves the clock, camera, RViz and terminal at maximum size.
for existing in list(s.shapes):s.shapes._spTree.remove(existing._element)
movie=s.shapes.add_movie(str(video),0,0,r.slide_width,r.slide_height,poster_frame_image=str(SCENE/'poster_full.png'),mime_type='video/mp4')
slides[-1]['movie']=dict(file='国赛答辩/B09018834_完整演示.mp4',sha256=hashlib.sha256(video.read_bytes()).hexdigest(),duration_s=170.934,rectangle_inches=[0,0,13.333333,7.5])

# 04 Keep the vehicle complete and magnify its new mounting hardware.
s=new('新版云台与被动 V 形推板','安装底板 → 支撑柱 → 旋转底座；几何引导与受约束控制协同','图：当前 rescue_rover/model.sdf 等比例渲染；与 urdf/rescue_rover.urdf 对应。')
car=ROOT/'avs_ws/docs/report_assets/vehicle_model.png';pic(s,car,.2,1.20,8.2,5.66,'新版完整车辆与 V 形推板')
pic(s,car,8.65,1.43,4.18,3.52,'云台安装底板、支撑柱与旋转底座局部',crop=(1135,185,1665,735))
label(s,'V 形推板',6.14,6.17,1.7,6.60,5.26)
text(s,'云台安装结构（局部放大）',8.48,5.12,4.5,.5,22,TEAL,True,PP_ALIGN.CENTER)
text(s,'整车宽约 0.285 m\n推板宽 0.28 m',8.63,5.88,4.17,.9,24,bold=True)

# 05 New-run images replace historical push frames.
s=new('真实接触推障：对准、推进、脱离','2 kg 动态箱体；0.10 m/s 闭环推障；里程计推进目标 1.08 m','三图：新版同次录屏 00:47 / 00:53 / 00:59，裁去界面背景；框、车辆与箱体原样保留。')
for i,(name,title) in enumerate([('push_before','① 对准入口'),('push_during','② 实体推进'),('push_after','③ 转向脱离')]):
 x=.35+i*4.28;text(s,title,x,1.3,4.07,.5,25,TEAL,True,PP_ALIGN.CENTER);pic(s,SCENE/(name+'.png'),x,1.9,4.07,4.82,title+'同次真实物理交互')

# 06 Reuse the innovation deck's wide safety diagram at full width.
s=new('主动接触的安全边界：保护完整车体','推板也在停车扫掠范围内；检查指令速度与实际惯性速度','图源：创新点 PPT 第 5 页；当前 footprint 与 motion_safety.py 绘制的保护原理。')
pic(s,INNOV/'control/完整轮廓停车保护示意.png',.35,1.25,12.63,5.31,'完整轮廓在直行与转弯时的停车扫掠范围')
strip(s,'低速前方接触 · 侧后继续保护 · 脱离 ≤12 s / ≤6 cm',6.55,23)

# 07 A/B images demonstrate different scan angles at one stop.
s=new('云台左右观察，任务等待多帧确认','到观察点 → 确认停车 → 扫描 → 连续 3 个关联处理帧 → 继续','图：创新点 PPT 第 2 页，同一停车点两个扫视时刻；用于机制说明，与本次量化结果分开。')
for i,(filename,caption) in enumerate([('scan_stop_A.png','扫视时刻 A'),('scan_stop_B.png','扫视时刻 B')]):
 x=.35+i*6.42;pic(s,INNOV/'vision'/filename,x,1.31,6.21,4.73,'同一停车点不同扫视视角');text(s,caption,x,6.23,6.21,.43,25,TEAL,True,PP_ALIGN.CENTER)

# 08/09 Split five-class evidence to keep both boxes and terminal output legible.
s=new('走廊识别：火灾、化学、辐射','绿色框为当前图案分类；三帧确认事件与单帧显示框分别记录','相机图：新版同次运行，保留原检测框与类别；原图与裁剪坐标见素材来源记录。')
for i,(name,title) in enumerate([('fire','火灾 FIRE'),('chemical_video','化学 CHEMICAL'),('radiation','辐射 RADIATION')]):
 x=.35+i*4.28;text(s,title,x,1.27,4.07,.42,23,TEAL,True,PP_ALIGN.CENTER);pic(s,CAMERA/(name+'_large.png'),x,1.88,4.07,4.94,'同次实际 '+name+' 分类与检测框')

s=new('走廊识别：电气、生物危害与终端打印','规则要求：入室前识别五类标识，并在终端打印结果','相机及终端：新版同次连续录屏；终端原字保留，按行裁剪换行排布，未重写检测结果。')
for i,(name,title) in enumerate([('electrical','电气 ELECTRICAL'),('biohazard_video','生物 BIOHAZARD')]):
 x=.35+i*4.28;text(s,title,x,1.27,4.07,.42,23,TEAL,True,PP_ALIGN.CENTER);pic(s,CAMERA/(name+'_large.png'),x,1.9,4.07,4.8,'同次实际 '+name+' 分类与检测框')
text(s,'五类终端确认',9.0,1.28,3.9,.5,22,TEAL,True,PP_ALIGN.CENTER)
pic(s,CAMERA/'corridor_terminal.png',9.0,1.99,3.98,4.8,'同次五类识别确认的真实终端打印')

# 10 Same input replay: large panel, only one line of mechanisms.
s=new('同帧局部放大重检，恢复部分小目标','同色负例训练 → 图案 / 牌边核验 → 局部重检 → 时序确认','图源：创新点 PPT 第 7 页；v19 / image_0462 同输入离线回放，不是两次现场录像。')
pic(s,INNOV/'vision/recovery_same_frame_verified.png',.35,1.29,12.63,5.69,'同一输入帧未检出与区域恢复 ELECTRICAL 的回放对照')

# 11 Four panels fill the body; retain true algorithm text and coordinates.
for group,title in [([(0,'T0 · 坍塌'),(1,'T1 · 有毒泄漏')],'核心标识：坍塌与有毒泄漏'),([(2,'T2 · 被困人员'),(3,'T3 · 高温')],'核心标识：被困人员与高温')]:
 s=new(title,'四种图案各不相同；核心标识附加 AprilTag，类别由 ID 与语义表关联','相机图：新版同次运行，保留原 ID、类别与估计 map 坐标；仅裁背景。')
 for i,(tag,caption) in enumerate(group):
  x=.35+i*6.42;text(s,caption,x,1.28,6.21,.53,27,TEAL,True,PP_ALIGN.CENTER)
  pic(s,CAMERA/f'tag_{tag}_large.png',x,1.94,6.21,4.85,'同次核心标签 '+str(tag)+' 与估计地图坐标')

# 12 A readable RViz map demonstrates the scoring evidence.
s=new('拍摄时刻 TF，让视觉结果对应 RViz 地图','实际云台关节角 → 图像拍摄时刻坐标变换 → 多次有效观测融合','地图：新版同次录屏 01:26 的 RViz；源码机制来自 vision_node.py，非纯 PnP 误差。')
pic(s,SCENE/'core_markers.png',.35,1.29,9.06,5.69,'同次 RViz 四个核心 Marker 与地图布局')
for i,(a,b) in enumerate([('拍摄时刻','匹配实际关节姿态'),('质量筛选','重投影 ≤2.5 px'),('融合确认','至少 4 次有效观测')]):
 y=1.72+i*1.68;shape(s,9.73,y,3.24,1.32);text(s,a,9.9,y+.12,2.9,.4,26,TEAL,True);text(s,b,9.9,y+.78,2.9,.43,19)

# 13 Large real PGM plus a large detail view of the tiny doorway window.
s=new('门洞残留栅格清理区：让旧占用不再堵路','限定区域内，三次不同时间戳的激光自由证据才清理派生导航图','图：实际 rescue_map.pgm + navigation_map.yaml；配置叠加原理图，未录制逐格清理前后对照。')
pic(s,ROOT/'avs_ws/docs/report_assets/navigation_map_regions.png',.35,1.26,5.77,5.70,'实际 PGM 上的可移动箱体区域与门洞残留栅格清理区')
pic(s,ASSET/'地图门洞放大.png',6.37,1.26,6.61,4.5,'门洞区域原始 PGM 的同区域放大，叠加配置允许范围')
text(s,'原始 PGM 保留\n新障碍由实时激光层标记',6.55,6.01,6.26,.8,25,TEAL,True)

# 14 Editable large chart, values read from the historical experiment.
s=new('按任务阶段选速度：完整任务平均缩短 7.6%','普通 0.20 m/s · 精细 0.12 m/s · 推障 0.10 m/s；到位置后单独对正朝向','数据：2026-10-12 独立无界面速度实验；1 次基准、2 次最终配置，与本次 GUI 录屏分别统计。')
text(s,'首次导航 → 完整任务完成',.55,1.4,9.3,.5,27,bold=True)
for i,(label_text,v,color) in enumerate([('原速（1 次）',310.82,MUTED),('最终（2 次均值）',287.20,TEAL)]):
 y=2.38+i*1.67;text(s,label_text,.6,y+.21,3.25,.52,26,bold=True);shape(s,4.05,y,v/340*7.1,.96,color);text(s,f'{v:.2f} s',4.05+v/340*7.1+.19,y+.19,2.1,.52,31,color,True)
text(s,'节省 23.62 s',.7,5.79,4.8,.72,37,GOLD,True)
text(s,'5 类 + 4 标签\n两次均完成全部目标',6.03,5.71,6.7,1.0,28,TEAL,True)

# 15 All current values come from one run, not the innovation deck's historical run.
ev=json.loads((RUN/'evidence/evaluation.json').read_text())
s=new('当前视频的同次验收结果','完整任务、相机画面、日志、轨迹和源码哈希对应同一运行','同次 evidence/evaluation.json；墙体轮廓离散采样为空，不等于连续接触测量。')
pic(s,RUN/'evidence/trajectory.png',.35,1.3,5.37,5.63,'同次独立验收旁路绘制的真实位置轨迹')
for x,y,v,l in [(5.95,1.45,'5 / 5','走廊类别'),(9.5,1.45,'4 / 4','核心 Marker'),(5.95,3.05,'0.9960 m','箱体实际位移'),(9.5,3.05,'4.26 cm','返航位置误差')]:metric(s,v,l,x,y,3.48,1.25)
text(s,'四标记 map 平面误差',6.14,4.8,6.5,.5,25,bold=True);text(s,'7.52–13.94 cm',6.14,5.47,6.5,.74,37,TEAL,True)
text(s,'在线 SLAM 已留档 · 项目验收通过',6.13,6.4,6.65,.4,22,MUTED)

# 16 Conclude within the eight-minute rule; technical details stay in backup.
s=new('团队贡献：结构、感知与导航协同实现','面向本场地验证；下一步做随机初始条件、逐帧评估与接触力检测','基础算法与框架明确第三方归属，团队贡献可追溯到机构设计、源码及实测。')
for i,(num,title,body) in enumerate([('01','结构与接触','新版云台 · 被动推板\n完整轮廓 · 有界接触'),('02','感知与标定','图案 · 几何 · 时序核验\n拍摄时刻 TF · 位置融合'),('03','导航与复现','激光自由证据地图处理\n阶段控制 · 独立验收')]):
 x=.35+i*4.28;shape(s,x,1.66,4.07,3.35);text(s,num,x+.23,1.87,3.6,.53,31,TEAL,True);text(s,title,x+.23,2.61,3.6,.5,28,bold=True);text(s,body,x+.23,3.46,3.6,1.24,21)
text(s,'第三方基础：ROS 2 · Gazebo · Nav2 · slam_toolbox\nYOLOv5 · OpenCV · AprilTag',.45,5.56,12.45,.88,22,MUTED,align=PP_ALIGN.CENTER)
text(s,'谢谢各位老师',.45,6.5,12.45,.5,28,TEAL,True,PP_ALIGN.CENTER)

# 17–22 Hidden backup pages, accessible for questions.
s=new('备份 A｜比赛评分与现场证据','国赛 8 分钟包含视频；展示结束后按需回答提问','依据：本地 B09 比赛规则（2026 年 7 月）；项目验收门限不等同官方评分阈值。',backup=True)
table(s,['评分项','分值','现场证据'],[
['自建环境与单车建图','15','Gazebo 场景与清晰占据栅格地图'],['五类走廊识别','20','入室前 5 类分类 + 终端打印'],['入口清障交互','20','真实推箱 + 平稳驶入核心区'],['核心识别与标定','20','四 AprilTag + RViz Marker 与布局吻合'],['返回起点','5','完整返航画面与 complete 事件'],['方案创新性答辩','20','场景、机构、视觉与导航的团队改进']], [3.5,1.1,7.9],row_h=.73,size=22)

s=new('备份 B｜传感器、任务与执行闭环','YAML 给任务目标，Nav2 根据地图规划路径；23 步任务由事件推进','来源：launch/sim_launch.py、mission_node.py、vision_node.py 与 safety_node.py。',backup=True)
for x,title,body in [( .55,'感知与定位','激光 + 里程计 → AMCL\n图像 + 云台关节角 → 识别 / TF'),(4.93,'任务与导航','确认事件 → 任务状态机\nSmac2D 栅格 A* → RPP 跟踪'),(9.30,'安全与执行','速度平滑 → 安全检查\n完整车体停车扫掠 → 车轮')]:
 shape(s,x,2.1,3.5,3.05);text(s,title,x+.18,2.32,3.15,.5,27,TEAL,True);text(s,body,x+.18,3.14,3.15,1.7,22)
line(s,4.1,3.7,4.78,3.7);line(s,8.5,3.7,9.14,3.7);strip(s,'任务与视觉不读世界真值；独立验收工具旁路记录',6.12,24)

s=new('备份 C｜定位误差先统一坐标系','map←odom 变换统一真实位置与估计位置；误差含测距与定位漂移','本次录屏同次 evaluation.json；raw world/map 差不可直接作为定位误差。',backup=True)
rows=[]
for i,name in enumerate(['COLLAPSE','TOXIC_LEAK','TRAPPED_PERSON','HIGH_TEMPERATURE']):rows.append([f'T{i}',name,f"{ev['core_marker_errors_m'][str(i)]*100:.2f}",f"{ev['raw_world_map_coordinate_difference_m'][str(i)]*100:.2f}"])
table(s,['ID','类别','统一 map / cm','原始坐标差 / cm'],rows,[1,4.75,3.15,3.6],y=1.7,row_h=.86,size=23)
text(s,'上述数值全部属于新版录屏；15 cm 是项目自定验收门限。',.6,6.37,12.1,.52,23,TEAL,True)

s=new('备份 D｜更快的候选不一定更快完成任务','评价从首次导航到完整任务完成；保留失败候选与完整日志','历史速度实验：speed_tuning_validation.json，1 次基准、2 次最终配置。',backup=True)
table(s,['配置','任务耗时 / s','结果','说明'],[['原速基准','310.82','通过','1 次基准'],['最终 0.20 / 第 1 次','286.07','通过','Marker 7.67–12.83 cm'],['最终 0.20 / 第 2 次','288.32','通过','Marker 4.41–6.83 cm'],['分档 0.24','296.84','通过','末端对正耗时更长'],['全程 0.24','不计成绩','失败','门洞触发激光保护'],['分档 0.30','不计成绩','失败','横偏与异常转向停车']], [3.65,2.45,1.3,5.1],row_h=.75,size=21)

s=new('备份 E｜视觉指标与工程确认条件','单帧显示框、历史确认列表、任务确认事件是不同信息','模型合成集指标：yolov5/hazard_yolov5.json；时序规则见 tracker 与 vision_node。',backup=True)
table(s,['项目','指标 / 条件','解释范围'],[['合成模型验证','P 85.62% / R 70.81%','160 张、IoU≥0.50、conf 0.45'],['无目标合成图','2 / 59 有误报','图像级误报率 3.39%'],['走廊事件','连续 3 个关联处理帧','不等于一帧看到框就确认'],['核心定位','至少 4 次有效观测','不要求连续 4 帧'],['完整任务','5 类 + 4 标签全部确认','不等于逐帧零误报或零漏报'],['红箱像素框','仅作显示','不参与导航与推障授权']], [3.1,4.35,5.05],row_h=.75,size=21)

s=new('备份 F｜评委常见追问','用源码、原始日志和同次录屏说明机制与验证范围','复现环境：Ubuntu 22.04、ROS 2 Humble、Gazebo Classic 11；一键 start.sh。',backup=True)
questions=[('如何证明真实推障？','2 kg 动态箱体、物理碰撞与摩擦、独立位移记录。'),('是否按固定速度硬走路线？','YAML 只给任务目标，路径与跟踪由 Nav2 完成。'),('地图清理会忽略真实障碍吗？','限定区域、三次自由证据，实时激光层继续标记。'),('团队创新体现在哪里？','基础算法明确归属，团队实现结构、核验、控制与集成。'),('已经证明全程绝对无碰撞吗？','墙体检查是离散采样；尚无连续接触传感器证明。')]
for i,(a,b) in enumerate(questions):
 y=1.48+i*1.04;text(s,a,.53,y,5.15,.45,23,TEAL,True);text(s,b,5.93,y,6.88,.8,22)

# Match slide notes to the updated paginated speech after it is available.
guide=OUT/'AVS_国赛答辩逐页讲稿.md'
if guide.exists():
 for match in re.finditer(r'## 第(\d+)页[^\n]*\n(.*?)(?=\n## |\Z)',guide.read_text(),re.S):
  idx=int(match.group(1))-1
  if 0<=idx<len(r.slides):r.slides[idx].notes_slide.notes_text_frame.text=match.group(0)
path=OUT/'AVS_国赛答辩.pptx';r.save(path)
for item,s in zip(slides,r.slides):
 area=sum(sh.width*sh.height for sh in s.shapes if sh.shape_type==13)
 if item.get('movie'):area+=r.slide_width*r.slide_height
 item['picture_slide_percent']=round(area/(r.slide_width*r.slide_height)*100,1)
 item['picture_content_percent']=100 if item.get('movie') else round(area/(Inches(12.63)*Inches(5.74))*100,1)
(OUT/'PPT配图与版式核对.json').write_text(json.dumps(dict(recording=RUN.name,main_slides=17,backup_slides=6,presentation_target_s=455,slides=slides),ensure_ascii=False,indent=2))
print(path)
print([(x['page'],x['picture_slide_percent'],x['picture_content_percent']) for x in slides[:17]])
