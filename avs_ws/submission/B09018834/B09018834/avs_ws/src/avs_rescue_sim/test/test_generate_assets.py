"""Asset generation must not silently replace a saved SLAM map."""

import importlib.util
from pathlib import Path

import cv2
import pytest
import yaml


@pytest.fixture
def assets(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'tools' / 'generate_assets.py'
    spec = importlib.util.spec_from_file_location('generate_assets', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    module.TEXTURES = tmp_path / 'textures'
    maps = tmp_path / 'maps'
    maps.mkdir()
    (maps / 'rescue_map.pgm').write_bytes(b'previously saved SLAM pixels')
    (maps / 'rescue_map.yaml').write_text('previously saved SLAM metadata')
    return module


def saved_map(assets):
    return {p.name: p.read_bytes() for p in (assets.ROOT / 'maps').iterdir()}


def test_help_does_not_write_assets(assets):
    before = saved_map(assets)
    with pytest.raises(SystemExit) as exit_info:
        assets.main(['--help'])
    assert exit_info.value.code == 0
    assert not assets.TEXTURES.exists()
    assert saved_map(assets) == before


def test_texture_generation_preserves_slam_map(assets):
    before = saved_map(assets)
    assets.main([])
    assert len(list(assets.TEXTURES.glob('*.png'))) == 9
    assert saved_map(assets) == before


def test_text_free_core_boards_remain_distinct_and_decodable(assets):
    assets.main([])
    images = [cv2.imread(str(path)) for path in sorted(assets.TEXTURES.glob('*.png'))]
    assert len({image.tobytes() for image in images}) == 9
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11))
    for tag_id in range(4):
        image = cv2.imread(str(assets.TEXTURES / f'apriltag_{tag_id}.png'))
        _, ids, _ = detector.detectMarkers(cv2.resize(image, (180, 180)))
        assert ids is not None and ids.flatten().tolist() == [tag_id]


def test_explicit_map_export_has_matching_coordinates(assets):
    before = saved_map(assets)
    output = assets.ROOT / 'exported_map'
    assets.main(['--map-output', str(output)])
    metadata = yaml.safe_load((output / 'rescue_map.yaml').read_text())
    image = cv2.imread(str(output / metadata['image']), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    assert metadata['origin'] == [-0.2, -0.2, 0.0]
    assert metadata['resolution'] == 0.02
    # Check physical wall centres, rather than just checking file existence.
    for x, y in [(0., 1.5), (3., 1.5), (1.5, 3.), (1.1, 1.)]:
        px = round((x - metadata['origin'][0]) / metadata['resolution'])
        py = image.shape[0] - 1 - round(
            (y - metadata['origin'][1]) / metadata['resolution'])
        assert image[py, px] == 0
    assert saved_map(assets) == before
