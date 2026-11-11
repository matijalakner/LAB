"""Line detection from jumps in the collapsed contrast (``analysis jumps NAME``).

Preparation (first photo, and again whenever you ask for it):
  1. Cut out the middle ``prep_rows`` (300) rows and cut ``edge`` (200) px off
     the left and the right.
  2. Brightness per pixel: the colour channels weighted by how bright they are
     in this strip; a channel that is nearly black adds only noise and one that
     is saturated has no contrast, so they get (almost) no weight (channel_weights).
  3. Contrast of every pixel, (I - background) / background with the background
     a moving median along x, collapsed (averaged) over the rows -> one value per x.
  4. Jump: c(x + w/2) - c(x - w/2) over ``jump_width`` w px (16 for a 6000 px wide
     photo, scaled with the width; 1 = neighbouring pixels). A real edge is
     spread over several px, so the wider jump collects all of it while the
     noise stays the same.
  5. Every positive jump larger than ``contrast_diff`` noise sigmas is a line
     (sigma = robust spread of the jumps of this strip, so the value means the
     same in bright and in dark photos). Within ``merge`` px only the largest counts.
  6. The whole photo is saved with the lines as navy blue lines from top to
     bottom and opened; you answer y (keep), n (then + = more lines, - = fewer
     lines, or a new value) or q. After 15 tries it stops by itself.

Analysis (every photo, in time order, the first included):
  The middle row of the photo and the rows above and below it (``rows`` = 3),
  without the edges, are collapsed the same way. With tracking (the default)
  each line is searched only within +-``window`` (20 %) of the spacing around
  its position in the photo before (the first photo: the preparation), and
  taken if its jump is over ``min_sigma`` (2) noise sigmas of this strip. Noise
  between the lines cannot become a line. A line that is not found keeps its
  old position for the next photo. New lines are searched beyond the outermost
  ones, where lines come into the picture, at ``contrast_diff`` sigmas.
  When a photo has a different number of lines than the photo before it, the
  marked photo is shown: y = continue with the new count, n = run the
  preparation again on this photo and analyse it again, q = stop (the results
  so far are written).

  Cross-check: the period of the collapsed contrast (its autocorrelation, no
  lines needed) is compared with the spacing; lines.csv has both, and a
  difference over 5 % is printed.

Gap rule (every photo, and the preparation): a distance between neighbouring
lines below half the average distance means a false line: of its two lines the
one whose removal leaves the distances closest to the typical (median) one is excluded,
until no such distance is left. A distance over twice the average (lines
lost) is left out: the lines are split there. The spacing is then the grid fit
(spacing.fit_grid) of every part, together: (sum of their lengths) / (sum of
their grid steps). Excluded lines are not used as positions for the next photo.

x positions are those of the whole photo (the cut edge added back).
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .contrast import ContrastConfig, sizes
from .detect import REF_WIDTH, moving_median
from .image import _read_image
from .spacing import fit_grid
from .utils import write_csv

NAVY = (0, 0, 128)
EXCLUDED = (220, 30, 30)       # dotted: lines excluded by the gap rule
GAP_LOW, GAP_HIGH = 0.5, 2.0   # distances outside this many times the average are excluded
MAX_TRIES = 15
START_SIGMAS = 6.0
SATURATED = 250
PERIOD_TOL = 0.05


@dataclass
class JumpConfig:
    contrast_diff: float = None   # preparation: jump limit in noise sigmas; None = 6
    edge: int = 200               # px cut off the left and the right
    prep_rows: int = 300          # rows of the preparation strip
    rows: int = 3                 # rows of the analysis strip (middle row +- 1)
    merge: int = 25               # jumps closer than this (px) are one line
    jump_width: int = 16          # jump = c(x + w/2) - c(x - w/2); 1 = neighbouring pixels
    channels: str = "auto"        # auto (weighted by brightness), mean, r, g or b
    track: bool = True            # search every line near its previous position
    window: float = 0.2           # +- this fraction of the spacing
    min_sigma: float = 2.0        # analysis: jump of a tracked line, in noise sigmas
    min_rel: float = 0.35         # ... and at least this fraction of the typical line jump
    # merge and jump_width are px of a photo REF_WIDTH (6000 px) wide and scale with the
    # width (jump_width 1 stays 1)


def middle_strip(img, rows, edge):
    """``rows`` rows around the middle of the photo, without ``edge`` px left and right."""
    h, w = img.shape[:2]
    if h < rows:
        raise ValueError(f"photo has only {h} rows, {rows} needed")
    if w < 2 * edge + 100:
        raise ValueError(f"photo is only {w} px wide; cannot cut {edge} px off each side")
    r0 = (h - rows) // 2
    return img[r0:r0 + rows, edge:w - edge]


def channel_weights(strip, mode="auto"):
    """Weights of R, G, B (sum 1) for the brightness.

    auto: each channel by its mean brightness, so a nearly black channel
    (green and blue under red light) adds little noise; a channel with more
    than 5 % saturated pixels gets 0, because it shows no contrast there.
    """
    if mode in ("r", "g", "b"):
        w = np.zeros(3)
        w["rgb".index(mode)] = 1.0
        return w
    if mode == "mean":
        return np.full(3, 1 / 3)
    if mode != "auto":
        raise ValueError("channels must be auto, mean, r, g or b")
    s = np.asarray(strip, dtype=float).reshape(-1, 3)
    w = s.mean(axis=0)
    w[(s >= SATURATED).mean(axis=0) > 0.05] = 0.0
    return w / w.sum() if w.sum() > 0 else np.full(3, 1 / 3)


def collapsed_contrast(strip, weights=None):
    """Contrast of every pixel averaged over the rows -> one value per x."""
    weights = channel_weights(strip) if weights is None else np.asarray(weights, float)
    gray = np.asarray(strip, dtype=np.float32) @ weights.astype(np.float32)
    window = sizes(gray.shape[1], ContrastConfig())[0]
    background = np.stack([moving_median(row, window) for row in gray])
    return ((gray - background) / np.maximum(background, 1.0)).mean(axis=0)


def jump_profile(profile, width=4):
    """(jumps, offset): jumps[i] = c(i + width) - c(i), at x = i + offset (= width / 2)."""
    c = np.asarray(profile, dtype=float)
    width = max(1, int(width))
    return c[width:] - c[:-width], width / 2


def noise_sigma(d):
    """Robust spread of the jumps (most are noise); the std if most are exactly 0."""
    sigma = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    return sigma if sigma > 0 else max(float(np.std(d)), 1e-9)


def _refine(d, k):
    """Sub-pixel position of the maximum at index k (parabola)."""
    if 0 < k < len(d) - 1:
        a, b, c = d[k - 1], d[k], d[k + 1]
        den = a - 2 * b + c
        if den < 0:
            return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return 0.0


def find_jumps(profile, limit, merge=10, width=4, lo=None, hi=None):
    """x of the lines (strip coordinates): positive jumps > ``limit`` (absolute).

    Local maxima of the jumps over the limit are candidates; the largest are
    taken first, and a candidate closer than ``merge`` px to one already taken
    belongs to that line. ``lo`` / ``hi`` limit the search to that x range.
    """
    d, off = jump_profile(profile, width)
    if len(d) < 3:
        return []
    inner = np.flatnonzero((d[1:-1] > limit) & (d[1:-1] >= d[:-2]) & (d[1:-1] >= d[2:])) + 1
    ends = [i for i in (0, len(d) - 1) if d[i] > limit]
    cand = np.r_[inner, ends].astype(int)
    if lo is not None:
        cand = cand[cand + off >= lo]
    if hi is not None:
        cand = cand[cand + off <= hi]
    taken = []
    for k in cand[np.argsort(-d[cand], kind="stable")]:
        if all(abs(k - t) >= merge for t in taken):
            taken.append(int(k))
    return [k + off + _refine(d, k) for k in sorted(taken)]


@dataclass
class Spacing:
    """The spacing of one photo after the gap rule."""
    lines: list                   # lines kept
    excluded: list                # lines excluded (too close to a neighbour)
    long_gaps: list               # (x_left, x_right) of distances over GAP_HIGH x the average
    spacing: float = None
    std: float = float("nan")
    n_missing: int = 0            # missed lines: inside the parts (grid fit) and in long gaps
    n_extra: int = 0              # excluded lines + lines the grid fit put off the grid


def gap_rule(xs, low=GAP_LOW, high=GAP_HIGH):
    """(kept lines, excluded lines, parts): the gap rule, see the module doc."""
    xs = sorted(float(x) for x in xs)
    excluded = []
    while len(xs) >= 3:
        gaps = np.diff(xs)
        avg = gaps.mean()
        i = int(np.argmin(gaps))
        if gaps[i] >= low * avg:
            break

        typical = float(np.median(gaps))   # not pulled by the short distance itself

        def score(j):                      # distance closest to typical after removing xs[j]
            if 0 < j < len(xs) - 1:
                return abs(xs[j + 1] - xs[j - 1] - typical)
            other = xs[2] - xs[1] if j == 0 else xs[-2] - xs[-3]
            return abs(other - typical)
        j = i if score(i) <= score(i + 1) else i + 1
        excluded.append(xs.pop(j))
    parts = [xs[:1]] if xs else []
    if len(xs) >= 2:
        avg = float(np.mean(np.diff(xs)))
        for a, b in zip(xs, xs[1:]):
            if b - a > high * avg:
                parts.append([b])
            else:
                parts[-1].append(b)
    return xs, sorted(excluded), parts


def spacing_with_rule(xs, low=GAP_LOW, high=GAP_HIGH):
    """Spacing (grid fit of the parts between long gaps) -> Spacing."""
    kept, excluded, parts = gap_rule(xs, low, high)
    res = Spacing(kept, excluded, [(p[-1], q[0]) for p, q in zip(parts, parts[1:])])
    span = steps = 0.0
    single, extra, missing = [], 0, 0
    for part in parts:
        fit = fit_grid(part)
        if fit is None or len(fit.lines) < 2:
            continue
        n = fit.index[-1] - fit.index[0]
        if n <= 0:
            continue
        span += fit.lines[-1] - fit.lines[0]
        steps += n
        idx = np.asarray(fit.index)
        single += list(np.diff(fit.lines)[np.diff(idx) == 1])
        extra += len(fit.extra)
        missing += len(fit.missing)
    if steps:
        res.spacing = span / steps
        res.std = float(np.std(single, ddof=1)) if len(single) > 1 else float("nan")
        missing += sum(max(0, int(round((b - a) / res.spacing)) - 1) for a, b in res.long_gaps)
    res.n_missing, res.n_extra = missing, len(excluded) + extra
    return res


def _spacing_of(xs):
    fit = fit_grid(xs)
    if fit is not None:
        return fit.spacing
    return None


def track_jumps(profile, reference, cfg, new_limit):
    """Lines near ``reference`` (strip x) -> (found, next_reference, sigma).

    Every reference line is searched within +- cfg.window * spacing for its
    largest jump; it is found if that is over cfg.min_sigma noise sigmas and
    over cfg.min_rel of the median of all these largest jumps (in a bright
    photo the lines are far above the noise, so an empty window is not filled
    with a noise peak; in a dark one the sigma limit decides).
    Beyond the outermost reference lines (by more than half a spacing) new
    lines over ``new_limit`` sigmas are added. The next reference is the found
    lines plus the old positions of the lines not found.
    """
    d, off = jump_profile(profile, cfg.jump_width)
    sigma = noise_sigma(d)
    spacing = _spacing_of(reference)
    if not spacing:
        found = find_jumps(profile, new_limit * sigma, cfg.merge, cfg.jump_width)
        return found, found, sigma
    half = cfg.window * spacing
    best = []                                     # (reference x, index of the largest jump)
    for x in reference:
        lo, hi = int(np.floor(x - half - off)), int(np.ceil(x + half - off))
        lo, hi = max(lo, 0), min(hi, len(d) - 1)
        best.append((x, None if hi < lo else lo + int(np.argmax(d[lo:hi + 1]))))
    peaks = [d[k] for _, k in best if k is not None]
    need = max(cfg.min_sigma * sigma, cfg.min_rel * float(np.median(peaks)) if peaks else 0.0)
    found, keep = [], []
    for x, k in best:
        if k is not None and d[k] > need:
            found.append(k + off + _refine(d, k))
        else:
            keep.append(x)
    edge_lo, edge_hi = min(reference) - 0.5 * spacing, max(reference) + 0.5 * spacing
    limit = new_limit * sigma
    found += find_jumps(profile, limit, cfg.merge, cfg.jump_width, hi=edge_lo)
    found += find_jumps(profile, limit, cfg.merge, cfg.jump_width, lo=edge_hi)
    found = sorted(found)
    return found, sorted(found + keep), sigma


def period(profile, expected):
    """Period of the profile from its autocorrelation, near ``expected`` px (or None)."""
    if not expected:
        return None
    c = np.asarray(profile, dtype=float)
    c = c - c.mean()
    n = len(c)
    lo, hi = int(0.6 * expected), int(min(1.6 * expected, n // 2))
    if hi - lo < 3 or lo < 2:
        return None
    ac = np.array([np.dot(c[:n - k], c[k:]) / (n - k) for k in range(lo - 1, hi + 2)])
    k = int(np.argmax(ac[1:-1])) + 1
    if not (ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1]) or ac[k] <= 0:
        return None
    return lo - 1 + k + _refine(ac, k)


def mark_navy(img, xs, width=None):
    """The whole photo with every x as a navy blue line from top to bottom."""
    marked = np.array(img, dtype=np.uint8, copy=True)
    w = marked.shape[1]
    half = (width or max(3, w // 1000)) // 2           # at least 3 px: visible, survives jpeg
    for x in xs:
        x = int(round(x))
        marked[:, max(0, x - half):min(w, x + half + 1)] = NAVY
    return marked


def save_marked(img, xs, path, excluded=()):
    """The marked photo (navy lines; ``excluded`` lines dotted red) as JPEG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    marked = mark_navy(img, xs)
    w = marked.shape[1]
    half = max(3, w // 1000) // 2
    for x in excluded:
        x = int(round(x))
        for r0 in range(0, marked.shape[0], 16):           # dashes, 8 px on, 8 px off
            marked[r0:r0 + 8, max(0, x - half):min(w, x + half + 1)] = EXCLUDED
    Image.fromarray(marked).save(path, quality=92)
    return path


def _describe(sp):
    """Text for a Spacing (or a list of lines, which gets the gap rule first)."""
    if not isinstance(sp, Spacing):
        sp = spacing_with_rule(sp)
    text = f"{len(sp.lines)} lines"
    if sp.spacing is not None:
        text += f", spacing {sp.spacing:.1f} px"
    if sp.excluded:
        text += f", {len(sp.excluded)} excluded (too close)"
    if sp.long_gaps:
        text += f", {len(sp.long_gaps)} distance(s) over {GAP_HIGH:g}x left out"
    if sp.n_missing:
        text += f", {sp.n_missing} missed"
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


class Analyser:
    """The detection of one series: settings, channel weights and contrast_diff."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.weights = None
        self.value = cfg.contrast_diff or START_SIGMAS

    def sizes(self, img):
        """(jump_width, merge) in px for this photo's width."""
        s = img.shape[1] / REF_WIDTH
        jw = 1 if self.cfg.jump_width <= 1 else max(2, int(round(self.cfg.jump_width * s)))
        return jw, max(3, int(round(self.cfg.merge * s)))

    def _cfg(self, img):
        from dataclasses import replace
        jw, merge = self.sizes(img)
        return replace(self.cfg, jump_width=jw, merge=merge)

    def strip_profile(self, img, rows):
        return collapsed_contrast(middle_strip(img, rows, self.cfg.edge), self.weights)

    def prep_lines(self, img, value):
        """(lines in whole-photo x, sigma) of the preparation strip at ``value`` sigmas."""
        cfg = self._cfg(img)
        profile = self.strip_profile(img, cfg.prep_rows)
        sigma = noise_sigma(jump_profile(profile, cfg.jump_width)[0])
        xs = find_jumps(profile, value * sigma, cfg.merge, cfg.jump_width)
        return [x + cfg.edge for x in xs], sigma

    def lines(self, img, reference):
        """(lines, next reference, period) of the analysis strip, whole-photo x."""
        cfg = self._cfg(img)
        profile = self.strip_profile(img, cfg.rows)
        ref = [x - cfg.edge for x in reference] if reference else []
        if cfg.track and len(ref) >= 2:
            found, nxt, _ = track_jumps(profile, ref, cfg, self.value)
        else:
            d, _ = jump_profile(profile, cfg.jump_width)
            found = find_jumps(profile, self.value * noise_sigma(d), cfg.merge, cfg.jump_width)
            nxt = found
        p = period(profile, _spacing_of(found) or _spacing_of(ref))
        return [x + cfg.edge for x in found], [x + cfg.edge for x in nxt], p


def prepare(photo, img, an, out_dir, interactive=True, show=True, ask=input):
    """The preparation on one photo -> lines (whole-photo x), or None (quit / 15 tries).

    Sets ``an.weights`` (from this photo) and ``an.value`` (the kept contrast_diff).
    """
    from .folder import _show_image
    cfg = an.cfg
    an.weights = channel_weights(middle_strip(img, cfg.prep_rows, cfg.edge), cfg.channels)
    value = an.value
    low = high = None
    prep_dir = Path(out_dir) / "preparation"
    for attempt in range(1, MAX_TRIES + 1):
        found, sigma = an.prep_lines(img, value)
        sp = spacing_with_rule(found)
        lines = sp.lines
        an.value = value
        if not interactive:
            return lines
        thin, _, _ = an.lines(img, lines)
        path = save_marked(img, lines, prep_dir / f"try{attempt}_{Path(photo).stem}.jpg",
                           sp.excluded)
        print(f"\nPreparation, try {attempt} of {MAX_TRIES} on {Path(photo).name}: "
              f"contrast_diff {value:.3g} sigma (= {value * sigma:.4g}) -> {_describe(sp)}")
        print("  channels R, G, B weighted " + ", ".join(f"{w:.2f}" for w in an.weights))
        print("  x = " + ", ".join(f"{x:.0f}" for x in lines))
        print(f"  (the {cfg.rows}-row analysis strip of this photo then finds "
              f"{len(spacing_with_rule(thin).lines)} lines)")
        print(f"  marked photo: {path}")
        if show and not _show_image(path):
            print("  (could not open an image viewer - open the file above yourself)")
        while True:
            answer = ask("Is this okay? [y = yes, n = no, q = quit] ").strip().lower()
            if answer in ("y", "yes", "q", "quit", "n", "no"):
                break
            print("Please answer y, n or q.")
        if answer in ("y", "yes"):
            return lines
        if answer in ("q", "quit"):
            return None
        if attempt == MAX_TRIES:
            break
        while True:
            text = ask("+ = more lines, - = fewer lines, or a new contrast_diff in sigmas "
                       f"(now {value:.3g}), q = quit: ").strip().lower()
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


LINES_HEADER = ["photo", "file", "n_lines", "contrast_diff", "checked", "period_px",
                "period_vs_spacing_pct", "x_px", "excluded_x", "long_gaps"]


def _row(time_info, n, name, sp, warning=""):
    """results.csv row (folder.RESULTS_HEADER) from a Spacing."""
    mean = std = ""
    if sp.spacing is None:
        warning = "; ".join(w for w in (warning, "fewer than 2 lines") if w)
    else:
        mean = round(sp.spacing, 3)
        std = "" if np.isnan(sp.std) else round(sp.std, 3)
    return (time_info[0], n, name, mean, len(sp.lines), std, warning, time_info[1],
            sp.n_missing, sp.n_extra)


def main_jumps(path, output_dir=None, input_dir=None, config=None, interactive=True,
               show=True, ask=input):
    """``analysis jumps NAME``: preparation, then every photo; see the module doc.

    Writes <output_dir>/jumps/<name>/:
      results.csv       as the folder analysis (for analysis report --results)
      lines.csv         photo, file, n_lines, contrast_diff, checked, period_px,
                        period_vs_spacing_pct, x_px (all lines)
      parameters.json   the settings and every preparation (photo, contrast_diff,
                        channel weights, initial positions)
      preparation/      the marked photos of every preparation try
      <photo>_marked.jpg  every photo with its lines in navy blue
    Returns the result rows ([] if the first preparation was not accepted).
    """
    from .folder import RESULTS_HEADER, _show_image, get_sorted_photos, result_row
    from .logs import resolve_folder
    from .paths import output_root

    cfg = config or JumpConfig()
    an = Analyser(cfg)
    output_dir = output_root(output_dir)
    folder = resolve_folder(path, input_dir)
    photos, times = get_sorted_photos(folder, output_dir)
    out_dir = Path(output_dir) / "jumps" / folder.name
    out_dir.mkdir(parents=True, exist_ok=True)

    img = _read_image(photos[0])
    initial = prepare(photos[0], img, an, out_dir, interactive, show, ask)
    if initial is None:
        print("Nothing was analysed.")
        return []
    preparations = []

    def note_preparation(photo, lines):
        preparations.append({"photo": photo.name, "contrast_diff_sigma": an.value,
                             "channel_weights": [round(float(w), 4) for w in an.weights],
                             "initial_positions": [round(x, 2) for x in lines]})

    note_preparation(photos[0], initial)
    print(f"\ncontrast_diff {an.value:.3g} sigma, {len(initial)} initial lines. Analysing "
          f"{len(photos)} photos on the middle {cfg.rows} rows"
          + (f", each line searched within +-{cfg.window:.0%} of the spacing"
             if cfg.track else "") + ".")

    def write(rows, line_rows):
        params = dict(asdict(cfg), contrast_diff=an.value, method="jumps",
                      preparations=preparations)
        (out_dir / "parameters.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
        write_csv(out_dir / "lines.csv", LINES_HEADER, line_rows)
        return write_csv(out_dir / "results.csv", RESULTS_HEADER, rows)

    rows, line_rows = [], []
    previous, reference = len(initial), initial
    for n, photo in enumerate(photos, start=1):
        checked, per, diff = "", None, None
        try:
            img = img if n == 1 else _read_image(photo)
            found, nxt, per = an.lines(img, reference)
            sp = spacing_with_rule(found)
            while interactive and len(sp.lines) != previous:
                marked = save_marked(img, sp.lines, out_dir / f"{photo.stem}_marked.jpg",
                                     sp.excluded)
                print(f"\n[{n}/{len(photos)}] {photo.name}: {_describe(sp)}, "
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
                again = prepare(photo, img, an, out_dir, interactive, show, ask)
                if again is None:
                    print("Stopped; the results so far are written.")
                    return _finish(rows, write(rows, line_rows))
                note_preparation(photo, again)
                previous, reference = len(again), again
                checked = "prepared again"
                found, nxt, per = an.lines(img, reference)
                sp = spacing_with_rule(found)
            save_marked(img, sp.lines, out_dir / f"{photo.stem}_marked.jpg", sp.excluded)
            row = _row(times[photo], n, photo.name, sp)
            previous = len(sp.lines)
            drop = set(sp.excluded)
            reference = [x for x in nxt if x not in drop]          # excluded: not followed
            if per and sp.spacing:
                diff = 100 * (per / sp.spacing - 1)
        except Exception as e:
            sp = Spacing([], [], [])
            row = result_row(times[photo], n, photo.name, None, f"failed: {e}")
        rows.append(row)
        line_rows.append((n, photo.name, len(sp.lines), round(an.value, 4), checked,
                          "" if per is None else round(per, 2),
                          "" if diff is None else round(diff, 1),
                          " ".join(f"{x:.1f}" for x in sp.lines),
                          " ".join(f"{x:.1f}" for x in sp.excluded),
                          " ".join(f"{a:.0f}-{b:.0f}" for a, b in sp.long_gaps)))
        flag = (f"; period {per:.1f} px differs by {diff:+.0f} %"
                if diff is not None and abs(diff) > 100 * PERIOD_TOL else "")
        print(f"[{n}/{len(photos)}] {photo.name}: {_describe(sp)}"
              + (f" ({checked})" if checked else "") + (f" {row[6]}" if row[6] else "") + flag)
    return _finish(rows, write(rows, line_rows))


def _finish(rows, csv_path):
    print(f"Data: {csv_path}")
    print(f"For the report: analysis report NAME --results {csv_path}")
    return rows
