import numpy as np
import pytest
from PIL import Image

from line_analysis import DetectionConfig, analyse_image, detect_lines, load_image
from line_analysis.spacing import spacing_stats
from conftest import line_image


@pytest.mark.parametrize("spacing", [40, 55, 80])
def test_lines_are_found_where_they_are(spacing):
    img, xs = line_image(spacing)
    found, _, _ = detect_lines(img, DetectionConfig())
    assert len(found) == len(xs)
    assert np.max(np.abs(np.array(found) - np.array(xs))) <= 1.5
    mean, std, n = spacing_stats(found)
    assert mean == pytest.approx(spacing, abs=0.5)


def test_spacing_stats_needs_two_lines():
    assert spacing_stats([10]) is None
    mean, std, n = spacing_stats([0, 10])
    assert (mean, n) == (10, 2) and np.isnan(std)


def test_16_bit_png_is_scaled_to_8_bit(tmp_path):
    import cv2
    img, xs = line_image(50)
    gray16 = (img[:, :, 0].astype(np.uint16) * 257)
    path = tmp_path / "flir_0000.png"
    cv2.imwrite(str(path), gray16)
    loaded = load_image(path)
    assert loaded.dtype == np.uint8 and loaded.shape == img.shape
    assert abs(int(loaded[0, 0, 0]) - int(img[0, 0, 0])) <= 1
    found, _, _ = detect_lines(loaded)
    assert len(found) == len(xs)


def test_analyse_image_writes_marked_png_and_csv(tmp_path):
    img, xs = line_image(60)
    src = tmp_path / "s_0000.jpg"
    Image.fromarray(img).save(src, quality=95)
    res = analyse_image(src, tmp_path / "out", plot=True)
    assert len(res["lines"]) == len(xs)
    marked = np.asarray(Image.open(res["marked_path"]))
    assert marked.shape == img.shape
    rows = open(res["csv_path"]).read().splitlines()
    assert rows[0] == "line,x_px,spacing_px" and len(rows) == 1 + len(xs)
    assert (tmp_path / "out" / "s_0000_signal.png").exists()
