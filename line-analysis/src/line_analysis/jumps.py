"""Line detection from jumps in the collapsed contrast (``analysis jumps NAME``).

Preparation (first photo, and again whenever you ask for it):
  1. Cut out the middle ``prep_rows`` (300) rows and cut ``edge`` (200) px off
     the left and the right.
  2. Contrast of every pixel, (I - background) / background as in contrast.py,
     collapsed (averaged) over the rows -> one contrast value per x.
  3. Jump between neighbouring pixels, c(x+1) - c(x). Every positive jump larger
     than ``contrast_diff`` is a line (neighbouring pixels over it are one line,
     placed at the largest jump).
  4. The whole photo is saved with the lines as navy blue lines from top to
     bottom and opened; you answer y (keep), n (then + = more lines, - = fewer
     lines, or a new value) or q. After 15 tries it stops by itself. The kept
     contrast_diff and the line positions (initial positions) are used next.

Analysis (every photo, in time order):
  The middle row of the photo and the rows above and below it (``rows`` = 3),
  without the edges, are collapsed and searched for jumps the same way. When a
  photo has a different number of lines than the photo before it (the first
  photo: than the preparation), the marked photo is shown: y = continue with
  the new count, n = run the preparation again on this photo and analyse it
  again, q = stop (the results so far are written).

x positions are those of the whole photo (the cut edge added back). The spacing
of every photo comes from the grid fit (spacing.fit_grid), as in the folder
analysis.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .contrast import ContrastConfig, contrast_profile
from .image import _read_image
from .spacing import fit_grid
from .utils import write_csv

NAVY = (0, 0, 128)
MAX_TRIES = 15


@dataclass
class JumpConfig:
    contrast_diff: float = None   # jump that makes a line; None = suggested from the photo
    edge: int = 200               # px cut off the left and the right
    prep_rows: int = 300          # rows of the preparation strip
    rows: int = 3                 # rows of the analysis strip (middle row +- 1)
    merge: int = 10               # jumps closer than this (px) are one line


def middle_strip(img, rows, edge):
    """``rows`` rows around the middle of the photo, without ``edge`` px left and right."""
    h, w = img.shape[:2]
    if h < rows:
        raise ValueError(f"photo has only {h} rows, {rows} needed")
    if w < 2 * edge + 100:
        raise ValueError(f"photo is only {w} px wide; cannot cut {edge} px off each side")
    r0 = (h - rows) // 2
    return img[r0:r0 + rows, edge:w - edge]


def collapsed_contrast(strip):
    """Contrast of every pixel averaged over the rows -> one value per x."""
    return contrast_profile(strip, ContrastConfig())


def jump_profile(profile):
    """c(x+1) - c(x); entry i is the jump between pixel i and i+1."""
    return np.diff(np.asarray(profile, dtype=float))


def find_jumps(profile, contrast_diff, merge=10):
    """x of the lines: positive jumps > ``contrast_diff``, in strip coordinates.

    Every local maximum of the jumps over the limit is a candidate; the
    largest are taken first, and a candidate closer than ``merge`` px to one
    already taken belongs to that line. A line sits between the two pixels of
    its jump, refined with a parabola.
    """
    d = jump_profile(profile)
    if len(d) < 3:
        return []
    inner = np.flatnonzero((d[1:-1] > contrast_diff) & (d[1:-1] >= d[:-2]) & (d[1:-1] >= d[2:])) + 1
    ends = [i for i in (0, len(d) - 1) if d[i] > contrast_diff]
    cand = np.r_[inner, ends].astype(int)
    taken = []
    for k in cand[np.argsort(-d[cand], kind="stable")]:
        if all(abs(k - t) >= merge for t in taken):
            taken.append(int(k))
    lines = []
    for k in sorted(taken):
        dx = 0.0
        if 0 < k < len(d) - 1:
            a, b, c = d[k - 1], d[k], d[k + 1]
            den = a - 2 * b + c
            if den < 0:
                dx = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
        lines.append(k + 0.5 + dx)
    return lines


def suggest_contrast_diff(profile, k=6.0):
    """A starting value: ``k`` robust sigmas of the jumps (most jumps are noise)."""
    d = jump_profile(profile)
    sigma = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    if sigma == 0:                     # dark photo: most jumps are exactly 0 (whole levels)
        sigma = float(np.std(d))
    return max(k * sigma, 1e-4)


def detect(img, contrast_diff, rows, cfg):
    """Lines (x in the whole photo) in the middle ``rows`` rows of ``img``."""
    strip = middle_strip(img, rows, cfg.edge)
    return [x + cfg.edge for x in find_jumps(collapsed_contrast(strip), contrast_diff, cfg.merge)]


def mark_navy(img, xs, width=None):
    """The whole photo with every x as a navy blue line from top to bottom."""
    marked = np.array(img, dtype=np.uint8, copy=True)
    w = marked.shape[1]
    half = (width or max(3, w // 1000)) // 2           # at least 3 px: visible, survives jpeg
    for x in xs:
        x = int(round(x))
        marked[:, max(0, x - half):min(w, x + half + 1)] = NAVY
    return marked


def save_marked(img, xs, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mark_navy(img, xs)).save(path, quality=92)
    return path


def _describe(xs):
    fit = fit_grid(xs)
    text = f"{len(xs)} lines"
    if fit is not None:
        text += f", spacing {fit.spacing:.1f} px"
        if fit.missing:
            text += f", {len(fit.missing)} missed"
        if fit.extra:
            text += f", {len(fit.extra)} extra"
    return text


def _next_value(value, answer, low, high, factor=1.5):
    """New contrast_diff after '+' (more lines) or '-' (fewer lines).

    ``low`` is the largest value known to give too many lines, ``high`` the
    smallest known to give too few; between two known values the geometric
    middle is taken, else the value moves by ``factor``.
    """
    if answer == "+":
        high = value if high is None else min(high, value)
        new = np.sqrt(low * high) if low is not None else value / factor
    else:
        low = value if low is None else max(low, value)
        new = np.sqrt(low * high) if high is not None else value * factor
    return float(new), low, high


def prepare(photo, img, cfg, out_dir, interactive=True, show=True, ask=input,
            start=None):
    """The preparation on one photo -> (contrast_diff, lines) or None (quit / 15 tries)."""
    from .folder import _show_image
    strip = middle_strip(img, cfg.prep_rows, cfg.edge)
    profile = collapsed_contrast(strip)
    # the value is used on the thin analysis strip too, which is far noisier:
    # the suggestion comes from its noise
    value = start or cfg.contrast_diff or suggest_contrast_diff(
        collapsed_contrast(middle_strip(img, cfg.rows, cfg.edge)))
    low = high = None
    prep_dir = Path(out_dir) / "preparation"
    for attempt in range(1, MAX_TRIES + 1):
        lines = [x + cfg.edge for x in find_jumps(profile, value, cfg.merge)]
        if not interactive:
            return value, lines
        thin = detect(img, value, cfg.rows, cfg)
        path = save_marked(img, lines, prep_dir / f"try{attempt}_{Path(photo).stem}.jpg")
        print(f"\nPreparation, try {attempt} of {MAX_TRIES} on {Path(photo).name}: "
              f"contrast_diff {value:.4g} -> {_describe(lines)}")
        print("  x = " + ", ".join(f"{x:.0f}" for x in lines))
        print(f"  (the {cfg.rows}-row analysis strip of this photo gives {len(thin)} lines "
              "with this value)")
        print(f"  marked photo: {path}")
        if show and not _show_image(path):
            print("  (could not open an image viewer - open the file above yourself)")
        while True:
            answer = ask("Is this okay? [y = yes, n = no, q = quit] ").strip().lower()
            if answer in ("y", "yes", "q", "quit", "n", "no"):
                break
            print("Please answer y, n or q.")
        if answer in ("y", "yes"):
            return value, lines
        if answer in ("q", "quit"):
            return None
        if attempt == MAX_TRIES:
            break
        while True:
            text = ask("+ = more lines, - = fewer lines, or a new contrast_diff "
                       f"(now {value:.4g}), q = quit: ").strip().lower()
            if text in ("q", "quit"):
                return None
            if text in ("+", "-"):
                value, low, high = _next_value(value, text, low, high)
                break
            try:
                new = float(text)
            except ValueError:
                print("Please answer +, - , a number or q.")
                continue
            if new <= 0:
                print("contrast_diff must be larger than 0.")
                continue
            value = new
            break
    print(f"\n{MAX_TRIES} tries without a yes - stopping.")
    return None


LINES_HEADER = ["photo", "file", "n_lines", "contrast_diff", "checked", "x_px"]


def main_jumps(path, output_dir=None, input_dir=None, config=None, interactive=True,
               show=True, ask=input):
    """``analysis jumps NAME``: preparation, then every photo; see the module doc.

    Writes <output_dir>/jumps/<name>/:
      results.csv       as the folder analysis (for analysis report --results)
      lines.csv         photo, file, n_lines, contrast_diff, checked, x_px (all lines)
      parameters.json   the settings and every preparation (photo, contrast_diff, lines)
      preparation/      the marked photos of every preparation try
      <photo>_marked.jpg  every photo with its lines in navy blue
    Returns the result rows ([] if the first preparation was not accepted).
    """
    from .folder import RESULTS_HEADER, _show_image, get_sorted_photos, result_row
    from .logs import resolve_folder
    from .paths import output_root

    cfg = config or JumpConfig()
    output_dir = output_root(output_dir)
    folder = resolve_folder(path, input_dir)
    photos, times = get_sorted_photos(folder, output_dir)
    out_dir = Path(output_dir) / "jumps" / folder.name
    out_dir.mkdir(parents=True, exist_ok=True)

    img = _read_image(photos[0])
    prepared = prepare(photos[0], img, cfg, out_dir, interactive, show, ask)
    if prepared is None:
        print("Nothing was analysed.")
        return []
    value, initial = prepared
    preparations = [{"photo": photos[0].name, "contrast_diff": value,
                     "initial_positions": [round(x, 2) for x in initial]}]
    print(f"\ncontrast_diff {value:.4g}, {len(initial)} initial lines. "
          f"Analysing {len(photos)} photos on the middle {cfg.rows} rows.")

    def write(rows, line_rows):
        params = dict(asdict(cfg), contrast_diff=value, method="jumps",
                      preparations=preparations)
        (out_dir / "parameters.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
        write_csv(out_dir / "lines.csv", LINES_HEADER, line_rows)
        return write_csv(out_dir / "results.csv", RESULTS_HEADER, rows)

    rows, line_rows = [], []
    previous = len(initial)
    for n, photo in enumerate(photos, start=1):
        checked = ""
        try:
            img = img if n == 1 else _read_image(photo)
            lines = detect(img, value, cfg.rows, cfg)
            while interactive and len(lines) != previous:
                marked = save_marked(img, lines, out_dir / f"{photo.stem}_marked.jpg")
                print(f"\n[{n}/{len(photos)}] {photo.name}: {_describe(lines)}, "
                      f"the photo before had {previous}")
                print(f"  marked photo: {marked}")
                if show and not _show_image(marked):
                    print("  (could not open an image viewer - open the file above yourself)")
                answer = ask("Is this okay? [y = yes, n = no (prepare again), q = quit] "
                             ).strip().lower()
                if answer in ("y", "yes"):
                    checked = "accepted"
                    break
                if answer in ("q", "quit"):
                    print("Stopped; the results so far are written.")
                    return _finish(rows, write(rows, line_rows))
                if answer not in ("n", "no"):
                    print("Please answer y, n or q.")
                    continue
                again = prepare(photo, img, cfg, out_dir, interactive, show, ask, start=value)
                if again is None:
                    print("Stopped; the results so far are written.")
                    return _finish(rows, write(rows, line_rows))
                value, initial = again
                preparations.append({"photo": photo.name, "contrast_diff": value,
                                     "initial_positions": [round(x, 2) for x in initial]})
                previous = len(initial)
                checked = "prepared again"
                lines = detect(img, value, cfg.rows, cfg)
            save_marked(img, lines, out_dir / f"{photo.stem}_marked.jpg")
            row = result_row(times[photo], n, photo.name, lines)
            previous = len(lines)
        except Exception as e:
            lines = []
            row = result_row(times[photo], n, photo.name, None, f"failed: {e}")
        rows.append(row)
        line_rows.append((n, photo.name, len(lines), round(value, 6), checked,
                          " ".join(f"{x:.1f}" for x in lines)))
        print(f"[{n}/{len(photos)}] {photo.name}: {_describe(lines)}"
              + (f" ({checked})" if checked else "") + (f" {row[6]}" if row[6] else ""))
    return _finish(rows, write(rows, line_rows))


def _finish(rows, csv_path):
    print(f"Data: {csv_path}")
    print(f"For the report: analysis report NAME --results {csv_path}")
    return rows
