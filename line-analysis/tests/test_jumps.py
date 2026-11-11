import csv
import json

import numpy as np
import pytest
from PIL import Image

from line_analysis.jumps import (MAX_TRIES, NAVY, JumpConfig, _next_value, find_jumps,
                                 main_jumps, mark_navy)

GRID = 300 + 100 * np.arange(12)        # 300 ... 1400 in a 1700 px photo


def _photo(path, xs, width=1700, height=600, seed=0):
    """Dark 3 px lines on a grey background: the contrast jumps up on their right side."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 180, np.float32) + rng.normal(0, 2, (height, width, 3))
    for x in xs:
        img[:, int(x) - 1:int(x) + 2] = 60
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)   # png: no jpeg blur


def _folder(inp, sets, name="j"):
    for k, xs in enumerate(sets):
        _photo(inp / "folder" / name / f"{name}_{k:04d}.png", xs, seed=k)


def _read(out, name="j", file="results.csv"):
    with open(out / "jumps" / name / file) as f:
        return list(csv.DictReader(f))


def _answers(*seq):
    it = iter(seq)
    asked = []

    def ask(q):
        asked.append(q)
        return next(it)
    ask.asked = asked
    return ask


def test_find_jumps_takes_positive_jumps_only():
    p = np.zeros(200)
    p[50:53] = -0.5           # dark line: down at 49/50, up at 52/53
    p[120:] = 0.3             # a step up
    p[160:] = 0.0             # a step down: negative, not a line
    xs = find_jumps(p, 0.1)
    assert np.allclose(xs, [52.5, 119.5])
    assert find_jumps(p, 0.6) == []


def test_next_value_moves_and_bisects():
    v, lo, hi = _next_value(0.1, "+", None, None)          # more lines: lower
    assert v < 0.1 and hi == 0.1
    v2, lo, hi = _next_value(v, "-", lo, hi)                # now fewer: between v and 0.1
    assert lo == v and v < v2 < 0.1


def test_non_interactive_run(dirs):
    inp, out = dirs
    _folder(inp, [GRID, GRID + 5, GRID + 10])
    rows = main_jumps("j", out, inp, interactive=False, show=False)
    rec = _read(out)
    assert len(rows) == 3 and all(r["warning"] == "" for r in rec)
    assert all(abs(float(r["mean_spacing_px"]) - 100) < 0.5 for r in rec)
    lines = _read(out, file="lines.csv")
    xs = np.array(lines[1]["x_px"].split(), float)
    assert len(xs) == 12 and np.allclose(xs, GRID + 5 + 1.5, atol=1)   # whole-photo x
    params = json.loads((out / "jumps" / "j" / "parameters.json").read_text())
    assert params["edge"] == 200 and params["rows"] == 3 and params["prep_rows"] == 300
    assert len(params["preparations"][0]["initial_positions"]) == 12
    marked = np.asarray(Image.open(out / "jumps" / "j" / "j_0000_marked.jpg"))
    assert marked.shape[:2] == (600, 1700)                 # the whole photo
    x = float(lines[0]["x_px"].split()[0])
    col = marked[:, int(round(x))].astype(int)
    assert np.abs(col - NAVY).sum(axis=1).max() < 60       # navy from top to bottom


def test_edges_are_cut(dirs):
    inp, out = dirs
    _folder(inp, [np.r_[100, GRID, 1600]])                  # lines inside the 200 px edges
    main_jumps("j", out, inp, interactive=False, show=False)
    assert _read(out, file="lines.csv")[0]["n_lines"] == "12"


def test_preparation_retries_then_count_change_is_asked(dirs):
    inp, out = dirs
    _folder(inp, [GRID, GRID, np.delete(GRID, [3, 7]), np.delete(GRID, [3, 7])])
    # too high first (no lines), '+' lowers it 3 times; then y. Photo 3 has 2 lines fewer: y.
    ask = _answers("n", "+", "n", "+", "n", "+", "y", "y")
    rows = main_jumps("j", out, inp, JumpConfig(contrast_diff=2.0), show=False, ask=ask)
    assert len(rows) == 4
    lines = _read(out, file="lines.csv")
    assert [r["n_lines"] for r in lines] == ["12", "12", "10", "10"]
    assert [r["checked"] for r in lines] == ["", "", "accepted", ""]
    rec = _read(out)
    assert all(abs(float(r["mean_spacing_px"]) - 100) < 0.5 for r in rec)   # grid fit
    assert (out / "jumps" / "j" / "preparation" / "try4_j_0000.jpg").exists()


def test_no_at_a_count_change_prepares_again(dirs):
    inp, out = dirs
    _folder(inp, [GRID, np.r_[GRID, 1450], GRID])
    ask = _answers("y", "n", "y", "y")      # prep ok; photo 2 not ok -> prepare again: ok;
    rows = main_jumps("j", out, inp, show=False, ask=ask)                # photo 3 back to 12: ok
    assert len(rows) == 3
    lines = _read(out, file="lines.csv")
    assert lines[1]["checked"] == "prepared again"
    params = json.loads((out / "jumps" / "j" / "parameters.json").read_text())
    assert [p["photo"] for p in params["preparations"]] == ["j_0000.png", "j_0001.png"]


def test_quits_after_15_tries_and_on_q(dirs):
    inp, out = dirs
    _folder(inp, [GRID, GRID])
    ask = _answers(*(["n", "-"] * MAX_TRIES))
    assert main_jumps("j", out, inp, show=False, ask=ask) == []
    assert sum("Is this okay" in q for q in ask.asked) == MAX_TRIES
    _folder(inp, [GRID, np.delete(GRID, 4)], name="k")
    rows = main_jumps("k", out, inp, show=False, ask=_answers("y", "q"))
    assert len(rows) == 1 and len(_read(out, "k")) == 1                  # written so far


def test_mark_navy_full_height():
    m = mark_navy(np.zeros((50, 3000, 3), np.uint8), [1000.4])
    assert (m[:, 999:1002] == NAVY).all() and (m[:, 990] == 0).all()
