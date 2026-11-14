import csv
import json

import numpy as np

from line_analysis.spacing import trimmed_mean
import pytest
from PIL import Image

from line_analysis.jumps import (MAX_TRIES, NAVY, Analyser, JumpConfig, _next_value,
                                 channel_weights, find_jumps, main_jumps, mark_navy, period,
                                 track_jumps)

GRID = 300 + 100 * np.arange(12)        # 300 ... 1400 in a 1700 px photo


def _photo(path, xs, width=1700, height=600, seed=0, faint=()):
    """Dark 3 px lines on a grey background (``faint`` x: only slightly darker)."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 180, np.float32) + rng.normal(0, 2, (height, width, 3))
    for x in xs:
        img[:, int(x) - 1:int(x) + 2] = 60
    for x in faint:
        img[:, int(x) - 1:int(x) + 2] = 165
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
    xs = find_jumps(p, 0.1, width=1)
    assert np.allclose(xs, [52.5, 119.5])
    assert find_jumps(p, 0.6, width=1) == []
    # over 4 px: the same lines, the jump of a smooth edge is collected
    xs4 = find_jumps(p, 0.1, width=4)
    assert len(xs4) == 2 and abs(xs4[0] - 52) < 2 and abs(xs4[1] - 119.5) < 2


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
    assert len(xs) == 12 and np.allclose(xs - xs[0], GRID - GRID[0], atol=1)
    assert abs(xs[0] - (GRID[0] + 5)) < 4                               # whole-photo x
    assert all(abs(float(r["period_vs_spacing_pct"])) < 2 for r in lines)
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
    _folder(inp, [np.r_[30, GRID, 1670]])            # inside the edges (57 px at 1700 px)
    main_jumps("j", out, inp, interactive=False, show=False)
    assert _read(out, file="lines.csv")[0]["n_lines"] == "12"


def test_preparation_retries_then_count_change_is_asked(dirs):
    inp, out = dirs
    _folder(inp, [GRID, GRID, np.delete(GRID, [3, 7]), np.delete(GRID, [3, 7])])
    # far too high first (no lines), '+' lowers it, then a typed value; y.
    # Photo 3 has 2 lines fewer: y.
    ask = _answers("n", "+", "n", "+", "n", "20", "y", "y")
    rows = main_jumps("j", out, inp, JumpConfig(contrast_diff=1e9, ask="count"), show=False,
                      ask=ask)
    assert len(rows) == 4
    lines = _read(out, file="lines.csv")
    assert [r["n_lines"] for r in lines] == ["12", "12", "10", "10"]
    assert [r["checked"] for r in lines] == ["", "", "accepted", ""]
    rec = _read(out)
    assert all(abs(float(r["mean_spacing_px"]) - 100) < 0.5 for r in rec)   # grid fit
    assert (out / "jumps" / "j" / "preparation" / "try4_j_0000.jpg").exists()


def test_no_at_a_count_change_prepares_again(dirs):
    inp, out = dirs
    _folder(inp, [GRID, np.delete(GRID, 4), GRID])
    # prep ok; photo 2 (a line gone) not ok -> prepare again on it: ok; photo 3 has
    # 12 again, one more than photo 2: ok; at the end only photo 3 is asked (photo 2
    # was decided by its accepted preparation): keep it
    ask = _answers("y", "n", "y", "y", "y")
    rows = main_jumps("j", out, inp, JumpConfig(ask="count"), show=False, ask=ask)
    assert len(rows) == 3
    lines = _read(out, file="lines.csv")
    assert lines[1]["checked"] == "prepared again"
    assert sum(q.startswith("y = keep") for q in ask.asked) == 1
    params = json.loads((out / "jumps" / "j" / "parameters.json").read_text())
    assert [p["photo"] for p in params["preparations"]] == ["j_0000.png", "j_0001.png"]


def test_quits_after_15_tries_and_on_q(dirs):
    inp, out = dirs
    _folder(inp, [GRID, GRID])
    ask = _answers(*(["n", "-"] * MAX_TRIES))
    assert main_jumps("j", out, inp, show=False, ask=ask) == []
    assert sum("Is this okay" in q for q in ask.asked) == MAX_TRIES
    _folder(inp, [GRID, np.delete(GRID, 4)], name="k")
    rows = main_jumps("k", out, inp, JumpConfig(ask="count"), show=False,
                      ask=_answers("y", "q"))
    assert len(rows) == 1 and len(_read(out, "k")) == 1                  # written so far


def test_mark_navy_full_height():
    m = mark_navy(np.zeros((50, 3000, 3), np.uint8), [1000.4])
    assert (m[:, 999:1002] == NAVY).all() and (m[:, 990] == 0).all()


def test_channel_weights():
    red = np.zeros((10, 50, 3), np.uint8)
    red[..., 0], red[..., 2] = 90, 4                       # red light: G, B nearly black
    w = channel_weights(red)
    assert w[0] > 0.9 and w[1] == 0 and np.isclose(w.sum(), 1)
    orange = np.zeros((10, 50, 3), np.uint8)
    orange[..., 0], orange[..., 1] = 255, 130              # red saturated: no contrast in it
    assert np.allclose(channel_weights(orange), [0, 1, 0])
    assert np.allclose(channel_weights(red, "mean"), 1 / 3)
    assert np.allclose(channel_weights(red, "g"), [0, 1, 0])


def _noisy_profile(xs, n=1300, depth=0.03, noise=0.01, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.normal(0, noise, n)
    for x in xs:
        p[int(x) - 2:int(x) + 2] -= depth                   # weak dark line, 4 px
    return p


def test_tracking_ignores_noise_between_lines():
    xs = 100 + 100 * np.arange(11)
    cfg = JumpConfig(jump_width=4, merge=10)
    p = _noisy_profile(xs)
    found, nxt, _ = track_jumps(p, list(xs + 3), cfg, new_limit=6)
    assert len(found) >= 10
    assert all(np.min(np.abs(xs + 2 - x)) < 6 for x in found)      # only near real lines
    untracked = find_jumps(p, 2 * 0.01 * np.sqrt(2), 10, 4)
    assert len(untracked) > 15                                        # noise lines without it


def test_tracking_keeps_a_lost_line_and_does_not_fill_it_with_noise():
    xs = 100 + 100 * np.arange(11)
    cfg = JumpConfig(jump_width=4, merge=10)
    p = _noisy_profile(np.delete(xs, 5), depth=0.5)                 # bright photo, one line gone
    found, nxt, _ = track_jumps(p, list(xs), cfg, new_limit=6)
    assert len(found) == 10 and len(nxt) == 11 and 600 in nxt


def test_extra_line_between_tracked_lines_is_ignored(dirs):
    inp, out = dirs
    _folder(inp, [GRID, np.r_[GRID, 1450], GRID + 3])
    ask = _answers("y", "y")              # preparation; photo 2: the 300-row check sees 1450
    main_jumps("j", out, inp, show=False, ask=ask)
    assert sum("Is this okay" in q for q in ask.asked) == 2
    assert [r["n_lines"] for r in _read(out, file="lines.csv")] == ["12", "12", "12"]
    assert "not followed at x=1450" in _read(out)[1]["quality"]


def test_new_lines_at_the_edges():
    xs = 100 + 100 * np.arange(11)
    cfg = JumpConfig(jump_width=4, merge=10)
    p = _noisy_profile(xs, depth=0.5)
    found, _, _ = track_jumps(p, list(xs[1:-1]), cfg, new_limit=6)  # lines 100, 1100 are new
    assert len(found) == 11


def test_period_cross_check():
    xs = 100 + 97.3 * np.arange(12)
    p = _noisy_profile(xs, depth=0.05)
    assert abs(period(p, 100) - 97.3) < 1
    assert period(p, None) is None


def test_sizes_scale_with_the_width():
    an = Analyser(JumpConfig())
    assert an.sizes(np.zeros((1, 6000, 3))) == (18, 47)
    assert an.edge_px(np.zeros((1, 6000, 3))) == 200 and an.edge_px(np.zeros((1, 3000, 3))) == 100
    ls = an.line_sizes(np.zeros((1, 3000, 3)))
    assert (ls.w, ls.half) == (4, 35)
    assert Analyser(JumpConfig(jump_width=1)).sizes(np.zeros((1, 3000, 3)))[0] == 1


def test_gap_rule_excludes_the_line_of_a_short_distance():
    from line_analysis.jumps import gap_rule, spacing_with_rule
    xs = list(100 + 100 * np.arange(10))
    kept, excluded, parts = gap_rule(xs + [430])              # 30 px from 400: too close
    assert excluded == [430] and kept == xs and len(parts) == 1
    sp = spacing_with_rule(xs + [430, 455])                   # two false lines
    assert sorted(sp.excluded) == [430, 455] and np.isclose(sp.spacing, 100)
    assert sp.n_extra == 2
    kept, excluded, _ = gap_rule(xs + [120])                  # at the end: the false one goes
    assert excluded == [120]


def test_gap_rule_leaves_long_distances_out():
    from line_analysis.jumps import spacing_with_rule
    xs = np.r_[100 + 100 * np.arange(5), 900 + 103 * np.arange(5)]   # 500 -> 900: 4x
    sp = spacing_with_rule(xs)
    assert sp.long_gaps == [(500, 900)] and not sp.excluded
    # parts: 4 steps of 100 and 4 of 103; the long distance does not count
    assert np.isclose(sp.spacing, (400 + 412) / 8)
    assert sp.n_missing == 3


def test_one_missed_line_is_flagged():
    from line_analysis.jumps import Analyser, Measurement, spacing_with_rule
    xs = list(np.delete(100 + 100 * np.arange(12), 5).astype(float))   # one 2x distance
    sp = spacing_with_rule(xs)
    assert not sp.excluded and not sp.long_gaps and np.isclose(sp.spacing, 100)  # 2x trimmed
    doubts = Analyser(JumpConfig(check_rows=0)).doubts(Measurement(xs, sp, xs))
    assert any("line may be missing" in d for d in doubts)


def test_uneven_bands_are_kept_with_strengths():
    from line_analysis.jumps import spacing_with_rule
    xs = [100, 400, 680, 1000, 1290, 1392, 1790, 2130]        # like 08_0122: a 102 px band
    sp = spacing_with_rule(xs, strengths=[30, 35, 40, 33, 20, 35, 12, 30])
    assert sp.lines == xs and np.isclose(sp.spacing, trimmed_mean(np.diff(xs)))
    sp = spacing_with_rule(xs + [1340], strengths=[30, 35, 40, 33, 20, 35, 12, 30, 5])
    assert sp.excluded == [1340] and sp.n_extra == 1           # a weak line in the band goes


def test_false_line_in_the_preparation_is_excluded(dirs):
    inp, out = dirs
    for k, xs in enumerate([GRID, GRID, GRID]):                 # a faint line 30 px from one
        _photo(inp / "folder" / "j" / f"j_{k:04d}.png", xs, seed=k,
               faint=[GRID[3] + 30] if k == 0 else ())
    main_jumps("j", out, inp, interactive=False, show=False)
    params = json.loads((out / "jumps" / "j" / "parameters.json").read_text())
    assert len(params["preparations"][0]["initial_positions"]) == 12
    rec = _read(out)
    assert all(abs(float(r["mean_spacing_px"]) - 100) < 0.5 for r in rec)


def test_doubtful_photo_is_asked_and_one_missing_line_is_not(dirs):
    inp, out = dirs
    half_gone = GRID[[0, 1, 2, 3, 10, 11]]                     # 6 of 12: coverage 50 %
    _folder(inp, [GRID, np.delete(GRID, 5), GRID, half_gone, GRID])
    ask = _answers("y", "y")                                    # preparation, then photo 4
    rows = main_jumps("j", out, inp, show=False, ask=ask)
    assert len(rows) == 5 and sum("Is this okay" in q for q in ask.asked) == 2
    rec = _read(out)
    assert rec[1]["quality"] == "ok" and rec[1]["n_missing"] == "1"
    assert "lines found" in rec[3]["quality"]
    assert all(abs(float(r["mean_spacing_px"]) - 100) < 0.5 for r in rec)
    assert all(float(r["spacing_err_px"]) < 0.5 for r in rec)
    assert (out / "jumps" / "j" / "overview.png").stat().st_size > 0


def test_review_mode_asks_only_at_the_end(dirs):
    inp, out = dirs
    half_gone = GRID[[0, 1, 2, 3, 10, 11]]
    _folder(inp, [GRID, half_gone, GRID])
    ask = _answers("y", "x")                                    # prep; review: exclude photo 2
    main_jumps("j", out, inp, JumpConfig(ask="review"), show=False, ask=ask)
    assert ask.asked[1].startswith("y = keep, x = exclude")
    rec = _read(out)
    assert rec[1]["warning"] == "excluded in review" and rec[0]["warning"] == ""
    assert _read(out, file="lines.csv")[1]["checked"] == "excluded"


def test_every_line_keeps_its_own_shape():
    from line_analysis.lines import make_templates, track
    x = np.arange(1200.0)
    L = np.zeros_like(x)
    lines = [200, 450, 700, 950]
    for k, xl in enumerate(lines):                    # steps down, then up (as in the photos)
        L += (-0.2 if k < 2 else 0.2) * (x >= xl)
    temps = make_templates(L, lines, 20)
    assert np.dot(temps[0][0], temps[3][0]) < -0.5    # opposite steps: opposite shapes
    rng = np.random.default_rng(0)
    moved = np.zeros_like(x)
    for k, xl in enumerate(lines):
        moved += (-0.2 if k < 2 else 0.2) * (x >= xl * 1.03 + 12)
    moved += rng.normal(0, 0.01, len(x))
    found, score, _ = track(moved, lines, temps, 250)
    assert np.allclose(found, [xl * 1.03 + 12 for xl in lines], atol=2)
    assert min(score) > 0.8


def test_weighted_fit_follows_the_precise_points():
    from line_analysis.fits import fit_curve
    x = np.arange(10.0)
    y = 2 * x + 1
    y[7] += 5                                                    # one bad point ...
    sig = np.full(10, 0.1)
    sig[7] = 10                                                  # ... with a large error bar
    assert abs(fit_curve(x, y, "linear", sig).params[0] - 2) < 0.01
    assert abs(fit_curve(x, y, "linear").params[0] - 2) > 0.1


def test_bench_template_on_a_dark_series():
    from dataclasses import replace
    from line_analysis.bench import DEFAULT_SERIES, METHODS, run_bench
    spec = replace(DEFAULT_SERIES[0], n=6)
    res = run_bench([spec], {"t": METHODS["jumps template"]}, verbose=False)[0]
    assert res["err_med"] < 1.0 and res["bad"] <= 1


def test_a_big_hole_does_not_remove_good_lines():
    from line_analysis.jumps import average_gap, spacing_with_rule
    xs = [300, 400, 500, 600, 1300, 1400]                      # 6 lines lost in the middle
    sp = spacing_with_rule(xs)
    assert sp.lines == xs and not sp.excluded and sp.long_gaps == [(600, 1300)]
    assert np.isclose(sp.spacing, 100) and sp.n_missing == 6
    assert np.isclose(average_gap([100, 100, 100, 700, 100]), 100)
    assert np.isclose(average_gap([98, 102, 100]), 100)


def test_the_end_asks_about_every_photo_still_doubtful(dirs):
    """After the run, photos still doubtful are shown again, except those kept
    with y during the run; with --yes too (final_review)."""
    inp, out = dirs
    _folder(inp, [GRID, GRID, GRID])
    cfg = JumpConfig(q_snr=1.01)              # no match reaches it: every photo doubtful
    # prep y, then y for each doubtful photo during the run: nothing left at the end
    ask = _answers("y", "y", "y", "y")
    main_jumps("j", out, inp, cfg, show=False, ask=ask)
    assert sum(q.startswith("Is this okay") for q in ask.asked) == 4
    assert not any(q.startswith("y = keep") for q in ask.asked)
    # --yes: nothing asked during the run; at the end every doubtful photo:
    # keep the first, exclude the others
    ask = _answers("y", "x", "x")
    rows = main_jumps("j", out, inp, cfg, interactive=False, show=False, ask=ask,
                      final_review=True)
    assert sum(q.startswith("y = keep") for q in ask.asked) == 3
    assert "excluded in review" not in rows[0][6]
    assert all("excluded in review" in r[6] for r in rows[1:])
    lines = _read(out, file="lines.csv")
    assert [l["checked"] for l in lines] == ["kept", "excluded", "excluded"]
    # no terminal: the end review stops quietly
    def eof(_):
        raise EOFError
    rows = main_jumps("j", out, inp, cfg, interactive=False, show=False, ask=eof,
                      final_review=True)
    assert len(rows) == 3


def test_review_only_of_a_finished_run(dirs):
    """analysis jumps NAME --review: the still doubtful photos of a finished run,
    without measuring again; p prepares one photo again."""
    from line_analysis.jumps import review_jumps
    inp, out = dirs
    _folder(inp, [GRID, GRID, GRID])
    cfg = JumpConfig(q_snr=1.01)              # every photo doubtful
    main_jumps("j", out, inp, cfg, interactive=False, show=False, final_review=False)
    before = _read(out)
    # photo 1: keep; photo 2: prepare again (preparation y) -> decided, not shown
    # again although still doubtful; photo 3: exclude
    ask = _answers("y", "p", "y", "x")
    rows = review_jumps("j", out, inp, show=False, ask=ask)
    assert len(rows) == 3
    assert sum(q.startswith("y = keep") for q in ask.asked) == 3
    lines = _read(out, file="lines.csv")
    assert [l["checked"] for l in lines] == ["kept", "prepared again", "excluded"]
    after = _read(out)
    assert after[0]["mean_spacing_px"] == before[0]["mean_spacing_px"]   # not measured again
    assert "excluded in review" in after[2]["warning"]
    assert "excluded in review" not in after[1]["warning"]
    params = json.loads((out / "jumps" / "j" / "parameters.json").read_text())
    assert params["preparations"][-1]["photo"] == "j_0001.png"
    assert params["preparations"][-1]["in_review"]
    # a second review: kept and excluded photos are not asked again
    ask = _answers()
    review_jumps("j", out, inp, show=False, ask=ask)
    assert not ask.asked
    # nothing to review without a finished run
    with pytest.raises(FileNotFoundError):
        review_jumps("nothing", out, inp, show=False, ask=_answers())
