"""Synthetic photos with vertical lines, and files in the equipment formats."""
import csv

import numpy as np
import pytest
from PIL import Image


def line_image(spacing, n=8, width=800, height=300, offset=40, dark=60, bg=180,
               line_width=3, seed=0):
    """RGB image with ``n`` dark vertical lines ``spacing`` px apart (plus noise)."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), bg, np.float32)
    img += rng.normal(0, 3, img.shape)
    xs = [offset + i * spacing for i in range(n) if offset + i * spacing < width - 5]
    for x in xs:
        x0 = int(round(x)) - line_width // 2
        img[:, x0:x0 + line_width] = dark
    return np.clip(img, 0, 255).astype(np.uint8), xs


def save_photo(path, spacing, **kw):
    img, xs = line_image(spacing, **kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path, quality=95)
    return xs


def write_log(path, header, rows, stamp="2026-11-02T07:31:11.102Z"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if stamp:
            w.writerow(["time_stamp", stamp])
        w.writerow(header)
        w.writerows(rows)
    return path


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "input", tmp_path / "output"
