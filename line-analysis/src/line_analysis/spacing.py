"""Line spacing over time, from the lines.csv written by process_video."""
from .paths import output_root
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .utils import write_csv


def read_lines_csv(path):
    """Rows of lines.csv as dicts: time (float), frame (int), lines (list).

    The leading ``time_stamp,<UTC>`` line is skipped; files without it still work.
    """
    with open(path, newline="", encoding="utf-8") as f:
        if not f.readline().startswith("time_stamp"):
            f.seek(0)
        return [{"time": float(r["time"]), "frame": int(r["frame"]),
                 "lines": json.loads(r["lines"])} for r in csv.DictReader(f)]


@dataclass
class GridFit:
    """Lines placed on a regular grid x = x0 + index * spacing.

    spacing    distance between neighbouring grid positions (px)
    lines      the lines on the grid (sorted), index their grid numbers
    extra      lines between grid positions (false lines; not used)
    missing    x of the grid positions between the first and the last line
               where no line was found
    std        sample std of the single-step gaps (NaN with fewer than 2)
    """
    spacing: float
    x0: float
    lines: list = field(default_factory=list)
    index: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    std: float = float("nan")

    @property
    def n_grid(self):
        """Grid positions from the first to the last line (found + missing)."""
        return len(self.lines) + len(self.missing)


EXTRA_TOL = 0.25     # a line further than this fraction of the spacing from the grid is extra


def _first_guess(gaps):
    """Spacing from the gaps, robust to a few halved (extra line) or doubled (missed) gaps."""
    m = float(np.median(gaps))
    full = gaps[gaps >= 0.6 * m]                   # halved gaps cannot set the scale
    m = float(np.median(full)) if len(full) else m
    k = np.maximum(np.round(full / m), 1)          # doubled gaps count as two steps
    return float(np.median(full / k)) if len(full) else m


def fit_grid(xs, extra_tol=EXTRA_TOL, iterations=10, hint=None):
    """Fit a regular grid to line positions -> GridFit, or None for < 2 lines.

    A missed line leaves a gap of two (or more) steps, and a false line falls
    between two grid positions; with the mean of the gaps either one changes
    the spacing by about 1/(number of lines). Here every line gets the grid
    number nearest to (x - x0) / spacing; lines further than ``extra_tol`` *
    spacing from their grid position, or sharing it with a closer line, are
    extra. The spacing is then (last - first line) / (their grid numbers
    apart), which is the plain mean of the gaps when nothing is missed or extra.
    ``hint``: a spacing to start from (e.g. the period of the pattern) instead
    of the one guessed from the gaps.
    """
    xs = np.sort(np.asarray(xs, dtype=float))
    if len(xs) < 2:
        return None
    gaps = np.diff(xs)
    d = float(hint) if hint else _first_guess(gaps)
    if not d > 0:
        return None
    anchor = xs[np.argmin(np.abs(xs - np.median(xs)))]   # a real line near the middle
    x0 = anchor
    keep = np.ones(len(xs), bool)
    for _ in range(iterations):
        n = np.round((xs - x0) / d)
        res = xs - (x0 + n * d)
        new = np.abs(res) <= extra_tol * d
        for k in np.unique(n[new]):                # one line per grid position
            same = np.flatnonzero(new & (n == k))
            if len(same) > 1:
                new[same] = False
                new[same[np.argmin(np.abs(res[same]))]] = True
        if new.sum() < 2 or np.ptp(n[new]) == 0:
            new = keep
            break
        A = np.column_stack([np.ones(new.sum()), n[new]])
        (x0n, dn), *_ = np.linalg.lstsq(A, xs[new], rcond=None)
        done = np.array_equal(new, keep) and abs(dn - d) < 1e-9 * d
        keep, x0, d = new, float(x0n), float(dn)
        if done:
            break
    n = np.round((xs - x0) / d).astype(int)
    lines, idx = xs[keep], n[keep]
    if len(lines) < 2 or idx[-1] == idx[0]:
        return GridFit(float(gaps.mean()), float(xs[0]), list(map(float, xs)),
                       list(range(len(xs))), [], [],
                       float(np.std(gaps, ddof=1)) if len(gaps) > 1 else float("nan"))
    spacing = float((lines[-1] - lines[0]) / (idx[-1] - idx[0]))
    x0 = float(lines[0] - idx[0] * spacing)
    steps = np.diff(idx)
    single = np.diff(lines)[steps == 1]
    present = set(idx.tolist())
    missing = [x0 + k * spacing for k in range(idx[0], idx[-1] + 1) if k not in present]
    return GridFit(spacing, x0, list(map(float, lines)), idx.tolist(),
                   list(map(float, xs[~keep])), [float(x) for x in missing],
                   float(np.std(single, ddof=1)) if len(single) > 1 else float("nan"))


def spacing_stats(xs):
    """(spacing, std, n_lines) of the lines, or None for fewer than 2 lines.

    The spacing comes from fit_grid, so a missed or a false line does not
    change it; with all lines found it is the mean of the gaps. The std is the
    sample std (ddof=1) of the gaps between neighbouring grid positions (NaN
    with fewer than two). n_lines counts every line given, extra ones included.
    """
    fit = fit_grid(xs)
    if fit is None:
        return None
    return fit.spacing, fit.std, len(np.asarray(xs))


def find_video_dir(name, output_dir=None):
    """<output_dir>/video/<name>, or ``name`` itself if it is a folder with lines.csv."""
    output_dir = output_root(output_dir)
    p = Path(name)
    if (p / "lines.csv").exists():
        return p
    d = Path(output_dir) / "video" / Path(name).stem
    if not (d / "lines.csv").exists():
        raise FileNotFoundError(f"No lines.csv in {d}. Run 'analysis video' on '{name}' first.")
    return d


def analyse_spacing(name, output_dir=None):
    """Mean line spacing (error bar = std) against time for an analysed video.

    Reads <output_dir>/video/<name>/lines.csv, writes spacing.csv and spacing.png
    next to it. Frames with fewer than 2 lines are skipped.
    """
    output_dir = output_root(output_dir)
    from .style import BLUE, figure, finish

    d = find_video_dir(name, output_dir)
    rows = []
    for r in read_lines_csv(d / "lines.csv"):
        s = spacing_stats(r["lines"])
        if s is not None:
            rows.append((r["time"], r["frame"], s[2], s[0], s[1]))
    if not rows:
        raise ValueError("No frame has at least 2 lines; nothing to plot.")
    t, frame, n, mean, std = (np.array(c) for c in zip(*rows))

    csv_path = write_csv(d / "spacing.csv",
                         ["time", "frame", "n_lines", "mean_spacing_px", "std_spacing_px"],
                         [(r[0], r[1], r[2], round(r[3], 3),
                           "" if np.isnan(r[4]) else round(r[4], 3)) for r in rows])

    fig, ax = figure(figsize=(9, 5))
    ax.errorbar(t, mean, yerr=np.nan_to_num(std), fmt="o-", color=BLUE, ms=5, lw=1.5,
                elinewidth=1, capsize=3, mec="white", mew=1)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("distance between lines (px)")
    ax.set_title(f"{d.name}: mean spacing, error bar = std of the spacings", loc="left")
    png_path = finish(fig, d / "spacing.png")
    return {"directory": str(d), "frames": len(rows), "time": t.tolist(),
            "mean_spacing": mean.tolist(), "std_spacing": std.tolist(),
            "csv_path": str(csv_path), "plot_path": str(png_path)}
