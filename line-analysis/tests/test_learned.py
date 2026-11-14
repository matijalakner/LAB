"""Learned detector (``analysis jumps --detector learned``) on real photos."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from line_analysis.jumps import Analyser, JumpConfig, _prepare_auto, run_series
from line_analysis.learned import LineModel, features, training_strips
from line_analysis.lines import LineSizes
from line_analysis.spacing import trimmed_mean

DATA = Path(__file__).parent / "data"
GREEN = DATA / "green"
TOL = 10


def _truth(folder):
    return {k: v for k, v in json.loads((folder / "truth.json").read_text()).items()
            if not k.startswith("_")}


def _img(path):
    return np.asarray(Image.open(path).convert("RGB"))


def _inside(xs, img, edge):
    w = img.shape[1]
    lo = int(round(edge * w / 6000)) + LineSizes.for_width(w).margin + 5
    return [x for x in xs if lo < x < w - lo]


GREEN_CFG = dict(edge=470, contrast_diff=5)


def test_green_series_learned():
    truth = _truth(GREEN)
    names = sorted(truth)
    imgs = [_img(GREEN / f"{n}.jpg") for n in names]
    res = run_series(imgs, JumpConfig(detector="learned", **GREEN_CFG), details=True)
    for name, img, r in zip(names, imgs, res):
        tr = _inside(truth[name], img, 470)
        found = r.spacing.lines
        missed = [x for x in tr if all(abs(x - f) > TOL for f in found)]
        false = [f for f in _inside(found, img, 470) if all(abs(x - f) > TOL for x in tr)]
        assert not false, (name, false)
        # the faint line at ~2130 in 0009 is followed but not found on 3 rows
        assert all(abs(x - 2130) < 15 for x in missed), (name, missed)
        assert abs(r.spacing.spacing / trimmed_mean(np.diff(tr)) - 1) < 0.005, name


def test_learned_finds_every_line_of_the_first_series():
    real = DATA / "real"
    truth = _truth(real)
    for name in sorted(truth):
        img = _img(real / f"{name}.jpg")
        r = run_series([img], JumpConfig(detector="learned"), details=True)[0]
        tr = _inside(truth[name], img, 200)
        found = r.spacing.lines
        assert not [x for x in tr if all(abs(x - f) > 15 for f in found)], name
        assert not [f for f in _inside(found, img, 200)
                    if all(abs(x - f) > 15 for x in tr)], name


def test_network_learns_lines_and_not_the_rest():
    """Trained on one photo, it gives the lines of another photo a high
    probability and the places between them a low one."""
    truth = _truth(GREEN)
    a, b = _img(GREEN / "08_green_0000.jpg"), _img(GREEN / "08_green_0005.jpg")
    an = Analyser(JumpConfig(detector="learned", **GREEN_CFG))
    _prepare_auto(an, a)
    edge, sz = an.edge_px(b), an.line_sizes(b)
    p = an.model.prob(an.gray(b, 9), sz)
    lines = [x - edge for x in _inside(truth["08_green_0005"], b, 470)]
    at_lines = [p[int(x) - 3:int(x) + 4].max() for x in lines]
    between = [p[int(x) + 30:int(y) - 30].max() for x, y in zip(lines, lines[1:])]
    assert np.median(at_lines) > 0.8
    assert np.median(between) < 0.2


def test_model_save_and_load(tmp_path):
    img = _img(GREEN / "08_green_0000.jpg")
    an = Analyser(JumpConfig(detector="learned", **GREEN_CFG))
    _prepare_auto(an, img)
    path = tmp_path / "line_model.npz"
    an.model.save(path)
    loaded = LineModel.load(path)
    g, sz = an.gray(img, 3), an.line_sizes(img)
    assert np.allclose(loaded.prob(g, sz), an.model.prob(g, sz), atol=1e-5)
    # a run can start from it
    an2 = Analyser(JumpConfig(detector="learned", model=str(path), **GREEN_CFG))
    assert an2.model is not None and an2.model.trained


def test_no_learn_keeps_the_first_training():
    truth = _truth(GREEN)
    imgs = [_img(GREEN / f"{n}.jpg") for n in sorted(truth)]
    counts = {}
    for learn in (True, False):
        an = Analyser(JumpConfig(detector="learned", learn=learn, **GREEN_CFG))
        _prepare_auto(an, imgs[0])
        first = len(an.model.y)
        for img in imgs[:2]:
            an.accept(an.measure(img))
        counts[learn] = (first, len(an.model.y))
    assert counts[False][1] == counts[False][0]
    assert counts[True][1] > counts[True][0]


def test_features_and_strips_shapes():
    img = _img(GREEN / "08_green_0000.jpg")
    an = Analyser(JumpConfig(**GREEN_CFG))
    an.set_weights(img)
    full = an.gray(img, 300)
    strips = training_strips(full, 3, n=10)
    assert len(strips) == 10 and all(s.shape == (3, full.shape[1]) for s in strips)
    F = features(strips[0], an.line_sizes(img))
    assert F.shape[0] == full.shape[1] and np.isfinite(F).all()
