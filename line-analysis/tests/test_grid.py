import json

import numpy as np
import pytest
from PIL import Image

from line_analysis.detect import EXTRA_COLOR, MISSING_COLOR, LINE_COLOR, mark_grid
from line_analysis.spacing import fit_grid, spacing_stats, trimmed_mean

RNG = np.random.default_rng(3)
XS = 250 + 221 * np.arange(10) + RNG.normal(0, 5, 10)
MEAN = trimmed_mean(np.diff(XS))     # 10% largest and smallest distances left out


def test_all_lines_found_gives_the_trimmed_mean_gap():
    f = fit_grid(XS)
    assert np.isclose(f.spacing, MEAN) and not f.missing and not f.extra
    assert np.isclose(f.std, np.std(np.diff(XS), ddof=1))
    assert spacing_stats(XS)[2] == 10


def test_missed_lines_do_not_change_the_spacing():
    for drop in ([4], [1, 7], [3, 4]):                      # one, two apart, two neighbours
        f = fit_grid(np.delete(XS, drop))
        # a missed line makes one distance per grid step fewer; trimming then
        # leaves out a slightly different set, so the spacing moves by < 1 %
        assert np.isclose(f.spacing, MEAN, rtol=1e-2), drop
        assert np.allclose(f.missing, XS[drop], atol=35)
    # dropping an end line shortens the grid, but the spacing stays close
    assert abs(fit_grid(XS[1:]).spacing - MEAN) < 3


def test_false_lines_are_left_out():
    false = [XS[3] + 100, XS[6] + 130, XS[8] + 75]
    f = fit_grid(np.r_[XS, false])
    assert np.isclose(f.spacing, MEAN)
    assert np.allclose(sorted(f.extra), sorted(false))
    assert len(f.lines) == 10


def test_missed_and_false_together():
    xs = np.r_[np.delete(XS, [2, 6]), XS[5] + 90, XS[8] + 130]
    f = fit_grid(xs)
    assert np.isclose(f.spacing, MEAN, rtol=1e-2)
    assert len(f.missing) == 2 and len(f.extra) == 2


def test_a_second_line_near_a_grid_position_is_extra():
    f = fit_grid(np.r_[XS, XS[5] + 30])
    assert np.isclose(f.spacing, MEAN) and f.extra == [pytest.approx(XS[5] + 30)]


def test_uneven_spacing_still_fits():
    xs = np.cumsum(np.r_[100, 221 * (1 + 0.06 * np.sin(np.arange(9)))])  # +-6 % gaps
    f = fit_grid(xs)
    assert not f.extra and not f.missing
    assert np.isclose(f.spacing, trimmed_mean(np.diff(xs)))


def test_few_lines():
    assert fit_grid([5]) is None and spacing_stats([]) is None
    assert np.isclose(fit_grid([10, 60]).spacing, 50)
    xs = [10, 60, 110, 160, 260, 310]                             # 210 missed
    assert np.isclose(fit_grid(xs).spacing, 50)
    assert fit_grid(xs).missing == [pytest.approx(210)]


def test_mark_grid_colours():
    img = np.full((40, 1000, 3), 128, np.uint8)
    xs = [100, 300, 400, 500, 600, 650]                           # 200 missed, 650 false
    m = mark_grid(img, xs)
    assert tuple(m[0, 300]) == LINE_COLOR
    assert tuple(m[0, 650]) == EXTRA_COLOR
    assert tuple(m[0, 200]) == MISSING_COLOR and tuple(m[1, 200]) == (128, 128, 128)


def _photo(path, xs, width=1400, height=300, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 180, np.float32) + rng.normal(0, 3, (height, width, 3))
    for x in xs:
        img[:, int(round(x)) - 1:int(round(x)) + 2] = 60
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path, quality=95)


@pytest.mark.parametrize("method", ["contrast", "peaks"])
def test_folder_spacing_ignores_missed_and_false_lines(dirs, method):
    from line_analysis.folder import main_folder
    inp, out = dirs
    grid = 150 + 100 * np.arange(11)                             # 150 ... 1150
    photos = [grid, np.delete(grid, 5), grid, np.r_[grid, 700], grid, grid,
              np.delete(grid, 3), grid]
    for k, xs in enumerate(photos):
        _photo(inp / "folder" / "g" / f"g_{k:04d}.jpg", xs, seed=k)
    main_folder("g", out, inp, interactive=False, show=False, method=method)
    import csv
    with open(out / "folder" / "g" / "results.csv") as f:
        rec = list(csv.DictReader(f))
    assert len(rec) == len(photos)
    spacing = np.array([float(r["mean_spacing_px"]) for r in rec])
    assert np.all(np.abs(spacing - 100) < 1.0), spacing
    assert all(r["warning"] == "" for r in rec)
    assert [r["n_missing"] for r in rec][1] == "1" and rec[6]["n_missing"] == "1"
    assert rec[3]["n_extra"] == "1"
    marked = np.asarray(Image.open(out / "folder" / "g" / "g_0003_marked.png"))
    assert (np.abs(marked[:, :, :].astype(int) - EXTRA_COLOR).sum(axis=2) == 0).any()


def test_trimmed_mean_leaves_out_the_largest_and_smallest_10_percent():
    gaps = np.r_[np.full(18, 100.0), 10.0, 500.0]              # 20 distances: 2 left out
    assert trimmed_mean(gaps) == 100.0
    assert trimmed_mean([90, 100, 130]) == 100.0              # 4 lines: one at each end
    assert trimmed_mean([90, 130]) == 110.0                   # 3 lines: plain mean
    assert trimmed_mean(np.r_[np.full(28, 100.0), 1, 2, 3, 500, 600, 700]) == 100.0
