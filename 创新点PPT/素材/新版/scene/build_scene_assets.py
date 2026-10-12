"""Reproducible PPT assets from existing Gazebo recording and current SDF.

Only exports presentation assets. Does not change or launch the simulator.
"""
from pathlib import Path
import json
import math
import hashlib
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
VIDEO = ROOT / 'avs_ws/acceptance/recording_yolov5_smac_v19/continuous_raw.mp4'
SDF = ROOT / 'avs_ws/src/avs_rescue_sim/models/rescue_rover/model.sdf'
WORLD = ROOT / 'avs_ws/src/avs_rescue_sim/worlds/rescue_world.world'
RUN = ROOT / 'avs_ws/acceptance/speed_mixed_020_20261012_run2'
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
BG = '#1D2C42'
FG = '#F4F7FC'
MUTED = '#A6B7CE'
TEAL = '#42D5BB'


def font(size):
    return ImageFont.truetype(FONT, size)


def frame_at(seconds):
    cap = cv2.VideoCapture(str(VIDEO))
    cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f'Cannot extract frame at {seconds}s')
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def transform(text):
    x, y, z, a, b, c = map(float, (text or '0 0 0 0 0 0').split())
    rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    matrix = np.eye(4)
    matrix[:3, :3] = rz @ ry @ rx
    matrix[:3, 3] = [x, y, z]
    return matrix


def model_triangles():
    triangles = []
    components = []
    for link in ET.parse(SDF).findall('./model/link'):
        for visual in link.findall('visual'):
            matrix = transform(link.findtext('pose')) @ transform(visual.findtext('pose'))
            geometry = visual.find('geometry')
            color = np.array(list(map(float, visual.findtext('material/diffuse').split()))[:3])
            faces = []
            if geometry.find('box') is not None:
                dims = np.array(list(map(float, geometry.findtext('box/size').split()))) / 2
                points = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                                   [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]) * dims
                faces = [points[index] for index in [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4],
                                                     [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]]
            elif geometry.find('cylinder') is not None:
                radius = float(geometry.findtext('cylinder/radius'))
                h = float(geometry.findtext('cylinder/length')) / 2
                angles = np.linspace(0, 2 * np.pi, 65)
                bottom = np.c_[radius * np.cos(angles), radius * np.sin(angles), np.full(len(angles), -h)]
                top = bottom.copy()
                top[:, 2] = h
                faces = [bottom[:-1][::-1], top[:-1]] + [np.array([bottom[i], bottom[i + 1], top[i + 1], top[i]]) for i in range(64)]
            elif geometry.find('sphere') is not None:
                radius = float(geometry.findtext('sphere/radius'))
                azimuth = np.linspace(0, 2 * np.pi, 65)
                elevation = np.linspace(0, np.pi, 33)
                points = np.array([[[radius * np.cos(a) * np.sin(b), radius * np.sin(a) * np.sin(b), radius * np.cos(b)]
                                    for a in azimuth] for b in elevation])
                faces = [np.array([points[j, i], points[j + 1, i], points[j + 1, i + 1], points[j, i + 1]])
                         for j in range(32) for i in range(64)]
            else:
                raise RuntimeError(f'Unrecognized visual: {visual.attrib}')
            vertices = []
            for face in faces:
                face = face @ matrix[:3, :3].T + matrix[:3, 3]
                vertices.extend(face)
                for index in range(1, len(face) - 1):
                    triangle = face[[0, index, index + 1]]
                    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
                    length = np.linalg.norm(normal)
                    if length < 1e-12:
                        continue
                    triangles.append((triangle, normal / length, color))
            vertices = np.asarray(vertices)
            components.append({'link': link.get('name'), 'visual': visual.get('name'),
                               'min_model_xyz_m': vertices.min(axis=0).tolist(),
                               'max_model_xyz_m': vertices.max(axis=0).tolist()})
    return triangles, components


def render_model(path, camera):
    """Orthographic, physical geometry, per-pixel depth (no painter-order overlap)."""
    triangles, components = model_triangles()
    camera = np.array(camera, dtype=float)
    camera /= np.linalg.norm(camera)
    right = np.cross([0., 0., 1.], camera)
    right /= np.linalg.norm(right)
    up = np.cross(camera, right)
    basis = np.stack([right, up, camera])
    coordinates = np.concatenate([t[0] @ basis.T for t in triangles])
    xy_min, xy_max = coordinates[:, :2].min(axis=0), coordinates[:, :2].max(axis=0)
    center = (xy_min + xy_max) / 2
    width, height = 2000, 1400
    scale = min((width - 250) / (xy_max[0] - xy_min[0]), (height - 180) / (xy_max[1] - xy_min[1]))
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:] = (29, 44, 66)
    depth = np.full((height, width), -np.inf)
    light = np.array([.3, -.5, .82])
    light /= np.linalg.norm(light)
    for vertices, normal, color in triangles:
        point = vertices @ basis.T
        px = (point[:, 0] - center[0]) * scale + width / 2
        py = height / 2 - (point[:, 1] - center[1]) * scale
        x0, x1 = max(0, int(np.floor(px.min()))), min(width - 1, int(np.ceil(px.max())))
        y0, y1 = max(0, int(np.floor(py.min()))), min(height - 1, int(np.ceil(py.max())))
        if x1 < x0 or y1 < y0:
            continue
        denominator = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2])
        if abs(denominator) < 1e-10:
            continue
        xx, yy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        a = ((py[1] - py[2]) * (xx - px[2]) + (px[2] - px[1]) * (yy - py[2])) / denominator
        b = ((py[2] - py[0]) * (xx - px[2]) + (px[0] - px[2]) * (yy - py[2])) / denominator
        c = 1 - a - b
        z = a * point[0, 2] + b * point[1, 2] + c * point[2, 2]
        z_view = depth[y0:y1 + 1, x0:x1 + 1]
        visible = (a >= -1e-7) & (b >= -1e-7) & (c >= -1e-7) & (z > z_view)
        shade = .58 + .42 * max(0., float(normal @ light))
        canvas[y0:y1 + 1, x0:x1 + 1][visible] = np.rint(np.clip(color * shade * 255, 0, 255)).astype(np.uint8)
        z_view[visible] = z[visible]
    Image.fromarray(canvas).save(path)
    return components


def trajectory():
    """Same real samples and registration convention as evaluate_run.render_trace."""
    result = json.loads((RUN / 'result.json').read_text())
    im = Image.new('RGB', (1600, 1740), BG)
    draw = ImageDraw.Draw(im)
    plot = (140, 138, 1485, 1483)
    draw.rectangle(plot, fill='#F5F7FA')
    scale = 410
    def pixel(point):
        return 200 + point[0] * scale, 1430 - point[1] * scale
    world = ET.parse(WORLD)
    for model in world.findall('./world/model'):
        name = model.get('name')
        x, y = map(float, model.findtext('pose').split()[:2])
        if 'wall' in name or name.startswith('core_north'):
            w, h = map(float, model.findtext('link/collision/geometry/box/size').split()[:2])
            draw.rectangle((*pixel((x - w / 2, y + h / 2)), *pixel((x + w / 2, y - h / 2))), fill='#3C4652')
        if name.startswith('core_tag_'):
            px, py = pixel((x, y))
            draw.line((px - 9, py, px + 9, py), fill='#222B35', width=4)
            draw.line((px, py - 9, px, py + 9), fill='#222B35', width=4)
            draw.text((px - 43, py - 49), name[-1], font=font(27), fill='#222B35')
    previous = None
    for sample in result['poses']:
        rover = sample.get('rescue_rover')
        if rover is None:
            continue
        point = pixel(rover)
        step = sample.get('mission', {}).get('step', '')
        color = '#219B7A' if 'return' in step or 'exit' in step else '#2D7DE0'
        if previous is not None:
            draw.line((*previous, *point), fill=color, width=5)
        previous = point
    for tag, position in result['markers'].items():
        registration = result.get('marker_frames', {}).get(str(tag))
        if registration is not None:
            tx, ty, yaw = registration
            c, s = math.cos(yaw), math.sin(yaw)
            position = np.array([[c, s], [-s, c]]) @ (np.asarray(position) - [tx, ty])
        px, py = pixel(position)
        draw.ellipse((px - 11, py - 11, px + 11, py + 11), outline='#B844B4', width=4)
    x, y = result['final']['push_barrier'][:2]
    draw.rectangle((*pixel((x - .15, y + .15)), *pixel((x + .15, y - .15))), fill='#D74D47')
    draw.rectangle((*pixel((1.35, 2.05)), *pixel((1.65, 1.75))), outline='#D74D47', width=4)
    px, py = pixel((.55, .54))
    draw.ellipse((px - 14, py - 14, px + 14, py + 14), outline='#2D7DE0', width=4)
    draw.text((115, 35), '最新成功运行：实际采样轨迹', font=font(48), fill=FG)
    for text, color, x in [('蓝：去程', '#5C9BFF', 150), ('绿：返程', '#42D5BB', 545), ('紫：标签估计', '#D97CD7', 930)]:
        draw.text((x, 1530), text, font=font(36), fill=color)
    draw.text((150, 1595), '红色空框：箱体初位；实心：最终位置', font=font(30), fill=MUTED)
    draw.text((150, 1650), '2026-10-12 / speed_mixed_020_run2 / 3 × 3 m', font=font(27), fill=MUTED)
    im.save(OUT / 'trajectory_latest.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rect = (425, 160, 970, 575)
    frame_at(90).crop(rect).save(OUT / 'scene_overview_actual.png')
    shots = [(128, '推前：对准门口箱体'), (135, '推中：低速接触推进'), (160, '推后：箱体移入室内')]
    montage = Image.new('RGB', (1770, 590), BG)
    draw = ImageDraw.Draw(montage)
    for i, (seconds, label) in enumerate(shots):
        im = frame_at(seconds).crop(rect)
        im.save(OUT / f'push_{seconds}s_actual.png')
        x = 20 + i * 590
        montage.paste(im, (x, 68))
        draw.text((x, 20), label, font=font(28), fill=FG)
        draw.text((x, 500), f'原始连续录屏 / {seconds} s', font=font(24), fill=MUTED)
    draw.text((20, 548), '同一次 v19 历史成功运行；用于展示机械动作，非本次提速实验。', font=font(24), fill=MUTED)
    montage.save(OUT / 'push_sequence_actual.png')
    # A genuine complete rover view exists, but only 98×65 pixels. Do not AI upscale.
    frame_at(175).crop((740, 345, 838, 410)).save(OUT / 'vehicle_actual_crop.png')
    # Preserve the whole Gazebo viewport as the provenance for the crop.
    frame_at(175).crop((280, 140, 1120, 605)).save(OUT / 'vehicle_actual_context.png')
    components = render_model(OUT / 'vehicle_sdf_front.png', [.85, -1., .72])
    render_model(OUT / 'vehicle_sdf_rear.png', [-1., -.9, .45])
    trajectory()
    assets = [
        {'file': 'scene_overview_actual.png', 'type': '真实 Gazebo 录屏裁剪', 'source': str(VIDEO.relative_to(ROOT)), 'seconds': 90, 'crop_xyxy': rect, 'meaning': '当前项目匹配的灰色走廊、蓝色起点、黄色核心区；历史 v19 运行'},
        {'file': 'push_sequence_actual.png', 'type': '真实连续录屏三帧拼图', 'source': str(VIDEO.relative_to(ROOT)), 'seconds': [128, 135, 160], 'crop_xyxy': rect, 'meaning': '同一次历史成功运行的推前、推中、推后场景；不可标作最新提速实测'},
        {'file': 'vehicle_actual_crop.png', 'type': '真实 Gazebo 整车裁剪', 'source': str(VIDEO.relative_to(ROOT)), 'seconds': 175, 'crop_xyxy': [740, 345, 838, 410], 'meaning': '完整车辆轮廓，原始 98×65 px；清晰度有限，适合小角标而非放大做机械细节主图'},
        {'file': 'vehicle_actual_context.png', 'type': '真实 Gazebo 录屏裁剪', 'source': str(VIDEO.relative_to(ROOT)), 'seconds': 175, 'crop_xyxy': [280, 140, 1120, 605], 'meaning': '保留整车和场地背景的来源证据'},
        {'file': 'vehicle_sdf_front.png', 'type': '当前 SDF 等比例几何渲染示意', 'source': str(SDF.relative_to(ROOT)), 'meaning': '整车前方视角：真实尺寸、位置与配色，逐像素深度遮挡；必须标注按 SDF 渲染，不可称为 Gazebo 截图'},
        {'file': 'vehicle_sdf_rear.png', 'type': '当前 SDF 等比例几何渲染示意', 'source': str(SDF.relative_to(ROOT)), 'meaning': '整车后方视角：轮组、后万向球轮；必须标注按 SDF 渲染'},
        {'file': 'trajectory_latest.png', 'type': '最新成功运行记录重绘', 'source': str((RUN/'result.json').relative_to(ROOT)), 'meaning': '实际救援车位置采样，当前 world 墙体和记录 marker_frames 转换标签点；不是 RViz 地图或规划路线，误差解释须沿用验收说明'},
    ]
    manifest = {
        'assets': assets,
        'rejected_or_limited_existing_images': [
            {'path': 'avs_ws/docs/rescue_navigation_verified.png', 'decision': '替换', 'reason': '整条左侧走廊为蓝色，与当前 rescue_world.world 的灰走廊、仅蓝起点不符；雷达可视化也与当前 visualize=false 不符'},
            {'path': 'avs_ws/docs/world_comparison.png', 'decision': '不用整图', 'reason': '右侧是无关的 Ackermann mini.world；左侧只是布局示意，不能当真实导航验收截图'},
            {'path': '创新点PPT/素材/整车结构展示.png', 'decision': '替换并明确示意身份', 'reason': '几何来源确为当前 SDF，未发现组成或尺寸造假；但旧 matplotlib 面平均深度排序在相交推板处遮挡不佳，缺真实截图来源说明'},
            {'path': 'avs_ws/acceptance/recording_yolov5_smac_v19/evidence/slam_map.png', 'decision': '不作地图残影清理前后证据', 'reason': '只有单幅低分辨率 153×165 栅格，不能证明三次自由证据前后变化'},
            {'path': 'avs_ws/acceptance/speed_mixed_020_20261012_run2/trajectory.png', 'decision': '可用；已按同一记录重绘清晰中文版本', 'reason': '最新通过运行的测量轨迹，非在线 SLAM 地图'},
            {'path': 'avs_ws/acceptance/recording_yolov5_smac_v19/continuous_raw.mp4', 'decision': '采用场景与机械动作，不用作地图清理前后证明', 'reason': 'RViz 同时显示历史地图/轨迹，未录制可分辨 /map 与 /navigation_map 的同区域前后栅格；不能把整幅 RViz 变化归因于局部地图清理'},
        ],
        'map_before_after_evidence_available': False,
        'map_slide_recommendation': '用当前源码逻辑的明确原理示意，加真实推障前后图作为任务背景；不把示意称为实测栅格对照。',
        'sdf_sha256': hashlib.sha256(SDF.read_bytes()).hexdigest(),
        'geometry_visual_components': components,
        'geometry_verified': {'chassis_size_m': [.42, .24, .14], 'wheel_diameter_m': .17, 'wheel_separation_m': .24, 'rear_caster_radius_m': .047, 'pusher_crossbar_size_m': [.14, .28, .10], 'wing_yaws_rad': [-.45, .45], 'lidar_center_model_m': [.08, 0, .23], 'camera_center_model_m': [.20, 0, .27]},
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'output': str(OUT), 'assets': [a['file'] for a in assets]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
