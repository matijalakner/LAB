"""Real photos of series 08 with hand-marked lines: every line must be found.

The photos (tests/data/real, 2576 px wide as uploaded) cover the hard cases:
steps down left of the bright centre, steps up right of it, faint thin lines in
the centre, narrow bands (102-185 px next to 300-400 px), a dark vignetted left
edge, dust, and JPEG block edges.
"""
import json
from pathlib import Path

import numpy as np

from line_analysis.spacing import trimmed_mean
import pytest
from PIL import Image

from line_analysis.jumps import Analyser, JumpConfig, _prepare_auto, run_series
from line_analysis.lines import LineSizes

DATA = Path(__file__).parent / "data" / "real"
TRUTH = {k: v for k, v in json.loads((DATA / "truth.json").read_text()).items()
         if not k.startswith("_")}
ORDER = sorted(TRUTH)
TOL = 15


def _img(name):
    return np.asarray(Image.open(DATA / f"{name}.jpg").convert("RGB"))


def _counted(name, img):
    """True lines away from the cut edges and the filter margin."""
    w = img.shape[1]
    lo = int(round(200 * w / 6000)) + LineSizes.for_width(w).margin
    return [x for x in TRUTH[name] if lo <= x <= w - lo]


def _check(found, truth):
    missed = [x for x in truth if all(abs(f - x) > TOL for f in found)]
    false = [f for f in found if all(abs(f - x) > TOL for x in truth)]
    return missed, false


@pytest.mark.parametrize("name", ORDER)
def test_preparation_finds_every_line(name):
    img = _img(name)
    an = Analyser(JumpConfig())
    kept = _prepare_auto(an, img)
    missed, false = _check(kept, _counted(name, img))
    assert not missed and not false, (missed, false)


@pytest.mark.parametrize("name", ORDER)
def test_middle_three_rows_find_every_line(name):
    img = _img(name)
    res = run_series([img], details=True)[0]
    truth = _counted(name, img)
    missed, false = _check(res.spacing.lines, truth)
    assert not missed and not false, (missed, false)
    assert not res.doubtful, res.doubts
    # the trimmed average does not telescope to (last - first) / steps, so the
    # hand marks' 1-2 px error of single lines counts: within 1 %
    assert abs(res.spacing.spacing / trimmed_mean(np.diff(truth)) - 1) < 0.01


def test_series_with_big_jumps_between_photos():
    """All photos as one series, prepared on the first only: tracking across 30-80
    frames fails on some, the 300-row check notices and they are prepared again."""
    imgs = [_img(n) for n in ORDER]
    for name, img, res in zip(ORDER, imgs, run_series(imgs, details=True)):
        missed, false = _check(res.spacing.lines, _counted(name, img))
        assert not missed and not false, (name, missed, false)


def test_three_row_strips_across_the_middle():
    """Different 3-row strips (+-140 rows around the middle): nearly every line."""
    found = total = 0
    for name in ORDER:
        img = _img(name)
        an = Analyser(JumpConfig(check_rows=0))
        _prepare_auto(an, img)
        ref, temps, sp = an.reference, an.templates, an.spacing
        h = img.shape[0]
        truth = _counted(name, img)
        for y in range(h // 2 - 140, h // 2 + 141, 40):
            an.reference, an.templates, an.spacing = ref, temps, sp
            res = an.measure(img[y - 150:y + 151])          # middle 3 rows: y - 1 .. y + 1
            missed, _ = _check(res.spacing.lines, truth)
            found += len(truth) - len(missed)
            total += len(truth)
    assert found / total > 0.97
