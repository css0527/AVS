#!/usr/bin/env python3
"""Build truthful, compact looping illustrations for the competition deck.

Real footage is only cropped and sampled; schematics are explicitly labelled.
The source video, source PGM, and recovery comparison are never modified.
Each GIF has a complete poster, and the manifest distinguishes recorded
evidence from animated explanations. No speech, subtitle, or network operation.
"""
from pathlib import Path
import sys, json, math, hashlib, subprocess, tempfile, argparse
sys.path.insert(0, '/tmp/avs_ppt_deps')
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / '素材/动态版'
VIDEO = HERE / 'B09018834.mp4'
RECOVERY = ROOT / '创新点PPT/素材/新版/vision/recovery_same_frame_verified.png'
MAP = ROOT / 'avs_ws/src/avs_rescue_sim/maps/rescue_map.pgm'
MAP_CFG = ROOT / 'avs_ws/src/avs_rescue_sim/config/navigation_map.yaml'
SPEED = ROOT / 'avs_ws/docs/speed_tuning_validation.json'
REGULAR = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
BOLD = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
W, H, FPS = 960, 560, 8
NAVY, INK, RED, BLUE = '#102D4C', '#18334F', '#CE3E38', '#296497'
MUTED, LINE, PAPER, WHITE = '#647386', '#DDE4EC', '#F5F7FA', '#FFFFFF'
TEAL, PALE, REDPALE = '#1B7C7A', '#EAF0F7', '#FCEFEB'
MANIFEST = []
TEXTS = {
    1:['当前系统实录','场景与车辆均来自连续运行录屏','原成片 2×'],
    2:['闭环任务已完成','当前任务实录','原成片 2×','场景与地图同帧'],
    4:['真实场景中的工程问题','当前任务实录','侧墙、入口与核心区','原成片 2×'],
    5:['六项机制协同','可信观测','受控行动','主动观察','可靠辨认','受控接触','时空一致','地图一致','分层调度','工程机制示意'],
    6:['主动扫描','当前车载相机实录','保留实际检测框及漏检画面','原成片 2×'],
    7:['同帧离线回放','原链：未检出','恢复链：已检出','候选','图案 / 几何','局部重检','同一输入帧','保留原核对图的检测结果'],
    8:['受控接触','推障实录','实际车头与箱体接触推进','原成片 2×'],
    9:['时间配准机制示意','拍摄 t0','处理 t1','绑定 t0 姿态','camera','base','odom','map','t_image = t_TF','图像测量与拍摄时刻的实际姿态配对'],
    10:['处理机制示意','限定区域','不同扫描的自由证据','1','2','3','满足 3 次后局部清除','原图保留','实时障碍仍检测','真实 PGM 底图','配置允许区','不代表逐格实测更新'],
    11:['历史无界面对照','−7.6%','任务用时','分层调度','通行效率与末端精度协调','基准','最终均值','310.82 s','287.20 s','1 次基准 / 2 次最终','同一计时口径'],
    12:['已形成可追溯证据链','源文件','构建','运行','验收','代码 / 配置','哈希 / 日志','录屏 / 评估','证据关系示意'],
    13:['三类成果均已完成','仿真系统','连续运行','追溯交付','代码 + 场景','录屏 + 事件','配置 + 验收','成果结构示意'],
}

def font(size=28, bold=False):
    return ImageFont.truetype(BOLD if bold else REGULAR, size)

def text(im, xy, value, size=28, fill=INK, bold=False, anchor=None):
    ImageDraw.Draw(im).text(xy, value, font=font(size,bold), fill=fill, anchor=anchor,
                           spacing=8)

def center(im, xy, value, size=28, fill=INK, bold=False):
    text(im,xy,value,size,fill,bold,'mm')

def rounded(im, bounds, fill=WHITE, outline=None, width=2, radius=20):
    ImageDraw.Draw(im).rounded_rectangle(bounds, radius, fill, outline, width)

def arrow(im, p, q, color=BLUE, width=4):
    d=ImageDraw.Draw(im); d.line([p,q],fill=color,width=width)
    ang=math.atan2(q[1]-p[1],q[0]-p[0]); size=11
    a=(q[0]-size*math.cos(ang-.55),q[1]-size*math.sin(ang-.55))
    b=(q[0]-size*math.cos(ang+.55),q[1]-size*math.sin(ang+.55))
    d.polygon([q,a,b],fill=color)

def canvas(label, note='', dark=False):
    im=Image.new('RGB',(W,H),NAVY if dark else PAPER)
    text(im,(26,16),label,22,WHITE if dark else BLUE,True)
    if note:text(im,(26,526),note,19,'#C6D3DF' if dark else MUTED)
    return im

def fit(im, region):
    x,y,w,h=region
    factor=min(w/im.width,h/im.height)
    return im.resize((round(im.width*factor),round(im.height*factor)),Image.Resampling.LANCZOS)

def paste_fit(bg, source, region):
    x,y,w,h=region; im=fit(source,region)
    bg.paste(im,(x+(w-im.width)//2,y+(h-im.height)//2))

def rel(path):return str(Path(path).relative_to(ROOT))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(page, frames, kind, source, description, poster_index=0, extra=None):
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/f'page{page:02d}.gif'; poster=OUT/f'page{page:02d}_poster.png'
    poster_tmp=poster.with_name('.'+poster.stem+'.building.png')
    frames[poster_index].save(poster_tmp);poster_tmp.replace(poster)
    # An independent adaptive palette avoids introducing false image colours.
    paletteframes=[f.quantize(colors=128 if page==8 else 192,method=Image.Quantize.MEDIANCUT,
                             dither=Image.Dither.NONE) for f in frames]
    # GIF has a 10 ms time unit: alternate 120/130 ms instead of truncating
    # 125 ms to 120 ms, keeping a sampled clip's true playback duration.
    durations=[120 if i%2==0 else 130 for i in range(len(frames))]
    gif_tmp=target.with_name('.'+target.stem+'.building.gif')
    paletteframes[0].save(gif_tmp,save_all=True,append_images=paletteframes[1:],
        duration=durations,loop=0,optimize=True,disposal=2)
    with Image.open(gif_tmp) as verify:
        actual_ms=0
        encoded_frames=verify.n_frames
        for idx in range(verify.n_frames):
            verify.seek(idx);actual_ms+=verify.info['duration']
    gif_tmp.replace(target)
    sources=[source] if isinstance(source,(Path,str)) else source
    record=dict(page=page,gif=rel(target),poster=rel(poster),dimensions=[W,H],
        fps=FPS,frames=encoded_frames,sampled_frames=len(frames),duration_seconds=actual_ms/1000,
        frame_duration_ms='alternating 120 / 130',
        loop='infinite',kind=kind,description=description,
        sources=[dict(file=rel(p),sha256=sha(p)) for p in sources],
        bytes=target.stat().st_size,sha256=sha(target),poster_sha256=sha(poster))
    if extra:record.update(extra)
    record.update(file=record['gif'],source=[rel(p) for p in sources],texts=TEXTS[page],
        source_time=dict(start_seconds=record.get('clip_start_seconds'),
                         duration_seconds=record.get('clip_duration_seconds')))
    MANIFEST.append(record)
    print(f'page{page:02d}: {len(frames)} frames, {target.stat().st_size/1024**2:.2f} MiB',flush=True)
    if target.stat().st_size>5*1024*1024:raise RuntimeError(f'{target} exceeds 5 MiB')

def clip(start,duration,crop):
    x1,y1,x2,y2=crop
    # PNG extraction maintains the original measurements and detection boxes.
    with tempfile.TemporaryDirectory(prefix='avs_motion_') as tmp:
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(VIDEO),
             '-t',str(duration),'-vf',f'crop={x2-x1}:{y2-y1}:{x1}:{y1},fps={FPS}',
             '-an',str(Path(tmp)/'%04d.png')]
        subprocess.run(cmd,check=True)
        return [Image.open(p).convert('RGB') for p in sorted(Path(tmp).glob('*.png'))]

SCENE=(280,136,1120,606)
CAMERA=(10,704,530,1048)
RVIZ=(1174,136,1884,628)

def recorded(page,start,duration,crop,label,note):
    raw=clip(start,duration,crop); frames=[]
    for pic in raw:
        im=canvas(label,note)
        rounded(im,(16,57,944,511),WHITE)
        paste_fit(im,pic,(22,63,916,442))
        frames.append(im)
    save(page,frames,'recorded_video',VIDEO,
        '原连续录屏裁剪与8 fps采样；保持画面原有运动速度、检测框及目标，不添加检测结果。',
        poster_index=min(len(frames)-1,len(frames)//2),
        extra=dict(clip_start_seconds=start,clip_duration_seconds=duration,crop_xyxy=list(crop),
                   source_playback='原成片已标2倍播放；此处没有追加倍速'))

def page2():
    scene=clip(155.5,6,SCENE); rviz=clip(155.5,6,RVIZ);frames=[]
    for i,pic in enumerate(scene):
        im=canvas('闭环任务已完成','当前任务实录  ·  原成片 2×  ·  场景与地图同帧')
        rounded(im,(16,64,584,504),WHITE);rounded(im,(598,64,944,504),WHITE)
        paste_fit(im,pic,(22,70,556,426));paste_fit(im,rviz[i],(604,70,334,426))
        frames.append(im)
    save(2,frames,'recorded_video',VIDEO,'返航末段的场景与RViz同帧并列；不绘制额外完成标志。',
         poster_index=len(frames)-1,extra=dict(clip_start_seconds=155.5,clip_duration_seconds=6,
            crops_xyxy=[list(SCENE),list(RVIZ)],source_playback='原成片2倍播放，未追加倍速'))

def tiny_icon(im, cx, cy, kind, color=BLUE):
    d=ImageDraw.Draw(im)
    if kind=='scan':
        d.rounded_rectangle((cx-26,cy-18,cx+25,cy+19),8,outline=color,width=4)
        d.polygon([(cx+25,cy-11),(cx+42,cy-23),(cx+42,cy+23),(cx+25,cy+11)],outline=color,width=4)
        d.arc((cx-54,cy-49,cx+54,cy+49),215,325,fill=color,width=3)
    elif kind=='check':
        d.ellipse((cx-32,cy-32,cx+32,cy+32),outline=color,width=4)
        d.line([(cx-17,cy),(cx-4,cy+12),(cx+20,cy-14)],fill=color,width=5)
    elif kind=='push':
        d.rounded_rectangle((cx-28,cy-22,cx+18,cy+24),6,outline=color,width=4)
        d.line([(cx+21,cy-26),(cx+35,cy),(cx+21,cy+28)],fill=color,width=5)
        d.rectangle((cx+43,cy-16,cx+63,cy+16),outline=RED,width=3)
    elif kind=='clock':
        d.ellipse((cx-32,cy-32,cx+32,cy+32),outline=color,width=4)
        d.line([(cx,cy-22),(cx,cy),(cx+18,cy+11)],fill=color,width=4)
    elif kind=='map':
        d.line([(cx-40,cy+26),(cx-40,cy-25),(cx-9,cy-13),(cx+14,cy-27),(cx+40,cy-12),(cx+40,cy+34),(cx+13,cy+18),(cx-9,cy+33),(cx-40,cy+26)],fill=color,width=4)
        d.line([(cx-9,cy-13),(cx-9,cy+33)],fill=color,width=3)
        d.line([(cx+14,cy-27),(cx+13,cy+18)],fill=color,width=3)
    elif kind=='speed':
        d.arc((cx-38,cy-34,cx+38,cy+42),180,360,fill=color,width=4)
        d.line([(cx,cy+6),(cx+24,cy-18)],fill=color,width=5)
        d.ellipse((cx-5,cy+1,cx+5,cy+11),fill=color)
    elif kind=='file':
        d.rounded_rectangle((cx-29,cy-36,cx+29,cy+36),6,outline=color,width=4)
        for y in (-15,0,15):d.line([(cx-17,cy+y),(cx+17,cy+y)],fill=color,width=3)
    elif kind=='computer':
        d.rounded_rectangle((cx-44,cy-31,cx+44,cy+21),7,outline=color,width=4)
        d.line([(cx,cy+21),(cx,cy+36)],fill=color,width=4)
        d.line([(cx-27,cy+37),(cx+27,cy+37)],fill=color,width=4)
    elif kind=='play':
        d.rounded_rectangle((cx-41,cy-31,cx+41,cy+31),7,outline=color,width=4)
        d.polygon([(cx-9,cy-17),(cx-9,cy+17),(cx+18,cy)],fill=color)

def page5():
    labels=['主动观察','可靠辨认','受控接触','时空一致','地图一致','分层调度']
    icons=['scan','check','push','clock','map','speed'];frames=[]
    for frame in range(48):
        im=canvas('六项机制协同','工程机制示意')
        center(im,(480,75),'可信观测  ·  受控行动',30,INK,True)
        for k,label in enumerate(labels):
            row,col=divmod(k,3);x=27+col*313;y=118+row*191
            active=frame//8==k
            rounded(im,(x,y,x+280,y+161),WHITE,RED if active else LINE,4 if active else 2)
            tiny_icon(im,x+140,y+52,icons[k],RED if active else BLUE)
            center(im,(x+140,y+119),label,30,INK,True)
            if active:
                progress=(frame%8+1)/8
                ImageDraw.Draw(im).line((x+38,y+146,x+38+204*progress,y+146),fill=RED,width=4)
            if col<2:arrow(im,(x+286,y+82),(x+307,y+82),RED if active else BLUE,3)
        frames.append(im)
    save(5,frames,'labelled_mechanism',[ROOT/'avs_ws/submission/B09018834/avs_ws/TECHNICAL_REPORT.md'],
         '六项已实现工程机制的关系示意；逐项强调不代表新增试验或性能测量。')

def page7():
    original=Image.open(RECOVERY).convert('RGB')
    left=original.crop((20,65,660,515));right=original.crop((700,65,1340,515))
    frames=[]
    for i in range(48):
        im=canvas('同帧离线回放','同一输入帧  ·  保留原核对图的检测结果')
        rounded(im,(16,63,469,430),WHITE,RED if i<24 else LINE,3)
        rounded(im,(491,63,944,430),WHITE,TEAL if i>=24 else LINE,3)
        center(im,(242,89),'原链：未检出',25,INK,True)
        center(im,(718,89),'恢复链：已检出',25,TEAL,True)
        paste_fit(im,left,(27,116,431,303));paste_fit(im,right,(502,116,431,303))
        labels=['候选','图案 / 几何','局部重检']
        for k,label in enumerate(labels):
            x=102+k*294
            rounded(im,(x,448,x+170,500),PALE,TEAL if (i//8)%3==k else None,3,12)
            center(im,(x+85,473),label,23,INK,True)
            if k<2:arrow(im,(x+185,474),(x+274,474),BLUE,3)
        frames.append(im)
    save(7,frames,'same_frame_offline_replay',RECOVERY,
         '左右原图固定不变，动画只强调核验链与对照侧；不是新录制实时检测，也不是整段逐帧准确率对照。',
         poster_index=30,extra=dict(derived_image_crop_xyxy=[[20,65,660,515],[700,65,1340,515]]))

def camera_shape(im,cx,cy,angle=0,fill=BLUE):
    points=[(-38,-22),(20,-22),(20,-13),(43,-27),(43,27),(20,13),(20,22),(-38,22)]
    ca,sa=math.cos(angle),math.sin(angle)
    q=[(cx+x*ca-y*sa,cy+x*sa+y*ca) for x,y in points]
    ImageDraw.Draw(im).polygon(q,fill=fill)
    ImageDraw.Draw(im).ellipse((cx-13,cy-13,cx+13,cy+13),fill=WHITE)

def page9():
    frames=[]
    for i in range(56):
        im=canvas('时间配准机制示意','图像测量与拍摄时刻的实际姿态配对')
        d=ImageDraw.Draw(im)
        rounded(im,(38,81,432,280),WHITE);rounded(im,(528,81,922,280),WHITE)
        center(im,(235,114),'拍摄  t0',29,BLUE,True)
        center(im,(725,114),'处理  t1',29,MUTED,True)
        camera_shape(im,235,198,-.23,BLUE)
        # Camera rotation is a schematic, never presented as telemetry.
        camera_shape(im,725,198,-.23+.75*(.5+.5*math.sin(i/56*2*math.pi)),MUTED)
        arrow(im,(451,182),(508,182),MUTED)
        center(im,(480,306),'绑定 t0 姿态',30,TEAL,True)
        nodes=[('camera',145),('base',367),('odom',589),('map',811)]
        phase=(i/56*3)%3
        for k,(name,cx) in enumerate(nodes):
            rounded(im,(cx-89,362,cx+89,447),WHITE,TEAL,2,15)
            center(im,(cx,404),name,28,INK,True)
            if k<3:
                arrow(im,(cx+98,405),(cx+123,405),TEAL,3)
                if k<=phase<k+1:
                    x=cx+98+25*(phase-k);d.ellipse((x-7,398,x+7,412),fill=RED)
        # A line explicitly binds the capture timestamp to the transform chain.
        d.line([(235,265),(235,326),(145,326),(145,353)],fill=TEAL,width=3)
        center(im,(480,489),'t_image = t_TF',30,TEAL,True)
        frames.append(im)
    save(9,frames,'labelled_mechanism',ROOT/'avs_ws/src/avs_rescue_sim/avs_rescue_sim/vision_node.py',
         '动云台拍摄与处理时刻不同的原理示意，t0图像仅绑定t0 TF；不使用伪造定位误差或运动遥测。',poster_index=14)

def page10():
    source=Image.open(MAP).convert('RGB')
    # PGM rows run downward, map y upward. This is the saved map's real YAML.
    origin=(-.104,-.0121);resolution=.02
    placement=(32,73,432,427)
    scaled=source.resize((432,427),Image.Resampling.NEAREST)
    def world(x,y):
        return (32+(x-origin[0])/resolution/source.width*432,
                73+(source.height-(y-origin[1])/resolution)/source.height*427)
    regions=[(1.18,.70,1.72,1.70),(1.30,2.00,1.42,2.11)]
    frames=[]
    for i in range(56):
        im=canvas('处理机制示意','真实 PGM 底图  ·  配置允许区  ·  不代表逐格实测更新')
        im.paste(scaled,(32,73));d=ImageDraw.Draw(im)
        overlay=Image.new('RGBA',(W,H),(0,0,0,0));od=ImageDraw.Draw(overlay)
        for x1,y1,x2,y2 in regions:
            a=world(x1,y2);b=world(x2,y1)
            od.rectangle((a,b),fill=(27,124,122,54),outline=(27,124,122,255),width=3)
        im=Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB');d=ImageDraw.Draw(im)
        center(im,(716,101),'限定区域',30,TEAL,True)
        center(im,(716,150),'不同扫描的自由证据',27,INK,True)
        active=(i//12)%3
        for k in range(3):
            cx=584+132*k
            rounded(im,(cx-47,197,cx+47,280),TEAL if k<=active else PALE,None,2,16)
            center(im,(cx,236),str(k+1),40,WHITE if k<=active else MUTED,True)
            if k<2:arrow(im,(cx+56,239),(cx+76,239),BLUE,3)
        arrow(im,(716,297),(716,333),TEAL,4)
        rounded(im,(546,351,886,413),WHITE,TEAL,2,16)
        center(im,(716,382),'满足 3 次后局部清除',26,TEAL,True)
        center(im,(716,467),'原图保留  ·  实时障碍仍检测',23,INK,True)
        # Moving ray is clearly in the schematic half, not on the real map.
        ax=541+((i%12)/11)*343
        d.line([(ax,315),(min(ax+35,903),315)],fill=RED,width=4)
        frames.append(im)
    save(10,frames,'real_map_plus_labelled_mechanism',[MAP,MAP.with_suffix('.yaml'),MAP_CFG,
            ROOT/'avs_ws/src/avs_rescue_sim/avs_rescue_sim/navigation_map_node.py'],
         '真实PGM保持不变，只按原地图分辨率、原点和y翻转投影配置允许区。右侧为三次不同扫描自由证据的处理机制示意，不伪造同次逐格更新前后图。',
         poster_index=35,extra=dict(map_resolution_m=.02,map_origin_xy=list(origin),
            map_allowed_regions_xyxy=regions,underlying_original_map_unchanged=True))

def page11():
    data=json.loads(SPEED.read_text());values=[data['baseline_navigation_to_complete_wall_s'],
        data['selected_mean_navigation_to_complete_wall_s']]
    frames=[]
    for i in range(56):
        # Start with complete final data, then reveal the bars and hold final.
        progress=1.0 if i<8 or i>=40 else min(1.,(i-8)/27)
        im=canvas('历史无界面对照','1 次基准 / 2 次最终  ·  同一计时口径')
        center(im,(745,153),'−7.6%',68,RED,True)
        center(im,(745,218),'任务用时',26,INK,True)
        labels=['基准','最终均值'];colors=[BLUE,TEAL]
        for k,v in enumerate(values):
            y=302+k*104
            text(im,(35,y-5),labels[k],27,INK,True)
            x=182;barw=v/330*552
            rounded(im,(x,y,x+552,y+51),PALE,None,2,13)
            if progress>0:rounded(im,(x,y,x+max(13,barw*progress),y+51),colors[k],None,2,13)
            text(im,(754,y+5),f'{v:.2f} s',29,colors[k],True)
        center(im,(353,158),'分层调度',39,INK,True)
        center(im,(353,219),'通行效率与末端精度协调',25,BLUE,True)
        frames.append(im)
    save(11,frames,'historical_measurement_animation',SPEED,
         '读取历史无界面基准310.82s与最终两次均值287.20s，静态数字始终可见；动画仅呈现条形长度，不暗示本次录屏加速或新增统计。',
         poster_index=0,extra=dict(baseline_runs=1,selected_runs=2,
             baseline_seconds=values[0],selected_mean_seconds=values[1],
             reduction_percent=data['task_time_reduction_percent']))

def page12():
    labels=['源文件','构建','运行','验收'];icons=['file','computer','play','check'];frames=[]
    for i in range(56):
        im=canvas('已形成可追溯证据链','证据关系示意')
        for k,label in enumerate(labels):
            x=24+k*235
            rounded(im,(x,132,x+203,349),WHITE,TEAL if i//14==k else LINE,3)
            tiny_icon(im,x+101,205,icons[k],TEAL if i//14==k else BLUE)
            center(im,(x+101,291),label,31,INK,True)
            if k<3:arrow(im,(x+209,241),(x+229,241),BLUE,3)
        phase=(i/56)*3
        d=ImageDraw.Draw(im)
        d.line((125,374,830,374),fill=LINE,width=3)
        dotx=125+705*(i/55)
        d.ellipse((dotx-7,367,dotx+7,381),fill=TEAL)
        for k in range(3):
            if k<=phase<k+1:
                x=24+k*235+210+19*(phase-k)
                d.ellipse((x-6,235,x+6,247),fill=RED)
        rounded(im,(71,401,889,478),PALE,None,2,15)
        center(im,(480,440),'代码 / 配置  →  哈希 / 日志  →  录屏 / 评估',27,INK,True)
        frames.append(im)
    save(12,frames,'labelled_evidence_relationship',[
            ROOT/'avs_ws/acceptance/recording_submission_20261013_gimbal_run2/evidence/evaluation.json',
            ROOT/'avs_ws/submission/B09018834/avs_ws/TECHNICAL_REPORT.md'],
         '已有源码、构建、运行与验收证据的关系示意；不表示自动化平台或新增试验。',poster_index=45)

def page13():
    labels=['仿真系统','连续运行','追溯交付'];icons=['computer','play','file']
    subs=['代码 + 场景','录屏 + 事件','配置 + 验收'];frames=[]
    for i in range(48):
        im=canvas('三类成果均已完成','成果结构示意')
        for k,label in enumerate(labels):
            x=28+k*313;active=i//16==k
            rounded(im,(x,111,x+279,453),WHITE,TEAL if active else LINE,3)
            tiny_icon(im,x+139,195,icons[k],TEAL if active else BLUE)
            center(im,(x+139,291),label,33,INK,True)
            center(im,(x+139,355),subs[k],25,BLUE,False)
            # A quiet progress line emphasizes each complete artefact in turn.
            ImageDraw.Draw(im).line((x+64,415,x+215,415),fill=LINE,width=5)
            if active:
                progress=(i%16+1)/16
                ImageDraw.Draw(im).line((x+64,415,x+64+151*progress,415),fill=TEAL,width=5)
        frames.append(im)
    save(13,frames,'labelled_deliverables',ROOT/'avs_ws/submission/B09018834/avs_ws/TECHNICAL_REPORT.md',
         '三个已完成交付类别的结构示意，不新增个人分工、论文、专利或实车验证。',poster_index=32)

def main():
    p=argparse.ArgumentParser();p.add_argument('--pages',nargs='*',type=int)
    args=p.parse_args();selected=set(args.pages) if args.pages else None
    jobs={
        1:lambda:recorded(1,25,6,SCENE,'当前系统实录','场景与车辆均来自连续运行录屏  ·  原成片 2×'),
        2:page2,
        4:lambda:recorded(4,44,6,SCENE,'真实场景中的工程问题','当前任务实录  ·  侧墙、入口与核心区  ·  原成片 2×'),
        5:page5,
        6:lambda:recorded(6,12,8,CAMERA,'主动扫描 · 当前车载相机实录','保留实际检测框及漏检画面  ·  原成片 2×'),
        7:page7,
        8:lambda:recorded(8,48.5,9.5,SCENE,'受控接触 · 推障实录','实际车头与箱体接触推进  ·  原成片 2×'),
        9:page9,10:page10,11:page11,12:page12,13:page13}
    for page,job in jobs.items():
        if selected is None or page in selected:job()
    mp=OUT/'manifest.json'
    if selected and mp.exists():
        old=json.loads(mp.read_text()).get('assets',[])
        MANIFEST.extend([x for x in old if x['page'] not in selected])
    obj=dict(version='2026-10-17_compact_motion',generator=rel(Path(__file__)),
        rules=['原视频只裁剪采样，不生成检测框或重做运动',
            '示意图标注用途，不冒充实测对照', 'GIF无音频；PPT完整视频保留正式配音',
            '静态PDF使用完整poster；演示模式播放无限循环GIF'],
        assets=sorted(MANIFEST,key=lambda x:x['page']))
    mp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
