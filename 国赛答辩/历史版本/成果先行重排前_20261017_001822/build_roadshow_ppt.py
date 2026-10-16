#!/usr/bin/env python3
"""Build the source-backed competition pitch, scripts, and an auditable manifest.

Requires python-pptx and Pillow. All content lives in roadshow_content.json;
the Markdown, TXT, and slide notes are derived from that single source.
"""
from pathlib import Path
import sys, json, hashlib, re, subprocess, math
sys.path.insert(0, '/tmp/avs_ppt_deps')
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = json.loads((HERE / 'roadshow_content.json').read_text())
PAGES = DATA['slides']
GENERATED = HERE / '素材/路演新版'
GENERATED.mkdir(parents=True, exist_ok=True)
FONT = 'Noto Sans CJK SC'
NAVY, INK, RED, BLUE = '102D4C', '18334F', 'CE3E38', '296497'
MUTED, LINE, PAPER, WHITE = '647386', 'DDE4EC', 'F5F7FA', 'FFFFFF'
PALE, REDPALE, TEAL = 'EAF0F7', 'FCEFEB', '1B7C7A'
PPT = Presentation()
PPT.slide_width, PPT.slide_height = Inches(13.333333), Inches(7.5)
PPT.core_properties.title = '救援无人车仿真系统｜问题 · 方案 · 创新'
PPT.core_properties.author = 'Simulator · B09018834'
MANIFEST = []
ACTIVE = None

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def box(slide, x, y, w, h, color, kind=MSO_SHAPE.RECTANGLE, border=None):
    q = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    q.fill.solid(); q.fill.fore_color.rgb = RGBColor.from_string(color)
    if border:
        q.line.color.rgb = RGBColor.from_string(border); q.line.width = Pt(1)
    else:
        q.line.fill.background()
    q._element.spPr.append(OxmlElement('a:effectLst'))
    for ref in q._element.findall('.//' + qn('a:effectRef')):ref.set('idx','0')
    return q

def tx(slide, value, x, y, w, h, size=20, color=INK, bold=False, align=PP_ALIGN.LEFT):
    q = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    f = q.text_frame; f.word_wrap = True
    f.margin_left = f.margin_right = f.margin_top = f.margin_bottom = 0
    for i, part in enumerate(str(value).split('\n')):
        p = f.paragraphs[0] if i == 0 else f.add_paragraph()
        p.text = part; p.font.name = FONT; p.font.size = Pt(size)
        p.font.bold = bold; p.font.color.rgb = RGBColor.from_string(color)
        p.alignment = align; p.space_after = Pt(4); p.line_spacing = 1.10
        # Force the same CJK font in PowerPoint and LibreOffice.
        for run in p.runs:
            rp = run._r.get_or_add_rPr()
            ea = OxmlElement('a:ea'); ea.set('typeface', FONT); rp.append(ea)
    ACTIVE['texts'].append(dict(text=str(value), box_inches=[x, y, w, h], font_pt=size))
    return q

def ln(slide, x1, y1, x2, y2, color=LINE, width=1.2):
    q = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    q.line.color.rgb = RGBColor.from_string(color); q.line.width = Pt(width)
    q._element.spPr.append(OxmlElement('a:effectLst'))
    for ref in q._element.findall('.//' + qn('a:effectRef')):ref.set('idx','0')
    return q

def arrow(slide, x, y, w=.3, h=.23, color=RED):
    return box(slide, x, y, w, h, color, MSO_SHAPE.CHEVRON)

def picture(slide, path, x, y, w, h, meaning='', crop=None):
    p = Path(path)
    im = Image.open(p)
    original = p
    if crop:
        dest = GENERATED / (p.stem + '_crop.png'); im = im.crop(crop); im.save(dest); p = dest
    iw, ih = im.size; scale = min(w/iw, h/ih); nw, nh = iw*scale, ih*scale
    actual = [x+(w-nw)/2, y+(h-nh)/2, nw, nh]
    q = slide.shapes.add_picture(str(p), *(Inches(v) for v in actual))
    ACTIVE['images'].append(dict(file=str(p.relative_to(ROOT)), source=str(original.relative_to(ROOT)), sha256=sha(p), meaning=meaning, crop=crop, box_inches=actual))
    return q

def header(page, dark=False):
    global ACTIVE
    ACTIVE = dict(page=page['page'], title=page['title'], backup=page.get('backup',False), images=[], texts=[])
    MANIFEST.append(ACTIVE)
    s = PPT.slides.add_slide(PPT.slide_layouts[6])
    s.background.fill.solid(); s.background.fill.fore_color.rgb = RGBColor.from_string(NAVY if dark else WHITE)
    if page.get('backup'): s._element.set('show','0')
    if not dark:
        box(s,.48,.32,.36,.055,RED)
        tx(s,page.get('kicker','AVS · 工程创新'),.98,.23,10.9,.28,11,RED,True)
        title_size = 30 if len(page['title'])<24 else 27
        tx(s,page['title'],.5,.77,12.4,.70,title_size,INK,True)
        tx(s,page.get('subtitle',''),.52,1.53,12.2,.55,15,MUTED)
        ln(s,.5,6.98,12.84,6.98)
        tx(s,'SIMULATOR  /  B09018834',.52,7.13,3.25,.18,8.5,MUTED)
        tx(s,f"{page['page']:02d}" + ('  备用' if page.get('backup') else ''),11.8,7.08,1.0,.28,11,RED,True,PP_ALIGN.RIGHT)
    return s

def source(slide, value):
    tx(slide, value, .52, 6.73, 12.1, .21, 8.5, MUTED)

def innovation(slide, value):
    box(slide,.5,6.10,12.34,.47,REDPALE)
    tx(slide,'创新点',.67,6.19,.76,.30,14,RED,True)
    tx(slide,value,1.60,6.18,10.98,.32,16,INK,True)

def issue(slide, page):
    tx(slide,'遇到的问题',.53,2.15,3.35,.32,12,RED,True)
    tx(slide,page.get('display_problem',page['problem']),.53,2.63,3.42,1.12,20,INK,True)
    ln(slide,.53,3.92,3.88,3.92)
    tx(slide,'对应方案',.53,4.12,3.35,.30,12,BLUE,True)
    tx(slide,page.get('display_solution',page['solution']),.53,4.60,3.45,1.20,17,INK)
    innovation(slide,page.get('display_innovation',page['innovation']))

def step(slide, label, x, y, w, subtitle='', fill=PALE, main_color=BLUE):
    box(slide,x,y,w,.70,fill)
    tx(slide,label,x+.08,y+.15,w-.16,.35,16,main_color,True,PP_ALIGN.CENTER)
    if subtitle:tx(slide,subtitle,x,y+.89,w,.65,13,MUTED,False,PP_ALIGN.CENTER)

def clean_vehicle():
    """Remove the flat render background, preserving all model pixels."""
    src = ROOT/'avs_ws/docs/report_assets/vehicle_model.png'
    im=Image.open(src).convert('RGBA'); pixels=im.load();bg=(29,44,66)
    for y in range(im.height):
        for x in range(im.width):
            r,g,b,a=pixels[x,y]
            if max(abs(r-bg[0]),abs(g-bg[1]),abs(b-bg[2]))<7:pixels[x,y]=(r,g,b,0)
    bounds=im.getbbox(); im=im.crop(bounds);dest=GENERATED/'vehicle_transparent.png';im.save(dest)
    return dest

CAR=clean_vehicle()
INNOV=ROOT/'创新点PPT/素材/新版'
SCENE=HERE/'素材/新版场景'
video=HERE/'B09018834.mp4'
if not video.exists():video=ROOT/'avs_ws/submission/B09018834.mp4'
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)]))
duration=float(probe['format']['duration'])

for p in PAGES:
    n=p['page']
    s=header(p,dark=n in (1,13))
    if n==1:
        # A competition pitch cover: one proposition, one real model, strong type.
        box(s,.55,.60,.5,.055,RED)
        tx(s,'第十九届先进机器人及仿真技术大赛 · 无人车仿真组',1.2,.51,11.2,.4,14,'B9CADC')
        tx(s,'救援无人车\n仿真系统',.55,1.53,6.2,2.18,49,WHITE,True)
        tx(s,'把观察、接触与导航\n组织成可验证的自主任务',.59,4.02,5.8,1.03,24,'DEE8F3')
        box(s,.58,5.55,.055,.91,RED)
        tx(s,'Simulator  /  B09018834',.85,5.52,5.4,.38,20,WHITE,True)
        tx(s,'队长 陈莎莎  ｜  队员 梁辰瑜、赖丽燕、初冉\n指导教师 蒋玉莲、王俊',.85,6.08,7.8,.75,12,'B9CADC')
        picture(s,CAR,6.20,1.68,6.88,4.85,'依据当前 SDF 几何渲染；仅移除单色背景')
        tx(s,'问题驱动  /  结构与算法协同  /  证据验证',7.08,6.28,5.4,.48,14,'B9CADC',False,PP_ALIGN.CENTER)
        tx(s,'模型来源：rescue_rover/model.sdf；结构渲染，非实拍',7.00,7.10,5.8,.18,8,'9FB4CD',False,PP_ALIGN.RIGHT)
    elif n==2:
        box(s,.5,2.15,6.27,3.73,NAVY)
        picture(s,SCENE/'scene.png',.53,2.18,6.21,3.67,'真实 Gazebo 场景截图，用于说明狭窄布局')
        tx(s,'封闭厂区事故后的初步勘探',.65,6.18,5.9,.38,20,INK,True)
        items=[('01','看见了，未必可靠','侧墙视角短暂，同色物体干扰'),('02','要接触，也要避障','清障动作与普通避碰逻辑冲突'),('03','识别到，还要标得对','扫描相机的姿态必须与图像匹配'),('04','障碍挪走，地图仍占用','场景变化会破坏原有规划条件')]
        for i,(a,b,c) in enumerate(items):
            y=2.18+i*1.03
            tx(s,a,7.08,y,.64,.45,26,RED,True)
            tx(s,b,7.91,y+.02,4.89,.42,21,INK,True)
            tx(s,c,7.93,y+.56,4.88,.38,14,MUTED)
            if i<3:ln(s,7.92,y+.91,12.75,y+.91)
        source(s,'任务背景：本地 B09 规则；问题依据：TECHNICAL_REPORT 第 3–8 节与 debug_history.json。')
    elif n==3:
        # Rows map a concrete failure to the mechanism and a useful innovation.
        tx(s,'工程问题',.65,2.15,3.1,.37,15,RED,True)
        tx(s,'对应方案',4.55,2.15,4.3,.37,15,BLUE,True)
        tx(s,'形成的创新',9.15,2.15,3.4,.37,15,TEAL,True)
        rows=[('短时观察 / 同色误检','扫描与停车协同 + 多级视觉核验','观察动作与确认事件闭环'),('主动推箱 / 全车避碰','被动 V 形推板 + 有界接触授权','机构、闭环控制与安全协同'),('相机在动 / 地图要准','拍摄时刻 TF + 质量筛选与融合','观测时间与实际姿态对应'),('旧图堵门 / 末端纠偏','自由证据更新 + 分阶段导航','地图与任务控制协同')]
        for i,(a,b,c) in enumerate(rows):
            y=2.86+i*.74
            if i%2==0:box(s,.5,y-.12,12.34,.67,PAPER)
            tx(s,a,.65,y,3.4,.42,18,INK,True);arrow(s,4.02,y+.055,.28,.18)
            tx(s,b,4.55,y,4.5,.42,17,INK);arrow(s,8.69,y+.055,.28,.18)
            tx(s,c,9.15,y,3.5,.42,16,TEAL,True)
        innovation(s,'六项工程改进，分别回应可定位的失效原因')
        source(s,'实现依据：camera_scan_node / hazard_tracker / mission_node / safety_node / vision_node / navigation_map_node。')
    elif n==4:
        issue(s,p)
        for i,(name,caption) in enumerate([('scan_stop_A.png','同一停车点 · 扫视时刻 A'),('scan_stop_B.png','同一停车点 · 扫视时刻 B')]):
            x=4.45+i*4.23
            picture(s,INNOV/'vision'/name,x,2.16,4.06,2.65,'历史同一停车点不同视角；不作为连续三帧证据')
            tx(s,caption,x,4.92,4.06,.3,12,MUTED,False,PP_ALIGN.CENTER)
        for i,(label,sub) in enumerate([('到点停稳','位置与速度检查'),('核对确认','确认可先于停车产生'),('继续任务','满足最低等待时间')]):
            x=4.54+i*2.75;step(s,label,x,5.35,2.34,fill=PALE)
            if i<2:arrow(s,x+2.45,5.59,.22,.17)
        source(s,'源码：camera_scan_node.py / hazard_tracker.py / mission_node.py；图：历史停车点 A/B 视角，非连续三帧证据。')
    elif n==5:
        issue(s,p)
        picture(s,INNOV/'vision/recovery_same_frame_verified.png',4.37,2.10,8.43,3.91,'v19/image_0462 同输入离线回放；左未检出，右局部重检恢复')
        source(s,'证据：vision_recovery_replay.json，v19 / image_0462；同帧回放仅说明该例恢复，不推导全量准确率提升。')
    elif n==6:
        issue(s,p)
        picture(s,CAR,4.30,2.08,3.57,2.53,'当前 SDF 渲染的被动推板与完整车体')
        tx(s,'几何引导 + 里程计反馈',4.40,4.67,3.47,.4,15,INK,True,PP_ALIGN.CENTER)
        picture(s,INNOV/'control/完整轮廓停车保护示意.png',7.98,2.12,4.88,2.50,'依据当前 footprint 与 motion_safety.py 的停车扫掠原理示意')
        tx(s,'完整车体停车扫掠检查',8.02,4.67,4.78,.4,15,INK,True,PP_ALIGN.CENTER)
        box(s,4.42,5.30,8.36,.50,PALE)
        tx(s,'阶段授权  →  前方窄窗口接触  →  限时限位脱离',4.54,5.42,8.10,.3,15,BLUE,True,PP_ALIGN.CENTER)
        source(s,'源码：model.sdf / mission_node.py / motion_safety.py / safety_node.py；右图为原理示意，当前无接触力反馈。')
    elif n==7:
        issue(s,p)
        # An editable time diagram: the two instants are deliberately distinct.
        tx(s,'图像与姿态必须属于同一个时刻',4.55,2.16,8.1,.43,23,INK,True)
        ln(s,4.87,3.32,12.47,3.32,MUTED,2)
        for x,a,b in [(5.50,'t₀  拍摄','图像 + 实际云台角'),(11.24,'t₁  处理','处理完成时姿态')]:
            box(s,x,3.25,.14,.14,RED,MSO_SHAPE.OVAL)
            tx(s,a,x-.68,2.88,2.35,.35,16,RED,True,PP_ALIGN.CENTER)
            tx(s,b,x-1.25,3.68,3.05,.44,14,MUTED,False,PP_ALIGN.CENTER)
        box(s,5.06,4.33,7.65,.64,PALE)
        tx(s,'等待图像时刻 TF；图像超过时限则丢弃',5.19,4.49,7.39,.35,17,BLUE,True,PP_ALIGN.CENTER)
        tx(s,'相机坐标 → 云台 → 底盘 → odom → map',4.53,5.38,8.22,.38,18,INK,True,PP_ALIGN.CENTER)
        source(s,'源码：vision_node.py；定位链为机制示意。TF、质量筛选及融合均已实现，尚无逐项消融对照。')
    elif n==8:
        issue(s,p)
        picture(s,ROOT/'avs_ws/docs/report_assets/navigation_map_regions.png',4.34,2.08,3.69,3.29,'原始 PGM 叠加配置允许清理区，非实测前后对照')
        picture(s,HERE/'素材/地图门洞放大.png',8.11,2.08,4.69,3.29,'同一原始地图门洞区域放大与清理矩形')
        tx(s,'实际 PGM + 区域配置',4.39,5.40,3.6,.32,13,MUTED,False,PP_ALIGN.CENTER)
        tx(s,'仅清理有重复自由证据的栅格',8.10,5.40,4.71,.32,13,MUTED,False,PP_ALIGN.CENTER)
        source(s,'源码：navigation_map_node.py / navigation_map.yaml；原图及允许区示意，尚未保存派生地图逐格更新前后对照。')
    elif n==9:
        issue(s,p)
        # Native editable bars; values come from the archived historical run data.
        tx(s,'首次导航 → 完整任务完成',4.55,2.13,8.1,.43,20,INK,True)
        vals=[('原速基准',310.82,'9AACBF'),('最终配置',287.20,BLUE)]
        for i,(label,v,col) in enumerate(vals):
            y=2.96+i*.91;tx(s,label,4.58,y+.10,1.55,.40,16,INK)
            bar=v/340*4.61;box(s,6.12,y,bar,.57,col)
            tx(s,f'{v:.2f} s',6.12+bar+.15,y+.07,1.8,.45,20,col,True)
        tx(s,'7.6%',4.56,5.02,2.65,.77,42,RED,True)
        tx(s,'平均耗时缩短\n1 次基准 / 2 次最终配置',7.47,5.03,5.2,.74,16,INK)
        source(s,'2026-10-12 无界面历史实验：speed_tuning_validation.md/json；样本有限，与当前 GUI 录屏分开统计。')
    elif n==10:
        levels=[('01','机制是否成立','源码与配置核对\n相同输入图像回放','复核方案实现及单例效果'),('02','改动是否有效','同口径历史速度实验\n保留失败候选','评价完整任务，不只看最高速度'),('03','结果是否可信','事件 · 图像 · 轨迹 · TF\n源码哈希与旁路真值','同次证据对应，真值不进入控制')]
        for i,(a,b,c,d) in enumerate(levels):
            x=.52+i*4.18;box(s,x,2.27,3.96,3.34,PAPER)
            tx(s,a,x+.20,2.45,3.5,.65,36,RED,True)
            tx(s,b,x+.20,3.25,3.5,.50,23,INK,True)
            tx(s,c,x+.20,4.01,3.52,.88,17,MUTED)
            tx(s,d,x+.20,5.08,3.52,.44,12,BLUE,True)
        innovation(s,'独立、可追溯的工程验收，支撑每项结论的证据口径')
        source(s,'证据：vision_recovery_replay.json / speed_tuning_validation.json / run_acceptance.py / evaluate_run.py。')
    elif n==11:
        tx(s,'团队实现',.56,2.13,2.4,.4,17,RED,True)
        tx(s,'结构与接触',.56,2.80,2.32,.43,23,INK,True)
        tx(s,'云台、推板\n任务与安全协同',.56,3.55,2.9,.9,17,MUTED)
        ln(s,3.58,2.77,3.58,4.71)
        tx(s,'感知与标定',3.98,2.80,3.55,.43,23,INK,True)
        tx(s,'场景负例、核验与重检\n图像时刻配准、位置融合',3.98,3.55,3.72,.9,17,MUTED)
        ln(s,8.07,2.77,8.07,4.71)
        tx(s,'导航与验收',8.49,2.80,3.9,.43,23,INK,True)
        tx(s,'地图更新、阶段控制\n独立验收、连续录屏工具',8.49,3.55,3.9,.9,17,MUTED)
        box(s,.53,5.08,12.25,.65,PALE)
        tx(s,'下一步：随机初始条件重复验证  /  实际视频逐帧评估  /  接触力检测',.7,5.26,11.9,.35,17,BLUE,True,PP_ALIGN.CENTER)
        tx(s,'基础组件：ROS 2 · Gazebo · Nav2 · slam_toolbox · YOLOv5 架构思想 · OpenCV · AprilTag',.54,6.11,12.25,.44,13,MUTED,False,PP_ALIGN.CENTER)
        source(s,'团队信息：TECHNICAL_REPORT；组件归属：docs/third_party.md。个人具体分工未由材料充分证明，未编造分配。')
    elif n==12:
        # Full-frame video is embedded. Current source is left byte-for-byte intact.
        for existing in list(s.shapes):s.shapes._spTree.remove(existing._element)
        poster=GENERATED/'video_poster.jpg'
        subprocess.run(['ffmpeg','-y','-v','error','-ss','22','-i',str(video),'-frames:v','1',str(poster)],check=True)
        movie=s.shapes.add_movie(str(video),0,0,PPT.slide_width,PPT.slide_height,poster_frame_image=str(poster),mime_type='video/mp4')
        ACTIVE['video']=dict(file=str(video.relative_to(ROOT)),sha256=sha(video),duration_s=duration,has_audio=any(x['codec_type']=='audio' for x in probe['streams']))
    elif n==13:
        tx(s,'让每一个自主动作\n都有条件、有反馈、有证据',.75,1.90,11.85,2.10,41,WHITE,True,PP_ALIGN.CENTER)
        box(s,5.93,4.56,1.46,.055,RED)
        tx(s,'面向救援勘探的机构、感知与导航协同',.75,5.08,11.85,.57,22,'CCD9E7',False,PP_ALIGN.CENTER)
        tx(s,'Simulator  /  B09018834',.75,6.29,11.85,.44,17,'CCD9E7',False,PP_ALIGN.CENTER)
        tx(s,'谢谢各位老师',.75,6.89,11.85,.33,14,'CCD9E7',False,PP_ALIGN.CENTER)
    elif n==14:
        rows=[('环境与建图','15 分','自建场景、激光建图与在线留档'),('走廊识别','20 分','入室前分类与终端输出'),('入口清障','20 分','物理推箱、流畅操作及入室'),('核心标定','20 分','AprilTag 与 RViz Marker 布局对应'),('返回起点','5 分','完整返航与最终停车'),('创新答辩','20 分','机构、视觉、导航的团队改进')]
        for i,(a,b,c) in enumerate(rows):
            y=2.22+i*.57
            if i%2==0:box(s,.53,y-.04,12.26,.53,PAPER)
            tx(s,a,.70,y,2.7,.39,18,INK,True);tx(s,b,3.51,y,1.7,.39,18,RED,True);tx(s,c,5.34,y,7.2,.39,18,INK)
        tx(s,'8 分钟包含视频与讲解；项目自定厘米级门限不属于官方评分阈值。',.62,6.12,12.03,.39,16,BLUE,True)
        source(s,'依据：本地 B09 比赛规则及评审标准（2026 年 7 月），完整评分表与国赛条款。')
    elif n==15:
        rows=[('扫描与危险标识','±1.90 rad / 12 s；同目标连续 3 个关联处理帧'),('核心位置融合','至少 4 次有效观测；重投影 ≤2.5 px；不要求连续'),('接触控制','里程计推进；横偏 >0.04 m / 航向 >0.12 rad 中止'),('安全失效','激光、里程计、指令或必要 TF 失效即停车'),('地图处理','限定区内累计 3 个不同时间戳扫描的自由证据')]
        for i,(a,b) in enumerate(rows):
            y=2.25+i*.68
            tx(s,a,.67,y,3.0,.42,18,RED,True);tx(s,b,3.72,y,8.8,.54,18,INK)
            ln(s,.66,y+.58,12.62,y+.58)
        source(s,'条件来自当前 YAML、mission_node / vision_node / safety_node / navigation_map_node；均非官方规则阈值。')
    elif n==16:
        tx(s,'历史速度试验（无界面）',.60,2.21,6.6,.46,21,INK,True)
        for i,(a,b) in enumerate([('原速基准（1 次）','310.82 s'),('最终配置（2 次）','286.07 / 288.32 s'),('分档 0.24 m/s','296.84 s'),('统一 0.24 / 分档 0.30','失败候选，不计提速成绩')]):
            y=2.99+i*.61;tx(s,a,.65,y,3.8,.40,17,MUTED);tx(s,b,4.47,y,3.9,.42,18,BLUE,True)
        ln(s,8.82,2.26,8.82,5.57)
        tx(s,'模型合成验证',9.19,2.23,3.38,.43,21,INK,True)
        tx(s,'160 张',9.19,3.04,3.40,.62,34,RED,True)
        tx(s,'P 85.62%\nR 70.81%\n无目标图 2 / 59 误报',9.19,3.92,3.50,1.49,18,MUTED)
        tx(s,'历史对照与合成集指标，各有适用口径；不能替代当前视频逐帧评价。',.63,6.12,12.0,.44,16,BLUE,True)
        source(s,'来源：speed_tuning_validation.md/json、models/yolov5/hazard_yolov5.json；历史测试记录不称本次重跑。')
    elif n==17:
        for i,qa in enumerate(p['qa']):
            a,b=qa['q'],qa['a']
            y=2.18+i*.72
            tx(s,a,.65,y,3.98,.43,19,RED,True);tx(s,b,4.75,y,7.95,.52,17,INK)
            if i<4:ln(s,.65,y+.61,12.65,y+.61)
        source(s,'依据：launch、mission_node、vision_node、navigation_map_node、run_acceptance 与 evaluate_run。')
    else:
        raise ValueError(n)

def fmt(seconds):
    seconds=round(seconds); return f'{seconds//60:02d}:{seconds%60:02d}'

# Produce the script from exactly the material used for notes, once.
md=['# AVS 国赛答辩逐页讲稿\n', '更新日期：2026-10-17。正文 13 页，隐藏问答页 4 页。\n',
    '配音负责画面过程、分类名称和本次实测结果；PPT 主讲负责实际问题、对应方案、创新贡献与验证依据。本次实测数字不在 PPT 中再次汇报。视频播放时由配音讲解，现场主讲保持安静。\n',
    f'当前嵌入视频为 {duration:.3f} 秒，约 {fmt(duration)}，按实际文件统计。视频文件未改动；本轮交付的是新讲稿，现有音轨尚未按新稿重新录制。\n',
    '只朗读“现场讲述”。“讲者备注”和隐藏页用于排练及问答，不计入正文口播。时间为排练安排，正式上台需实测。\n']
clock=0
for p,sl in zip(PAGES,PPT.slides):
    backup=p.get('backup',False)
    secs=float(p.get('seconds',0))
    if p['page']==12:secs=duration+8;p['seconds']=round(secs,3)
    timing='问答备用' if backup else f'{fmt(clock)}—{fmt(clock+secs)}（{secs:.0f} 秒）'
    if not backup:clock+=secs
    block=[f"## 第{p['page']}页｜{p['title']}\n",f'排练时间：{timing}\n']
    if not backup:
        block.extend(['### 现场讲述\n',p.get('speech','')+'\n'])
    else:
        block.append('### 问答资料\n')
        for row in p.get('rows',[]):
            block.append('｜'.join(str(x) for x in row)+'\n')
        for group in p.get('tables',[]):
            block.append(group.get('title','')+'\n')
            for row in group.get('rows',[]):
                block.append('｜'.join(str(x) for x in row)+'\n')
        for qa in p.get('qa',[]):
            block.append('问：'+qa['q']+'\n\n答：'+qa['a']+'\n')
    if p.get('problem'):block.extend(['### 遇到的问题\n',p['problem']+'\n','### 对应解决方案\n',p['solution']+'\n','### 创新点\n',p['innovation']+'\n'])
    block.append('### 讲者备注\n')
    notes=p.get('notes','')
    if isinstance(notes,list):notes='\n'.join('- '+x for x in notes)
    block.append(notes+'\n')
    src=p.get('source','')
    if isinstance(src,list):src='；'.join(src)
    block.append('依据：'+src+'\n')
    sl.notes_slide.notes_text_frame.text='\n'.join(block)
    md.extend(block)
md.insert(5,f'总排练安排：**{fmt(clock)}**，包含视频、转场和各页余量；距离 8 分钟上限预留 {480-clock:.0f} 秒。\n')
mdstr='\n'.join(md)
(HERE/'AVS_国赛答辩逐页讲稿.md').write_text(mdstr)
txt=re.sub(r'(?m)^#{1,4}\s+','',mdstr);txt=txt.replace('**','')
(HERE/'AVS_国赛答辩逐页讲稿.txt').write_text(txt)
main_words=''.join(p.get('speech','') for p in PAGES if not p.get('backup'))
for forbidden in ['0.996','4.26','7.52','13.94','九十九点六','四点三厘米','七点五到十三点九']:
    assert forbidden not in mdstr, f'Video result repeated in slide script: {forbidden}'
assert clock<480, f'Pitch exceeds 8 minutes: {clock}'
PPT.save(HERE/'AVS_国赛答辩.pptx')

# Export an independent static render input: no embedded movie in the PDF.
# Hidden pages are made visible only in this temporary rendering document.
for slide in PPT.slides:
    slide._element.attrib.pop('show',None)
static_video_slide=PPT.slides[11]
for q in list(static_video_slide.shapes):static_video_slide.shapes._spTree.remove(q._element)
static_video_slide.shapes.add_picture(str(GENERATED/'video_poster.jpg'),0,0,PPT.slide_width,PPT.slide_height)
PPT.save('/tmp/avs_roadshow_static.pptx')

manifest=dict(date='2026-10-17', main_slides=13, hidden_slides=4, total_target_seconds=clock, video_duration_s=duration,
              spoken_cjk_chars=len(re.findall(r'[\u4e00-\u9fff]',main_words)), source_data='国赛答辩/roadshow_content.json', slides=MANIFEST)
(HERE/'PPT配图与版式核对.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in manifest.items() if k!='slides'},ensure_ascii=False,indent=2))
print(HERE/'AVS_国赛答辩.pptx')
