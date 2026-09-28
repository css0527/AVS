#!/usr/bin/env python3
"""Create the local source ZIP and a factual report from acceptance measurements."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

WORKSPACE=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acceptance',type=Path)
    parser.add_argument('--output',type=Path,default=WORKSPACE/'submission',
                        help='Output directory for the source ZIP and PDF report.')
    args=parser.parse_args()
    evidence=json.loads((args.acceptance/'evaluation.json').read_text())
    target=args.output;target.mkdir(parents=True,exist_ok=True)
    pdfmetrics.registerFont(TTFont('CN','/usr/share/fonts/truetype/arphic/ukai.ttc',subfontIndex=0))
    style=ParagraphStyle('body',fontName='CN',fontSize=11,leading=17,spaceAfter=8)
    heading=ParagraphStyle('heading',parent=style,fontSize=15,leading=23,spaceBefore=12)
    title=ParagraphStyle('title',parent=heading,fontSize=21,leading=30)
    story=[Paragraph('无人车仿真组技术实施报告',title),
           Paragraph('AVS 救援巡检平台 · ROS 2 Humble / Gazebo Classic 11',style),
           Paragraph('本报告依据项目源码与同一次连续演示的独立验收记录编写；工程贡献、第三方依赖及适用范围在文末说明。',style)]
    sections=[
      ('1. 任务与系统组成',
       '依据项目提供的 B09 比赛规则，系统从起点沿走廊识别五个不同标识，导航至核心入口，用实体推板推动障碍，进入核心区识别四个 AprilTag 并发布地图坐标 Marker，最后返回起点。路线目标、速度及检测阈值存放在 YAML。'),
      ('2. 场地、建图和定位',
       '自建 3×3 米厂区包含外墙、走廊、0.5 米核心入口、0.3 米实体障碍及九个标识。提供 slam_toolbox 遥控建图和地图保存脚本。运行加载项目保存的 rescue_map.pgm 与配套 YAML，AMCL 使用激光与里程计定位，Smac2D 使用栅格 A*，Regulated Pure Pursuit 输出前进控制。保留原始地图；在不包含墙体的可移动障碍区域，经过三次独立激光空闲射线确认后，发布更新的导航地图；动态代价层仍保留当前实体障碍。'),
      ('3. 推障机构与安全控制',
       '差速底盘前装被动 V 形推板，依靠 Gazebo 刚体接触和摩擦推动 2 千克障碍。前进、转弯经 Nav2；推障阶段根据里程计闭环控制进度、侧偏和航向，限速 0.10 米/秒，位移和时间均有上限。禁止通过删除障碍或修改模型姿态实现清障。激光安全节点检查完整车体轮廓、当前速度与制动过程，仅在有界推障阶段允许推板正前方接触目标；侧面和后方仍检查障碍。'),
      ('4. 视觉分类与核心标定',
       '走廊采用五种自行生成的无文字图案。项目内轻量 YOLOv5 由 C3/SPPF 主干、PAN 与三个 anchor 检测尺度组成，训练合成远近、透视、亮暗、模糊、噪声、遮挡及红箱、蓝色起点、黄色车身、无图案同色牌等负例，导出 TorchScript 在 CPU 推理。逐个候选核验内侧白色图案并沿相机画面拟合牌面四角后，才执行分类 NMS；同类空间关联需连续三帧才发布事件，减少纯色误报和候选框跳动。SIFT 仅为权重缺失时的告警兜底。云台以真实关节电机左右扫描，不改写车身姿态。核心标识有无文字图案、色带及 AprilTag 36h11；由相机内参和已知 Tag 边长计算 PnP，转换拍摄时刻的 TF 到 map，经过重投影检查、样本中值和异常值过滤后发布 RViz Marker。'),
      ('5. 任务闭环和故障处理',
       '任务节点确认 AMCL、规划器、控制器、导航器和速度平滑器均已激活，且导航地图与里程计就绪后才出发。普通任务导航先完成位置目标，再以当前定位位置为目标单独对正朝向，避免定位微调使末端控制反复切换。观察允许两次云台扫描，完成多帧确认即继续。任何漏识别、导航失败、传感器超时或推障偏离均停车，缺少识别结果不能报告完成。回程允许掉头，禁止自动旋转或倒车恢复。'),
      ('6. 实测验收',
       '独立记录 /evaluation/model_states 测量真实车辆、障碍位姿。Marker 与标识真值通过记录的 map←odom TF 转到相同坐标系后比较；原始 world/map 坐标差同时保留，包含 SLAM 地图定位偏移，不能与纯视觉误差混淆。控制与识别节点不订阅真值。以下为指定验收记录的实际结果；轮廓碰撞检查是离散采样，不能等同于连续接触传感器。'),
    ]
    for h,t in sections:
        story.extend([Paragraph(h,heading),Paragraph(t,style)])
    marker_errors=evidence.get('core_marker_errors_m') or {}
    values=[['指标','实测值'],['自动验收','通过' if evidence['passed'] else '未通过'],
      ['运行记录时长',f"{evidence.get('duration_wall_s',0):.1f} s"],
      ['任务完成',str(evidence['mission_complete'])],['走廊类别数',str(len(evidence['corridor_labels']))],
      ['核心 Marker 记录数',str(len(marker_errors))],
      ['障碍位移',f"{evidence['barrier_displacement_m']:.3f} m"],
      ['红箱识别帧数',str(evidence.get('barrier_detection_frames','未记录'))],
      ['返航位置误差',f"{evidence['return_error_m']:.3f} m"],
      ['独立在线 SLAM 地图',str(evidence.get('online_slam_recorded',False))],
      ['墙体轮廓重叠采样数',str(len(evidence['wall_overlap_samples']))]]
    if not marker_errors:
        values.append(['核心 Marker 坐标记录','无坐标转换记录'])
    for tag,err in marker_errors.items():
        values.append([f'Tag {tag} 平面定位误差',
                       '无坐标转换记录' if err is None else f'{err:.3f} m'])
    for tag,err in evidence.get('raw_world_map_coordinate_difference_m',{}).items():
        values.append([f'Tag {tag} 原始 world/map 坐标差',f'{err:.3f} m'])
    table=Table(values,colWidths=[250,220]);table.setStyle(TableStyle([
      ('FONTNAME',(0,0),(-1,-1),'CN'),('FONTSIZE',(0,0),(-1,-1),10),
      ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce7f3')),
      ('GRID',(0,0),(-1,-1),.4,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(table)
    figure=args.acceptance/'trajectory.png'
    if figure.exists():
        story.append(Image(str(figure),width=380,height=400))
    slam_image=args.acceptance/'slam_map.png'
    if slam_image.exists():
        story.append(Paragraph('本次运行由独立 slam_toolbox 生成的激光占据栅格，未替换导航原图。',style))
        story.append(Image(str(slam_image),width=320,height=320,kind='proportional'))
    story.extend([Paragraph('7. 工程贡献、第三方依赖与局限',heading),
      Paragraph('本项目的工程工作包括场地与标识、被动推板结构、传感器云台、轻量模型定义与合成训练、参数化任务编排、动态障碍残影处理以及独立验收。ROS 2、Gazebo、Nav2、slam_toolbox、PyTorch、YOLOv5 架构思想、OpenCV 和 AprilTag 均为第三方基础组件，不宣称为本队原创基础算法。当前权重只适用于本项目五种图案和仿真域，不代表开放类别或真实灾害识别能力。路线与地图针对自建场地，改变墙体、纹理、标识尺寸或相机参数后需重新训练、标定和验收。',style),
      Paragraph('8. 复现与提交',heading),Paragraph('在 avs_ws 执行 ./start.sh 自动编译并运行。执行 python3 src/avs_rescue_sim/tools/run_acceptance.py 生成独立证据。演示视频必须连续记录完整一键流程，同屏显示 Gazebo、RViz、实时终端事件、系统时间和识别处理后的真实车载相机第一视角 /camera/annotated。走廊画面显示分类框和多帧确认状态，核心室内画面显示 AprilTag ID、灾情类别及估计的 map 坐标，并与 RViz 实时 Marker 按同一 ID 对应。红色推障箱以紫红色 PUSH BARRIER 框标出，/obstacles/detections 发布图像检测得到的像素边界框；该展示不读取模型真值，也不影响导航和推障控制。倍速时标注倍速，不超过 5 分钟、100 MB。源码 ZIP 包含技术说明和可用的验收图表、地图及源码哈希记录，不包含缓存、构建目录、视频或完整运行日志。提交前填写队伍身份，核对第三方许可与视频，并由队伍自行提交官网。',style)])
    SimpleDocTemplate(str(target/'technical_report.pdf'),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=40).build(story)
    with ZipFile(target/'avs_rescue_source.zip','w',ZIP_DEFLATED) as archive:
        for directory in ['src','docs']:
            for path in (WORKSPACE/directory).rglob('*'):
                if (path.is_file()
                        and not set(path.parts) & {'__pycache__', '.pytest_cache',
                                                   '.mypy_cache', '.ruff_cache'}
                        and path.suffix not in ['.pyc']):
                    archive.write(path,Path('avs_ws')/path.relative_to(WORKSPACE))
        for path in WORKSPACE.glob('*.sh'):archive.write(path,Path('avs_ws')/path.name)
        archive.write(WORKSPACE/'README.md','avs_ws/README.md')
        archive.write(WORKSPACE/'TECHNICAL_REPORT.md','avs_ws/TECHNICAL_REPORT.md')
        archive.write(args.acceptance/'evaluation.json','avs_ws/docs/acceptance_evaluation.json')
        for name in ['trajectory.png','slam_map.pgm','slam_map.yaml','slam_map.png','source_sha256.json']:
            path=args.acceptance/name
            if path.is_file():
                archive.write(path,Path('avs_ws/docs/acceptance')/name)
    print(target)


if __name__=='__main__':main()
