import csv
import json
import os

import numpy as np
import pytest
from PIL import Image

from line_analysis import DetectionConfig, TrackingConfig, track_lines
from line_analysis.detect import compute_signal, threshold_from
from line_analysis.folder import main_folder
from line_analysis.track import brackets
from conftest import line_image


def lines_at(xs, width=800, height=300, dark=60, faint=(), faint_dark=165, seed=0):
    """Image with lines at given x; lines whose index is in ``faint`` are weak."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 180, np.float32) + rng.normal(0, 3, (height, width, 3))
    for i, x in enumerate(xs):
        x0 = int(round(x)) - 1
        img[:, max(0, x0):x0 + 3] = faint_dark if i in faint else dark
    return np.clip(img, 0, 255).astype(np.uint8)


def track(img, ref, tracking=None):
    cfg = DetectionConfig()
    sig, _, _, x_tol = compute_signal(img, cfg)
    return track_lines(sig, ref, threshold_from(sig, cfg), cfg, x_tol, tracking)


def test_brackets_touch_and_edges_are_optional():
    brs = brackets([30, 130, 230, 760], width=800, tolerance=10)
    assert brs[0]["optional"] and not brs[1]["optional"] and brs[3]["optional"]
    assert brs[1]["wide"] == (80, 180) and brs[2]["wide"][0] == 180
    assert brs[1]["narrow"] == (120, 140)


def test_small_drift_is_found_in_the_narrow_bracket():
    ref = [100, 200, 300, 400, 500, 600, 700]
    t = track(lines_at([x + 6 for x in ref]), ref)
    assert not t["reported"] and t["widened"] == 0
    assert np.allclose(t["lines"], [x + 6 for x in ref], atol=1.5)
    assert t["reference"] == pytest.approx(t["lines"])


def test_large_drift_widens_the_search():
    ref = [100, 200, 300, 400, 500, 600, 700]
    t = track(lines_at([x + 35 for x in ref]), ref, TrackingConfig(x_tolerance=10))
    assert not t["reported"] and t["widened"] == len(ref)
    assert np.allclose(t["lines"], [x + 35 for x in ref], atol=1.5)


def test_one_line_per_bracket_even_with_an_extra_line():
    ref = [100, 200, 300, 400]
    t = track(lines_at([100, 200, 215, 300, 400]), ref)
    assert len(t["lines"]) == 4 and not t["reported"]


def test_line_that_leaves_the_picture_is_allowed():
    ref = [20, 120, 220, 320]
    t = track(lines_at([120, 220, 320]), ref)
    assert not t["reported"] and t["left"] == [20]
    assert 20 in t["reference"]                      # kept, so it can come back


def test_faint_line_is_found_at_lower_contrast():
    ref = [100, 200, 300, 400, 500, 600, 700]
    img = lines_at(ref, faint=(3,))
    assert track(img, ref, TrackingConfig(contrast_steps=(1.0,)))["missing"] == [400]
    t = track(img, ref)
    assert not t["reported"] and t["lowered"] >= 1 and t["min_factor"] < 1


def test_missing_middle_line_is_reported_and_reference_kept():
    ref = [100, 200, 300, 400, 500, 600, 700]
    t = track(lines_at([100, 200, 300, 500, 600, 700]), ref)
    assert t["reported"] and t["missing"] == [400]
    assert t["reference"] == ref


def test_folder_tracking_follows_drift_and_reports(dirs):
    inp, out = dirs
    folder = inp / "folder" / "tr"
    folder.mkdir(parents=True)
    base = [100, 200, 300, 400, 500, 600, 700]
    shifts = [0, 15, 30, 45, None, 60, 75]           # photo 4 loses a line
    for i, s in enumerate(shifts):
        xs = [x + (s if s is not None else 50) for x in base]
        if s is None:
            xs = xs[:3] + xs[4:]
        img = lines_at(xs, seed=i)
        Image.fromarray(img).save(folder / f"tr_{i:04d}.png")
        t = 1_700_000_000 + i
        os.utime(folder / f"tr_{i:04d}.png", (t, t))

    rows = main_folder("tr", out, inp, interactive=False, show=False, edge=0,
                       tracking=TrackingConfig(x_tolerance=10))
    with open(out / "folder" / "tr" / "tracking.csv") as f:
        trk = list(csv.DictReader(f))
    assert [r["status"] for r in trk] == ["reference", "ok", "ok", "ok", "reported", "ok", "ok"]
    assert "tracking: no line" in rows[4][6]
    # after the reported photo the search starts from photo 3 (+45) and still finds +60
    last = [float(x) for x in trk[-1]["reference_x"].split()]
    assert np.allclose(last, [x + 75 for x in base], atol=1.5)
    assert all(r[4] == 7 for i, r in enumerate(rows) if i != 4)
    params = json.loads((out / "folder" / "tr" / "parameters.json").read_text())
    assert params["tracking"]["x_tolerance"] == 10
