"""Automatic choice of the detection settings from one image.

There is no reference answer to compare with, so the tuner looks for settings
that give a *stable* answer: it sweeps the detection threshold and looks for
plateaus, ranges of thresholds over which the number of accepted lines does not
change. A wide plateau means the lines stand clearly apart from the noise, and
the middle of it is a safe threshold.

For each background-filter size (half, normal and double the default):
  1. the line signal is computed once;
  2. about 80 thresholds, evenly spaced on a log scale from the noise floor to
     the strongest peak, are tried and the accepted lines counted;
  3. runs of equal count (>= 2 lines, at least ``min_ratio`` wide) are plateaus.
     A plateau must keep at least ``keep`` (default half) of the lines found at
     the noise floor; otherwise "only the few strongest lines" would always win,
     because strong lines stay put over a very wide threshold range.
The widest plateau is the first choice. A plateau that runs into the lower end
of the sweep counts half, because its true width is unknown (the count may
still be growing towards the noise floor). The base settings are always among
the candidates, and the alternatives follow by how little they change the line
count, so answering "n" in the folder analysis gives small steps first. Each plateau becomes a ``DetectionConfig``:

  rel        = threshold / strong-response level of this image (so it scales
               with brightness)
  bg_window  = the filter size of the plateau
  min_dist   = at most half the smallest gap between accepted lines
  x_tol      = from the measured tilt of the lines (never below the default)

The threshold never goes below ``k * sigma`` (noise floor, ``k`` from the base
config), so the sweep cannot end up counting noise as lines. The other fields (n_blocks, k, min_fraction, band_rel, smooth, half_width) are
copied from the base config. ``min_fraction`` is not tuned: a line is accepted
at the base value by construction, so the weakest accepted line can never
justify a different one.
"""
import dataclasses
from dataclasses import replace

import numpy as np

from .detect import (MAD_TO_SIGMA, MIN_THRESHOLD, DetectionConfig, auto_sizes,
                     check_config, compute_signal, detect_lines, select_lines,
                     threshold_from)


def _plateaus(counts, grid, min_lines, min_ratio):
    """Runs of equal line count -> list of (count, t_low, t_high)."""
    out, i = [], 0
    while i < len(counts):
        j = i
        while j + 1 < len(counts) and counts[j + 1] == counts[i]:
            j += 1
        if counts[i] >= min_lines and grid[j] / grid[i] >= min_ratio:
            out.append((counts[i], grid[i], grid[j]))
        i = j + 1
    return out


def _same_lines(a, b, tol):
    """Same lines = same count, every line within ``tol`` px of its partner."""
    return len(a) == len(b) and (len(a) == 0 or
                                 np.max(np.abs(np.asarray(a) - np.asarray(b))) <= tol)


def _median_tilt(sig, xs, threshold, wide):
    """Typical sideways shift (px) of a line between the bands.

    Only bands where the line responds above the threshold are used, so noise
    cannot fake a tilt; the median over the lines ignores single odd lines.
    """
    tilts = []
    for x in xs:
        lo, hi = max(0, int(round(x)) - wide), min(sig.shape[1], int(round(x)) + wide + 1)
        seg = sig[:, lo:hi]
        strong = seg.max(axis=1) >= threshold
        if strong.sum() >= 3:
            pos = lo + seg[strong].argmax(axis=1)
            tilts.append(pos.max() - pos.min())
    return float(np.median(tilts)) if tilts else 0.0


def _candidates_for_strip(img, base=None, n_best=6, n_thresholds=80,
                    bg_scales=(0.5, 1.0, 2.0), min_lines=2, min_ratio=1.15, keep=0.5):
    """Ranked detection settings for an image, best first.

    Returns a list of dicts: config (DetectionConfig), lines (x positions),
    n_lines, threshold, plateau_ratio (how far the threshold can move before
    the count changes), bg_window, status ("ok", "check" if the final settings
    do not reproduce the plateau's line count, "base" for the untouched base
    settings, or "fallback" if no plateau exists and only those are returned).
    """
    base = base or DetectionConfig()
    check_config(base)
    width = np.asarray(img).shape[1]
    bg0, md0, xt0 = auto_sizes(width, base)

    sizes = sorted({max(15, int(round(bg0 * s))) | 1 for s in bg_scales})
    pool = []
    for bg in sizes:
        cfg = replace(base, bg_window=bg)
        sig, _, md, _ = compute_signal(img, cfg)
        mean_sig = sig.mean(axis=0)
        t_min = max(MIN_THRESHOLD, base.k * MAD_TO_SIGMA * float(np.median(mean_sig)))
        top = float(mean_sig.max())
        if top <= 1.2 * t_min:
            continue
        grid = np.geomspace(t_min, top, n_thresholds)
        counts = [len(select_lines(sig, t, base, md, xt0)) for t in grid]
        floor_lines = max(min_lines, int(np.ceil(keep * max(counts))))
        for count, lo, hi in _plateaus(counts, grid, floor_lines, min_ratio):
            ratio = hi / lo
            score = np.log(ratio) * (0.5 if lo <= grid[0] * 1.0001 else 1.0)
            score += np.log(1.05) if bg == bg0 else 0.0
            pool.append({"bg": bg, "count": count, "ratio": ratio, "score": score,
                         "t": float(np.sqrt(lo * hi)), "sig": sig, "md": md})

    if not pool:
        xs, _, thr = detect_lines(img, base)
        return [{"config": base, "lines": xs, "n_lines": len(xs), "threshold": thr,
                 "plateau_ratio": 0.0, "bg_window": bg0, "status": "fallback"}]

    ranked = sorted(pool, key=lambda p: -p["score"])

    out = []
    for p in ranked:
        sig, mean_sig = p["sig"], p["sig"].mean(axis=0)
        xs = select_lines(sig, p["t"], base, p["md"], xt0)
        min_dist = p["md"]
        if len(xs) > 1:
            min_dist = int(min(p["md"], max(5, 0.5 * np.min(np.diff(xs)))))
        x_tol = int(np.clip(np.ceil(_median_tilt(sig, xs, p["t"], 3 * xt0) / 2) + 2,
                            xt0, 3 * xt0))
        rel = p["t"] / float(np.percentile(mean_sig, 99.5))
        cfg = replace(base, bg_window=p["bg"], rel=float(rel),
                      min_dist=min_dist, x_tol=x_tol)

        thr = threshold_from(sig, cfg)                       # same signal, final settings
        final = select_lines(sig, thr, cfg, min_dist, x_tol)
        if any(_same_lines(final, o["lines"], 0.5 * p["md"]) for o in out):
            continue
        out.append({"config": cfg, "lines": final, "n_lines": len(final),
                    "threshold": thr, "plateau_ratio": p["ratio"], "bg_window": p["bg"],
                    "status": "ok" if len(final) == p["count"] else "check"})

    xs_b, _, thr_b = detect_lines(img, base)             # safety net: the base settings
    if not any(_same_lines(xs_b, o["lines"], 0.5 * md0) for o in out):
        out.append({"config": base, "lines": xs_b, "n_lines": len(xs_b),
                    "threshold": thr_b, "plateau_ratio": 0.0,
                    "bg_window": bg0, "status": "base"})

    # first choice stays first; the alternatives follow by how little they
    # change the result (line count), then by plateau width
    head, tail = out[0], out[1:]
    tail.sort(key=lambda c: (abs(c["n_lines"] - head["n_lines"]), -c["plateau_ratio"]))
    return ([head] + tail)[:n_best]


STRIP_HEIGHTS = (200, 400, 100, 50, None)   # tried after base.strip_height; None = full height


def tune_candidates(img, base=None, strips=None, per_strip=3, n_best=8, extended=True, **kwargs):
    """Candidate settings over several strip heights (best first).

    The tuner is run once per strip height. The base strip height (200 px by
    default) comes first with all its candidates; the other heights add their
    best few candidates after it, so answering "n" walks through them. Strip
    heights that give the same lines as an earlier candidate are skipped.
    extended=False tunes only the base strip height (about 5x faster); the first
    candidate is the same either way.
    """
    base = base or DetectionConfig()
    order = [base.strip_height] + ([s for s in (strips or STRIP_HEIGHTS) if s != base.strip_height]
                                   if extended else [])
    out = []
    for i, sh in enumerate(order):
        cands = _candidates_for_strip(img, dataclasses.replace(base, strip_height=sh), **kwargs)
        cands = cands if i == 0 else [c for c in cands if c["status"] == "ok"][:per_strip]
        for c in cands:
            tol = 0.5 * (c["config"].min_dist or 100)
            if not any(_same_lines(c["lines"], o["lines"], tol) for o in out):
                c["strip_height"] = sh
                out.append(c)
    return out[:n_best] if out else _candidates_for_strip(img, base, **kwargs)


def tune_parameters(tune_img, base=None):
    """The best detection settings for one image -> (DetectionConfig, report).

    report: status ("ok", "check" or "fallback"), n_lines, lines, threshold,
    plateau_ratio, bg_window and alternatives (number of other candidates; use
    tune_candidates to get them).
    """
    cands = tune_candidates(tune_img, base)
    best = cands[0]
    report = {k: v for k, v in best.items() if k != "config"}
    report["alternatives"] = len(cands) - 1
    return best["config"], report
