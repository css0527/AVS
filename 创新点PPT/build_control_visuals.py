"""Draw source-backed engineering diagrams and measured charts for the deck."""
from pathlib import Path
import json
import math
import os
import xml.etree.ElementTree as ET

os.environ['MPLCONFIGDIR'] = '/tmp/avs_ppt_mpl'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Polygon, Rectangle
from matplotlib.collections import LineCollection
import numpy as np
from PIL import Image
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '创新点PPT/素材/新版/control'
SIM = ROOT / 'avs_ws/src/avs_rescue_sim'
RUN = ROOT / 'avs_ws/acceptance/speed_mixed_020_20261012_run2'
BG, FG, MUTED, TEAL, GOLD = '#101b2c', '#f4f7fc', '#a6b7ce', '#42d5bb', '#ffc466'
BLUE, RED = '#7aabff', '#f36d7e'
FONT = FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family': FONT.get_name(), 'font.size': 14,
                     'text.color': FG, 'axes.labelcolor': MUTED, 'xtick.color': MUTED,
                     'ytick.color': MUTED, 'axes.edgecolor': MUTED,
                     'figure.facecolor': BG, 'axes.facecolor': BG, 'savefig.facecolor': BG,
                     'axes.unicode_minus': False})


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches='tight', pad_inches=.2)
    plt.close(fig)


def clean(ax):
    ax.spines[['top', 'right']].set_visible(False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    nav = yaml.safe_load((SIM / 'config/nav_params.yaml').read_text())
    mission = yaml.safe_load((SIM / 'config/mission_params.yaml').read_text())['mission_node']['ros__parameters']
    footprint = np.array(json.loads(nav['local_costmap']['local_costmap']['ros__parameters']['footprint']))
    manifest = []
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.5))
    for ax, (v, w), title in zip(axes, [(0.2, 0.), (0.2, 0.4)], ['直行：保护前伸推板', '转弯：保护完整外扫范围']):
        horizon = .2 + max(abs(v)/.5, abs(w)/.8)
        for t in np.linspace(0, horizon, 12):
            yaw = w*t
            c, s = math.cos(yaw), math.sin(yaw)
            xy = [v*t, 0.] if abs(w) < 1e-6 else [v/w*s, v/w*(1-c)]
            points = footprint @ np.array([[c, s], [-s, c]]) + xy
            ax.add_patch(Polygon(points, closed=True, facecolor=TEAL, edgecolor=TEAL, alpha=.09))
            ax.plot(*np.vstack([points, points[0]]).T, color=TEAL, alpha=.35, lw=1)
        ax.add_patch(Polygon(footprint, facecolor=BLUE, edgecolor=FG, alpha=.7, lw=1.4))
        ax.annotate('车头 / 推板', (.32, .02), (-.05, .32), arrowprops={'arrowstyle':'->','color':FG}, color=FG)
        ax.set(xlim=(-.28,.60), ylim=(-.29,.37), aspect='equal', xlabel='车体前向 / m', ylabel='横向 / m', title=title)
        ax.grid(alpha=.15)
        clean(ax)
    fig.text(.5, .01, '按代码反应时间与制动时长绘制的保护原理示意；不是实测轨迹或连续安全证明。', ha='center', fontsize=12, color=MUTED)
    fig.tight_layout(rect=(0,.06,1,1))
    save(fig, '完整轮廓停车保护示意.png')
    manifest.append(dict(file='完整轮廓停车保护示意.png', kind='源码参数示意',
                         source=['avs_ws/src/avs_rescue_sim/config/nav_params.yaml', 'avs_ws/src/avs_rescue_sim/avs_rescue_sim/motion_safety.py'],
                         meaning='真实footprint，v=0.20；转弯w=0.40；反应0.20秒，制动参数0.5/0.8；示意未绘3.5cm外侧余量'))

    config = yaml.safe_load((SIM / 'maps/rescue_map.yaml').read_text())
    pgm = np.asarray(Image.open(SIM / 'maps/rescue_map.pgm'))
    regions = yaml.safe_load((SIM / 'config/navigation_map.yaml').read_text())['navigation_map_node']['ros__parameters']
    x0, y0 = config['origin'][:2]
    res = config['resolution']
    fig, ax = plt.subplots(figsize=(6.7, 6.4))
    ax.imshow(pgm, cmap='gray', vmin=0, vmax=255,
              extent=(x0,x0+pgm.shape[1]*res,y0,y0+pgm.shape[0]*res), interpolation='nearest')
    for key, color in [('movable_region',GOLD), ('doorway_free_region',RED)]:
        a,b,c,d = regions[key]
        ax.add_patch(Rectangle((a,b),c-a,d-b,facecolor=color,alpha=.2))
        ax.add_patch(Rectangle((a,b),c-a,d-b,fill=False,edgecolor=color,lw=2.4))
    ax.annotate('可移动箱体区域', (1.72,1.12), (1.83,.95), color=GOLD,
                arrowprops={'arrowstyle':'->','color':GOLD}, bbox={'facecolor':BG,'edgecolor':'none','pad':3}, fontsize=13)
    ax.annotate('门洞内部小窗口', (1.35,2.06), (.24,2.51), color=RED,
                arrowprops={'arrowstyle':'->','color':RED}, bbox={'facecolor':BG,'edgecolor':'none','pad':3}, fontsize=13)
    ax.set(xlabel='地图 x / m', ylabel='地图 y / m', title='实际保存地图 + 配置允许更新区域')
    save(fig, '实际地图与允许清理区域.png')
    manifest.append(dict(file='实际地图与允许清理区域.png',kind='实际PGM叠加配置',
                         source=['avs_ws/src/avs_rescue_sim/maps/rescue_map.pgm','avs_ws/src/avs_rescue_sim/maps/rescue_map.yaml','avs_ws/src/avs_rescue_sim/config/navigation_map.yaml'],
                         meaning='原地图像素未改；只叠加两个YAML区域；不代表动态地图清理前后实测'))

    report = json.loads((ROOT/'avs_ws/docs/speed_tuning_validation.json').read_text())
    selected = [r for r in report['records'] if r['run'] in report['selected_runs']]
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    values = [report['baseline_navigation_to_complete_wall_s'], report['selected_mean_navigation_to_complete_wall_s']]
    bars = ax.barh([1,0], values, color=[MUTED,TEAL], height=.5)
    for bar, v in zip(bars, values):
        ax.text(v+3,bar.get_y()+bar.get_height()/2,f'{v:.2f} s',va='center',fontsize=18,color=FG)
    ax.set_yticks([1,0], ['原速基准（1次）','最终配置（2次平均）'])
    ax.set(xlim=(0,370),xlabel='首次导航至任务完成 / s')
    ax.spines[['top','right','left']].set_visible(False)
    ax.grid(axis='x',alpha=.15)
    fig.text(.99,.95,f'任务耗时 −{report["task_time_reduction_percent"]:.1f}%',ha='right',va='top',fontsize=24,color=GOLD)
    fig.text(.5,.015,'含行驶、停车、识别、推障、对正与返航；排除启动与采集尾段。',ha='center',fontsize=11,color=MUTED)
    fig.tight_layout(rect=(0,.08,1,.91))
    save(fig,'完整任务耗时对照.png')
    manifest.append(dict(file='完整任务耗时对照.png',kind='实测统计图',source=['avs_ws/docs/speed_tuning_validation.json'],
                         meaning='1次基准、2次同源码最终配置平均，首次导航至完成310.8198→287.1957秒，节省7.6006%；非多场地成功率'))

    record=json.loads((RUN/'result.json').read_text())
    world=ET.parse(SIM/'worlds/rescue_world.world')
    fig,ax=plt.subplots(figsize=(7,6.8))
    for model in world.findall('./world/model'):
        name=model.get('name')
        x,y=map(float,model.findtext('pose').split()[:2])
        if 'wall' in name or name.startswith('core_north'):
            w,h=map(float,model.findtext('link/collision/geometry/box/size').split()[:2])
            ax.add_patch(Rectangle((x-w/2,y-h/2),w,h,color='#748499'))
    samples=[v for v in record['poses'] if 'rescue_rover' in v]
    categories={'普通路段：0.20 m/s':[],'精细阶段：0.12 m/s':[],'推障：0.10 m/s':[]}
    colors=[BLUE,TEAL,GOLD]
    for before,after in zip(samples,samples[1:]):
        m=after.get('mission',{})
        if m.get('state')=='pushing': key=list(categories)[2]
        elif m.get('step') in mission['precision_navigation_steps']: key=list(categories)[1]
        else:key=list(categories)[0]
        categories[key].append([before['rescue_rover'][:2],after['rescue_rover'][:2]])
    for (label,segs),color in zip(categories.items(),colors):
        ax.add_collection(LineCollection(segs,colors=color,linewidths=2.7,label=label))
    ax.scatter([.55],[.54],s=100,facecolors='none',edgecolors=FG,lw=1.8)
    ax.text(.15,.31,'起点 / 返航',color=FG,fontsize=12)
    initial=(1.5,1.9)
    final=record['final']['push_barrier']
    ax.add_patch(Rectangle((initial[0]-.15,initial[1]-.15),.3,.3,fill=False,edgecolor=RED,lw=1.5,linestyle='--'))
    ax.add_patch(Rectangle((final[0]-.15,final[1]-.15),.3,.3,facecolor=RED,alpha=.8))
    ax.set(xlim=(-.15,3.15),ylim=(-.15,3.15),xlabel='world x / m',ylabel='world y / m',aspect='equal',title='成功运行的实际轨迹与阶段档位')
    ax.legend(loc='upper left',frameon=False,labelcolor=FG,fontsize=11)
    clean(ax)
    save(fig,'实测轨迹与速度档位.png')
    manifest.append(dict(file='实测轨迹与速度档位.png',kind='实测数据可视化',
                         source=['avs_ws/acceptance/speed_mixed_020_20261012_run2/result.json','avs_ws/src/avs_rescue_sim/worlds/rescue_world.world','avs_ws/src/avs_rescue_sim/config/mission_params.yaml'],
                         meaning='world真值轨迹，仅验收使用；颜色是阶段目标速度上限，不是瞬时实测速率；普通档位也可能减速、停车、转向'))
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Generated',len(manifest),'source-backed figures in',OUT)


if __name__=='__main__':main()
