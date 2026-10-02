"""Camera previews must preserve ROS image row padding, color and ownership."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip('rclpy')
pytest.importorskip('PyQt5')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avs_rescue_sim.demo_viewer import image_to_qimage


def test_bgr_preview_preserves_padded_rows_and_owns_pixels():
    # Two BGR rows with two padding bytes apiece. Padding must not become pixels.
    data = bytearray([0, 0, 255, 0, 255, 0, 88, 99,
                      255, 0, 0, 255, 255, 255, 88, 99])
    message = SimpleNamespace(encoding='bgr8', width=2, height=2, step=8, data=data)
    image = image_to_qimage(message)
    data[:] = bytes(len(data))
    assert image.pixelColor(0, 0).getRgb() == (255, 0, 0, 255)
    assert image.pixelColor(1, 0).getRgb() == (0, 255, 0, 255)
    assert image.pixelColor(0, 1).getRgb() == (0, 0, 255, 255)
    assert image.pixelColor(1, 1).getRgb() == (255, 255, 255, 255)


@pytest.mark.parametrize('encoding,data,expected', [
    ('rgb8', [90, 40, 10], (90, 40, 10, 255)),
    ('rgba8', [90, 40, 10, 128], (90, 40, 10, 128)),
    ('bgra8', [10, 40, 90, 128], (90, 40, 10, 128)),
    ('mono8', [70], (70, 70, 70, 255)),
])
def test_camera_encoding_and_alpha(encoding, data, expected):
    message = SimpleNamespace(encoding=encoding, width=1, height=1,
                              step=len(data), data=bytearray(data))
    image = image_to_qimage(message)
    message.data[:] = bytes(len(data))
    assert image.pixelColor(0, 0).getRgb() == expected


@pytest.mark.parametrize('overrides', [
    {'step': 2}, {'width': 0}, {'height': 0}, {'data': b'\x00'},
    {'encoding': '32FC1'},
])
def test_invalid_frames_raise_descriptive_error(overrides):
    values = dict(encoding='rgb8', width=1, height=1, step=3, data=b'\x00\x00\x00')
    values.update(overrides)
    with pytest.raises(ValueError):
        image_to_qimage(SimpleNamespace(**values))
