"""Line spacing over time, from the lines.csv written by process_video."""
from .paths import output_root
import csv
import json
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


def spacing_stats(xs):
    """(mean, std, n_lines) of the distances between neighbouring lines, or None.

    Needs at least 2 lines. The std is the sample std (ddof=1) of the individual
    spacings, so it is NaN when there is only one spacing.
    """
    xs = np.sort(np.asarray(xs, dtype=float))
    if len(xs) < 2:
        return None
    d = np.diff(xs)
    std = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    return float(d.mean()), std, len(xs)


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
