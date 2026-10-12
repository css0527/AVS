"""Render the current complete vehicle with the reviewed SDF depth renderer."""
from pathlib import Path
import importlib.util
import shutil


def main():
    output = Path(__file__).resolve().parent
    scene = output / '素材/新版/scene'
    spec = importlib.util.spec_from_file_location(
        'avs_scene_renderer', scene / 'build_scene_assets.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.render_model(scene / 'vehicle_sdf_front.png', [.85, -1., .72])
    renderer.render_model(scene / 'vehicle_sdf_rear.png', [-1., -.9, .45])
    shutil.copyfile(scene / 'vehicle_sdf_front.png', output / '素材/整车结构展示.png')
    print('已依据当前 SDF 生成完整车辆图；图片为模型渲染示意。')


if __name__ == '__main__':
    main()
