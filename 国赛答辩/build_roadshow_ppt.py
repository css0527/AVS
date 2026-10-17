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
MOTION_SHAPES = []
MOTION_DIR = HERE/'素材/动态版'
MOTION_DATA = json.loads((MOTION_DIR/'manifest.json').read_text()) if (MOTION_DIR/'manifest.json').exists() else {}

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
        tx(s,page['title'],.52,.82,12.2,.72,33,INK,True)
        ln(s,.5,6.98,12.84,6.98)
        tx(s,'SIMULATOR  /  B09018834',.52,7.13,3.25,.18,8.5,MUTED)
        tx(s,f"{page['page']:02d}" + ('  备用' if page.get('backup') else ''),11.8,7.08,1.0,.28,11,RED,True,PP_ALIGN.RIGHT)
    return s

def source(slide, value):
    # Full provenance belongs in speaker notes and the audit manifest.
    ACTIVE.setdefault('sources',[]).append(value)

def innovation(slide, value):
    box(slide,.53,6.21,12.26,.61,REDPALE)
    tx(slide,'创新',.74,6.39,.64,.24,13,RED,True)
    tx(slide,value,1.60,6.35,10.92,.39,23,INK,True)

def issue(slide, page):
    tx(slide,'问题',.58,2.11,3.0,.31,14,RED,True)
    tx(slide,page['display_problem'],.58,2.66,3.05,1.05,24,INK,True)
    ln(slide,.58,3.92,3.57,3.92)
    tx(slide,'方案 · 已实施',.58,4.18,3.0,.31,14,BLUE,True)
    tx(slide,page['display_solution'],.58,4.75,3.10,1.13,21,INK,True)
    innovation(slide,page.get('display_innovation',page['innovation']))

def motion(slide, page, x, y, w, h):
    path=MOTION_DIR/f"page{page['page']:02d}.gif"
    asset=next((a for a in MOTION_DATA.get('assets',[]) if a['page']==page['page']),{})
    if not path.exists():raise FileNotFoundError(path)
    with Image.open(path) as im:
        iw,ih=im.size; frames=im.n_frames
        duration_ms=sum(f.info.get('duration',0) for f in __import__('PIL.ImageSequence',fromlist=['Iterator']).Iterator(im))
    scale=min(w/iw,h/ih); nw,nh=iw*scale,ih*scale
    actual=[x+(w-nw)/2,y+(h-nh)/2,nw,nh]
    q=slide.shapes.add_picture(str(path),*(Inches(v) for v in actual))
    poster=path.with_name(path.stem+'_poster.png')
    if not poster.exists():
        poster=path.with_suffix('.png')
    if not poster.exists():raise FileNotFoundError(f'Static poster for {path}')
    MOTION_SHAPES.append((slide,q,poster))
    provenance=asset.get('sources',[])
    ACTIVE['images'].append(dict(file=str(path.relative_to(ROOT)),source=provenance[0]['file'] if provenance else page.get('motion_asset',''),sources=provenance,kind=asset.get('kind'),clip_start_seconds=asset.get('clip_start_seconds'),sha256=sha(path),meaning=page.get('visual',''),box_inches=actual,animated=True,frames=frames,duration_ms=duration_ms,poster=str(poster.relative_to(ROOT))))
    assert frames>1,f'Animation has only one frame: {path}'
    return q

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
audio_check=HERE/'配音制作/音画核对.json'
audio_data=json.loads(audio_check.read_text()) if audio_check.exists() else {}
ai_audio_done=audio_data.get('status')=='complete' and audio_data.get('video_sha256')==sha(video)
audio_delivery=('已替换为按画面分段对齐的普通话 AI 女声，移除原有人声，不添加字幕。'
                if ai_audio_done else '新配音制作状态以配音制作/音画核对.json 为准。')

for p in PAGES:
    n=p['page']; layout=p['layout']
    s=header(p,dark=layout in ('cover','closing'))
    if layout=='cover':
        tx(s,'第十九届先进机器人及仿真技术大赛',.62,.52,11.8,.35,14,'B9CADC')
        tx(s,'救援无人车\n仿真系统',.60,1.67,5.15,1.95,45,WHITE,True)
        tx(s,'已完成自主任务闭环',.64,4.04,5.10,.55,24,'DEE8F3',True)
        motion(s,p,5.83,1.57,6.95,4.30)
        tx(s,'Simulator  /  B09018834',.64,5.45,5.25,.45,20,WHITE,True)
        tx(s,'队长 陈莎莎  ·  队员 梁辰瑜、赖丽燕、初冉\n指导教师 蒋玉莲、王俊',.64,6.26,11.9,.62,13,'B9CADC')
    elif layout=='completion':
        motion(s,p,4.57,1.82,8.22,4.45)
        for i,label in enumerate(p['display_items']):
            y=2.05+i*1.02
            tx(s,'✓',.62,y,.48,.47,28,TEAL,True)
            tx(s,label,1.25,y+.03,3.05,.45,25,INK,True)
        box(s,.60,6.36,12.10,.43,PALE)
        tx(s,'已完成 · 已验收 · 可复现',.81,6.42,11.7,.32,21,BLUE,True,PP_ALIGN.CENTER)
    elif layout=='video':
        for q in list(s.shapes):s.shapes._spTree.remove(q._element)
        ACTIVE['texts']=[]
        poster=GENERATED/'video_poster.jpg'
        subprocess.run(['ffmpeg','-y','-v','error','-ss','22','-i',str(video),'-frames:v','1',str(poster)],check=True)
        s.shapes.add_movie(str(video),0,0,PPT.slide_width,PPT.slide_height,poster_frame_image=str(poster),mime_type='video/mp4')
        ACTIVE['video']=dict(file=str(video.relative_to(ROOT)),sha256=sha(video),duration_s=duration,has_audio=any(x['codec_type']=='audio' for x in probe['streams']))
    elif layout=='scene':
        motion(s,p,4.39,1.79,8.42,4.82)
        labels=[('观察','短时可见 → 可靠确认'),('接触','正面推箱 → 整车保护'),('标注','相机运动 → 姿态配准'),('通行','场景变化 → 地图一致')]
        for i,(a,b) in enumerate(labels):
            y=2.07+i*1.08
            tx(s,a,.60,y,3.4,.33,14,RED,True)
            tx(s,b,.60,y+.42,3.65,.42,21,INK,True)
    elif layout=='mapping':
        motion(s,p,.80,1.66,11.75,4.84)
    elif layout in ('innov1','innov2','innov3','innov4','innov5','innov6'):
        issue(s,p)
        motion(s,p,4.03,1.85,8.76,4.20)
    elif layout=='evidence':
        motion(s,p,.80,1.71,11.75,4.60)
        tx(s,'已知场地仿真闭环  ·  真值仅用于旁路验收',.64,6.40,12.0,.38,21,BLUE,True,PP_ALIGN.CENTER)
    elif layout=='team':
        motion(s,p,.80,1.65,11.75,4.60)
        tx(s,'已交付：场景机构 · 感知控制 · 独立验收',.66,6.30,12.0,.40,22,INK,True,PP_ALIGN.CENTER)
        tx(s,'基础组件：ROS 2 / Gazebo / Nav2 / OpenCV / AprilTag；具体归属见讲者备注',.66,6.78,12.0,.21,10,MUTED,False,PP_ALIGN.CENTER)
    elif layout=='closing':
        tx(s,'自主动作\n有条件 · 有反馈 · 有证据',.80,2.01,11.73,1.76,40,WHITE,True,PP_ALIGN.CENTER)
        box(s,5.93,4.45,1.46,.055,RED)
        tx(s,'救援无人车仿真系统',.80,5.08,11.73,.48,24,'DEE8F3',True,PP_ALIGN.CENTER)
        tx(s,'Simulator  /  B09018834',.80,6.13,11.73,.42,18,'B9CADC',False,PP_ALIGN.CENTER)
        tx(s,'谢谢各位老师',.80,6.84,11.73,.30,16,'B9CADC',False,PP_ALIGN.CENTER)
    elif layout=='backup_rules':
        rows=[('环境与建图','15','场景与地图'),('走廊识别','20','分类与终端输出'),('入口清障','20','物理推箱与入室'),('核心标定','20','识别与地图 Marker'),('返回起点','5','返航与停车'),('创新答辩','20','问题、方案与创新')]
        for i,(label,score,evidence) in enumerate(rows):
            x=.62+(i%2)*6.24;y=2.00+(i//2)*1.44
            box(s,x,y,5.86,1.14,PAPER)
            tx(s,score,x+.20,y+.21,1.0,.56,33,RED,True)
            tx(s,label,x+1.47,y+.18,4.1,.39,23,INK,True)
            tx(s,evidence,x+1.47,y+.69,4.1,.32,17,MUTED)
        tx(s,'国赛 8 分钟：视频＋方案讲解',.67,6.62,12,.32,19,BLUE,True,PP_ALIGN.CENTER)
    elif layout=='backup_params':
        rows=[('云台扫描','±1.90 rad / 12 s'),('危险确认','连续 3 个关联处理帧'),('标记融合','≥4 次；重投影 ≤2.5 px'),('推进中止','横偏 >0.04 m / 航向 >0.12 rad'),('地图自由证据','3 个不同时间戳扫描')]
        for i,(a,b) in enumerate(rows):
            y=2.03+i*.84
            tx(s,a,.72,y,3.35,.42,22,RED,True)
            tx(s,b,4.19,y,8.2,.48,25,INK,True)
            if i<4:ln(s,.72,y+.62,12.5,y+.62)
        tx(s,'当前场地配置；传感器或必要 TF 失效即停车',.72,6.58,11.9,.37,19,BLUE,True,PP_ALIGN.CENTER)
    elif layout=='backup_metrics':
        for x,label in [(.64,'历史无界面任务'),(7.07,'模型合成验证')]:
            box(s,x,2.08,5.61,3.97,PAPER)
            tx(s,label,x+.24,2.35,5.1,.42,24,INK,True)
        tx(s,'310.82 → 287.20 s',.90,3.17,5.05,.68,29,BLUE,True)
        tx(s,'平均耗时 ↓7.6%',.90,4.10,5.0,.59,29,RED,True)
        tx(s,'基准 1 次 / 最终 2 次',.90,5.21,5.0,.35,19,MUTED)
        tx(s,'160 张',7.34,3.12,4.95,.68,35,RED,True)
        tx(s,'P 85.62% / R 70.81%',7.34,4.13,4.95,.50,24,BLUE,True)
        tx(s,'无目标图：2 / 59 误报',7.34,5.21,4.95,.35,19,MUTED)
        tx(s,'各自口径独立，不替代当前视频的逐帧评价',.67,6.55,12.0,.37,20,BLUE,True,PP_ALIGN.CENTER)
    elif layout=='backup_qa':
        rows=[('导航','目标点与条件＋Nav2 规划'),('接触','阶段＋已知位置＋几何窗口'),('地图','限定区配置；派生导航图'),('误差','同次 map←odom 统一坐标'),('验证','已知场地仿真；旁路真值验收')]
        for i,(a,b) in enumerate(rows):
            y=2.06+i*.87
            tx(s,a,.74,y,2.4,.45,24,RED,True)
            tx(s,b,3.45,y,9.05,.51,25,INK,True)
            if i<4:ln(s,.74,y+.65,12.5,y+.65)
    else:
        raise ValueError(layout)


def fmt(seconds):
    seconds=round(seconds); return f'{seconds//60:02d}:{seconds%60:02d}'

# Produce the script from exactly the material used for notes, once.
md=['# AVS 国赛答辩逐页讲稿\n', '更新日期：2026-10-17。正文 14 页，隐藏问答页 4 页。\n',
    '配音负责画面过程、分类名称和本次实测结果；PPT 主讲负责实际问题、对应方案、创新贡献与验证依据。本次实测数字不在 PPT 中再次汇报。视频播放时由配音讲解，现场主讲保持安静。\n',
    f'当前嵌入视频为 {duration:.3f} 秒，约 {fmt(duration)}，按实际文件统计。{audio_delivery}\n',
    '只朗读“现场讲述”。“讲者备注”和隐藏页用于排练及问答，不计入正文口播。时间为排练安排，正式上台需实测。\n']
clock=0
for p,sl in zip(PAGES,PPT.slides):
    backup=p.get('backup',False)
    secs=float(p.get('seconds',0))
    if p.get('layout')=='video':secs=duration+8;p['seconds']=round(secs,3)
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
# PDF uses a deliberate representative frame; the delivered PPT keeps GIF bytes.
for slide,shape,poster in MOTION_SHAPES:
    parent=slide.shapes._spTree
    index=list(parent).index(shape._element)
    coords=(shape.left,shape.top,shape.width,shape.height)
    old_rid=shape._element.blipFill.blip.rEmbed
    parent.remove(shape._element)
    slide.part.drop_rel(old_rid)
    replacement=slide.shapes.add_picture(str(poster),*coords)
    parent.remove(replacement._element)
    parent.insert(index,replacement._element)
for slide in PPT.slides:
    slide._element.attrib.pop('show',None)
static_video_slide=PPT.slides[2]
for q in list(static_video_slide.shapes):static_video_slide.shapes._spTree.remove(q._element)
for rid,relation in list(static_video_slide.part.rels.items()):
    if relation.reltype.rsplit('/',1)[-1] in ('video','media','image'):
        static_video_slide.part.drop_rel(rid)
static_video_slide.shapes.add_picture(str(GENERATED/'video_poster.jpg'),0,0,PPT.slide_width,PPT.slide_height)
PPT.save('/tmp/avs_roadshow_static.pptx')

manifest=dict(date='2026-10-17', main_slides=14, hidden_slides=4, total_target_seconds=clock, video_duration_s=duration,
              spoken_cjk_chars=len(re.findall(r'[\u4e00-\u9fff]',main_words)), animated_pages=[x['page'] for x in MANIFEST if any(i.get('animated') for i in x['images'])], source_data='国赛答辩/roadshow_content.json', slides=MANIFEST)
(HERE/'PPT配图与版式核对.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in manifest.items() if k!='slides'},ensure_ascii=False,indent=2))
print(HERE/'AVS_国赛答辩.pptx')
