"""Line detection in a thin strip of every photo (``analysis jumps NAME``).

Preparation (first photo, and again whenever you ask for it):
  1. Cut out the middle ``prep_rows`` (300) rows and cut ``edge`` (200) px off
     the left and the right.
  2. Brightness per pixel: the colour channels weighted by how bright they are
     in this strip; a channel that is nearly black adds only noise and one that
     is saturated has no contrast, so they get (almost) no weight (channel_weights).
  3. Contrast of every pixel, (I - background) / background with the background
     a moving median along x, collapsed (averaged) over the rows -> one value per x.
  4. Jump: c(x + w/2) - c(x - w/2) over ``jump_width`` w px (16 for a 6000 px wide
     photo, scaled with the width; 1 = neighbouring pixels).
  5. Every positive jump larger than ``contrast_diff`` noise sigmas is a line
     (sigma = robust spread of the jumps of this strip). Within ``merge`` px only
     the largest counts. Then the gap rule (below).
  6. The whole photo is saved with the lines as navy blue lines from top to
     bottom and opened; you answer y (keep), n (then + = more lines, - = fewer
     lines, or a new value) or q. After 15 tries it stops by itself.
  7. Template: the collapsed contrast around the kept lines, averaged over all
     of them: what a line looks like in this series.

Analysis (every photo, in time order, the first included), detector "template":
  The middle row and the rows above and below it (``rows`` = 3), without the
  edges, are collapsed the same way, and the template is slid along it
  (matched filter): lines are where it fits best. This uses the whole shape
  of a line (dip and rise), not one difference, so faint lines stand out
  better from the noise.
  1. Period: the autocorrelation of the filtered profile near the spacing of
     the photo before.
  2. Prediction: the lines of the photo before, stretched by (period / spacing
     before) and shifted, as a whole, to where the filtered profile is highest.
  3. Every predicted line is refined within +-``window`` (15 %) of the period;
     it is found if the filter there is over ``min_sigma`` noise sigmas and over
     ``min_rel`` of the typical line. Beyond the outer lines the grid is
     extended; a line there needs ``contrast_diff`` sigmas.
  4. Gap rule and grid fit -> spacing and its error (spacing_err_px).
  5. Quality: the photo is doubtful when the lines are weak (median filter
     value under ``q_snr`` sigmas), fewer than ``q_coverage`` of the predicted
     lines are found, the lines are far off a regular grid (rms over
     ``q_residual`` of the spacing), the period and the spacing disagree by over
     ``q_period``, or the spacing jumped by over ``q_jump`` from the photo before.
  Detector "threshold" is the previous one: each line searched within +-20 %
  of the spacing for its largest jump.

Asking (``ask``):
  doubtful (default)  a doubtful photo is shown: y = keep it, n = prepare again
                      on it and measure it again, q = stop (results written)
  count               as before: when the number of lines changes
  review              nothing during the run; afterwards an overview of the
                      spacing (overview.png) and every doubtful photo is shown:
                      y = keep, x = exclude (warning, left out of the report),
                      p = prepare again on it and measure it again, q = stop
  --yes asks nothing (the first preparation is kept).

Gap rule (every photo and the preparation): a distance between neighbouring
lines below half the average distance means a false line (the average of the
normal distances, average_gap: a big hole or a false line does not pull it): of its two lines the
one whose removal leaves the distances closest to the typical (median) one is
excluded, until no such distance is left. A distance over twice the average
(lines lost) is left out: the lines are split there. The spacing is then the
grid fit (spacing.fit_grid) of every part, together: (sum of their lengths) /
(sum of their grid steps). Excluded lines are not followed in the next photo.

x positions are those of the whole photo (the cut edge added back).
"""
import json
from dataclasses import asdict, dataclass, field, replace
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
    contrast_diff: float = None   # preparation and new edge lines: limit in noise sigmas; None = 6
    edge: int = 200               # px cut off the left and the right
    prep_rows: int = 300          # rows of the preparation strip
    rows: int = 3                 # rows of the analysis strip (middle row +- 1)
    merge: int = 25               # jumps closer than this (px) are one line
    jump_width: int = 16          # jump = c(x + w/2) - c(x - w/2); 1 = neighbouring pixels
    channels: str = "auto"        # auto (weighted by brightness), mean, r, g or b
    detector: str = "template"    # template (matched filter + prediction) or threshold
    track: bool = True            # threshold detector: search near the previous lines
    window: float = None          # search +- this fraction of the spacing; None = 0.15
                                  # (template) / 0.2 (threshold)
    min_sigma: float = 2.0        # a tracked line: over this many noise sigmas ...
    min_rel: float = 0.35         # ... and over this fraction of the typical line
    ask: str = "doubtful"         # doubtful | count | review
    q_snr: float = 3.0            # quality limits, see the module doc
    q_coverage: float = 0.6
    q_residual: float = 0.15
    q_period: float = 0.05
    q_jump: float = 0.08
    stretch: float = 0.04         # the row of lines may stretch +- this much per photo
    stretch_from_period: bool = False
    # merge and jump_width are px of a photo REF_WIDTH (6000 px) wide and scale with the
    # width (jump_width 1 stays 1)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
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
    """Robust spread (most values are noise); the std if most are exactly 0."""
    d = np.asarray(d, dtype=float)
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
    return [k + off for k in _peaks(d, limit, merge, lo - off if lo is not None else None,
                                    hi - off if hi is not None else None)]


def _peaks(d, limit, merge, lo=None, hi=None):
    """Sub-pixel indices of local maxima of ``d`` over ``limit``, strongest first, >= merge apart."""
    if len(d) < 3:
        return []
    inner = np.flatnonzero((d[1:-1] > limit) & (d[1:-1] >= d[:-2]) & (d[1:-1] >= d[2:])) + 1
    ends = [i for i in (0, len(d) - 1) if d[i] > limit]
    cand = np.r_[inner, ends].astype(int)
    if lo is not None:
        cand = cand[cand >= lo]
    if hi is not None:
        cand = cand[cand <= hi]
    taken = []
    for k in cand[np.argsort(-d[cand], kind="stable")]:
        if all(abs(k - t) >= merge for t in taken):
            taken.append(int(k))
    return [k + _refine(d, k) for k in sorted(taken)]


def period(profile, expected, lo=0.6, hi=1.6):
    """Period of the profile from its autocorrelation, near ``expected`` px (or None)."""
    if not expected:
        return None
    c = np.asarray(profile, dtype=float)
    c = c - c.mean()
    n = len(c)
    a, b = int(lo * expected), int(min(hi * expected, n // 2))
    if b - a < 3 or a < 2:
        return None
    ac = np.array([np.dot(c[:n - k], c[k:]) / (n - k) for k in range(a - 1, b + 2)])
    k = int(np.argmax(ac[1:-1])) + 1
    if not (ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1]) or ac[k] <= 0:
        return None
    return a - 1 + k + _refine(ac, k)


# ---------------------------------------------------------------------------
# gap rule and spacing
# ---------------------------------------------------------------------------
@dataclass
class Spacing:
    """The spacing of one photo after the gap rule."""
    lines: list                   # lines kept
    excluded: list                # lines excluded (too close to a neighbour)
    long_gaps: list               # (x_left, x_right) of distances over GAP_HIGH x the average
    spacing: float = None
    std: float = float("nan")
    err: float = float("nan")     # uncertainty of the spacing (from the grid fit)
    residual: float = float("nan")  # rms distance of the lines from the grid, px
    n_missing: int = 0            # missed lines: inside the parts (grid fit) and in long gaps
    n_extra: int = 0              # excluded lines + lines the grid fit put off the grid


def average_gap(gaps, low=GAP_LOW, high=GAP_HIGH):
    """The average of the normal distances: starting from the median, distances
    outside low..high times the current average are left out of it. Without
    outliers it is the plain mean; a big hole (many lines lost) or a false
    line cannot pull it, so the rule below does not turn on good lines."""
    gaps = np.asarray(gaps, dtype=float)
    avg = float(np.median(gaps))
    for _ in range(10):
        normal = gaps[(gaps >= low * avg) & (gaps <= high * avg)]
        new = float(normal.mean()) if len(normal) else avg
        if abs(new - avg) < 1e-9 * avg:
            break
        avg = new
    return avg


def gap_rule(xs, low=GAP_LOW, high=GAP_HIGH):
    """(kept lines, excluded lines, parts): the gap rule, see the module doc."""
    xs = sorted(float(x) for x in xs)
    excluded = []
    while len(xs) >= 3:
        gaps = np.diff(xs)
        avg = average_gap(gaps, low, high)
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
        avg = average_gap(np.diff(xs), low, high)
        for a, b in zip(xs, xs[1:]):
            if b - a > high * avg:
                parts.append([b])
            else:
                parts[-1].append(b)
    return xs, sorted(excluded), parts


def spacing_with_rule(xs, low=GAP_LOW, high=GAP_HIGH, hint=None):
    """Spacing (grid fit of the parts between long gaps) -> Spacing.

    ``hint``: expected spacing (the period), the start of every grid fit.
    """
    kept, excluded, parts = gap_rule(xs, low, high)
    res = Spacing(kept, excluded, [(p[-1], q[0]) for p, q in zip(parts, parts[1:])])
    span = steps = 0.0
    single, extra, missing = [], 0, 0
    fits = []
    for part in parts:
        fit = fit_grid(part, hint=hint)
        if fit is None or len(fit.lines) < 2:
            continue
        n = fit.index[-1] - fit.index[0]
        if n <= 0:
            continue
        fits.append(fit)
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
        # uncertainty of the slope of x = x0 + i * spacing (pooled over the parts)
        resid, sxx, n_pts = [], 0.0, 0
        for fit in fits:
            i = np.asarray(fit.index, float)
            x = np.asarray(fit.lines)
            A = np.column_stack([np.ones_like(i), i])
            coef, *_ = np.linalg.lstsq(A, x, rcond=None)
            resid += list(x - A @ coef)
            sxx += float(((i - i.mean()) ** 2).sum())
            n_pts += len(x)
        dof = n_pts - 2 * len(fits)
        if dof > 0 and sxx > 0:
            s_r = float(np.sqrt(np.sum(np.square(resid)) / dof))
            res.err = s_r / np.sqrt(sxx)
            res.residual = s_r
    res.n_missing, res.n_extra = missing, len(excluded) + extra
    return res


def _spacing_of(xs):
    fit = fit_grid(xs)
    return fit.spacing if fit is not None else None


# ---------------------------------------------------------------------------
# threshold detector (previous)
# ---------------------------------------------------------------------------
def track_jumps(profile, reference, cfg, new_limit):
    """Lines near ``reference`` (strip x) -> (found, next_reference, sigma).

    Every reference line is searched within +- window * spacing for its
    largest jump; it is found if that is over cfg.min_sigma noise sigmas and
    over cfg.min_rel of the median of all these largest jumps. Beyond the
    outermost reference lines (by more than half a spacing) new lines over
    ``new_limit`` sigmas are added. The next reference is the found lines plus
    the old positions of the lines not found.
    """
    d, off = jump_profile(profile, cfg.jump_width)
    sigma = noise_sigma(d)
    spacing = _spacing_of(reference)
    if not spacing:
        found = find_jumps(profile, new_limit * sigma, cfg.merge, cfg.jump_width)
        return found, found, sigma
    half = (cfg.window or 0.2) * spacing
    best = []
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


# ---------------------------------------------------------------------------
# template detector
# ---------------------------------------------------------------------------
def make_template(profile, lines, spacing, half_frac=0.3):
    """Mean of the profile around the lines (strip x) -> (template, half width).

    The template is zero-mean with unit length, so the filtered profile is in
    the units of the profile; index ``half`` is the line position.
    """
    half = max(3, int(round(half_frac * spacing)))
    k = np.arange(-half, half + 1)
    xs = np.arange(len(profile))
    segs = [np.interp(x + k, xs, profile) for x in lines if half <= x < len(profile) - half]
    if not segs:
        return None, half
    t = np.mean(segs, axis=0)
    t = t - t.mean()
    norm = np.linalg.norm(t)
    return (t / norm if norm > 0 else None), half


def matched(profile, template):
    """Filtered profile: m[x] = sum_k template[k] * profile[x - half + k]."""
    half = len(template) // 2
    c = np.pad(np.asarray(profile, float), half, mode="edge")
    return np.correlate(c, template, mode="valid")


def _value_at(m, x):
    return np.interp(x, np.arange(len(m)), m)


@dataclass
class Measurement:
    lines: list                   # found lines (whole-photo x), before the gap rule
    spacing: Spacing
    reference: list               # positions to follow in the next photo
    period: float = None
    snr: float = float("nan")     # median filter (or jump) value of the lines, in sigmas
    coverage: float = float("nan")  # found / predicted lines
    jump: float = float("nan")    # spacing change from the photo before
    doubts: list = field(default_factory=list)

    @property
    def doubtful(self):
        return bool(self.doubts)


class Analyser:
    """The detection of one series: settings, channel weights, template, reference."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.weights = None
        self.value = cfg.contrast_diff or START_SIGMAS
        self.template = None
        self.half = None
        self.reference = []        # whole-photo x
        self.spacing = None        # spacing of the photo before

    # sizes ------------------------------------------------------------------
    def sizes(self, img):
        """(jump_width, merge) in px for this photo's width."""
        s = img.shape[1] / REF_WIDTH
        jw = 1 if self.cfg.jump_width <= 1 else max(2, int(round(self.cfg.jump_width * s)))
        return jw, max(3, int(round(self.cfg.merge * s)))

    def _cfg(self, img):
        jw, merge = self.sizes(img)
        return replace(self.cfg, jump_width=jw, merge=merge)

    def strip_profile(self, img, rows):
        return collapsed_contrast(middle_strip(img, rows, self.cfg.edge), self.weights)

    # preparation ------------------------------------------------------------
    def set_weights(self, img):
        self.weights = channel_weights(middle_strip(img, self.cfg.prep_rows, self.cfg.edge),
                                       self.cfg.channels)

    def prep_lines(self, img, value):
        """(lines in whole-photo x, sigma) of the preparation strip at ``value`` sigmas."""
        cfg = self._cfg(img)
        profile = self.strip_profile(img, cfg.prep_rows)
        sigma = noise_sigma(jump_profile(profile, cfg.jump_width)[0])
        xs = find_jumps(profile, value * sigma, cfg.merge, cfg.jump_width)
        return [x + cfg.edge for x in xs], sigma

    def set_reference(self, img, lines):
        """Start following ``lines`` (accepted in the preparation of ``img``)."""
        self.reference = sorted(lines)
        sp = spacing_with_rule(lines)
        self.spacing = sp.spacing
        self.template = None
        if self.cfg.detector == "template" and sp.spacing:
            profile = self.strip_profile(img, self.cfg.prep_rows)
            self.template, self.half = make_template(
                profile, [x - self.cfg.edge for x in sp.lines], sp.spacing)

    # analysis ----------------------------------------------------------------
    def lines(self, img, reference):
        """(lines, next reference, period) for the threshold detector (whole-photo x)."""
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

    def _template_lines(self, img):
        """(found, next reference, period, snr, coverage), strip x, template detector."""
        cfg = self._cfg(img)
        profile = self.strip_profile(img, cfg.rows)
        m = matched(profile, self.template)
        sigma = noise_sigma(m)
        ref = np.array([x - cfg.edge for x in self.reference], float)
        prev = self.spacing or _spacing_of(ref)
        if len(ref) < 2 or not prev:
            found = [k for k in _peaks(m, self.value * sigma, cfg.merge)]
            return found, [], period(m, _spacing_of(found)), np.nan, np.nan, None
        # 1. period, 2. stretch + shift of the whole row of lines
        per = period(m, prev, 0.75, 1.33)
        # the stretch is searched around the spacing before and, when the period
        # of the pattern says the spacing moved further, around the period too;
        # the better fit wins (the period of a noisy strip must not lead alone)
        centres = [1.0]
        if per and abs(per / prev - 1) > self.cfg.stretch and abs(per / prev - 1) < 0.25:
            centres.append(per / prev)
        if self.cfg.stretch_from_period and per and abs(per / prev - 1) < 0.25:
            centres = [per / prev]
        centre = float(np.median(ref))
        best = (-np.inf, 1.0, 0.0)
        for a0 in centres:
            p_now = a0 * prev
            shifts = np.arange(-0.5 * p_now, 0.5 * p_now + 1, 1.0)
            for a in a0 * np.linspace(1 - self.cfg.stretch, 1 + self.cfg.stretch, 17):
                pred = centre + a * (ref - centre)
                inside = (pred > 0) & (pred < len(m) - 1)
                if inside.sum() < 2:
                    continue
                vals = np.array([_value_at(m, pred[inside] + b).mean() for b in shifts])
                j = int(np.argmax(vals))
                if vals[j] > best[0]:
                    best = (vals[j], a, float(shifts[j]))
        _, a, b = best
        pred = centre + a * (ref - centre) + b
        spacing_now = a * prev
        # extend the grid beyond the outer lines
        ext = []
        x = pred.min() - spacing_now
        while x > 0:
            ext.append(x)
            x -= spacing_now
        x = pred.max() + spacing_now
        while x < len(m) - 1:
            ext.append(x)
            x += spacing_now
        # 3. refine every predicted line in its window
        half = (cfg.window or 0.15) * spacing_now

        def window_max(x):
            lo, hi = int(np.floor(x - half)), int(np.ceil(x + half))
            lo, hi = max(lo, 0), min(hi, len(m) - 1)
            if hi < lo:
                return None
            k = lo + int(np.argmax(m[lo:hi + 1]))
            return k + _refine(m, k), m[k]

        cand = [(x, window_max(x)) for x in pred]
        peaks = [v for _, w in cand if w for v in [w[1]]]
        need = max(cfg.min_sigma * sigma, cfg.min_rel * float(np.median(peaks)) if peaks else 0)
        found, nxt, vals = [], [], []
        inside = 0
        for x, w in cand:
            if not 0 <= x <= len(m) - 1:
                nxt.append(x)                    # out of the picture: keep following it
                continue
            inside += 1
            if w and w[1] > need:
                found.append(w[0])
                vals.append(w[1])
                nxt.append(w[0])
            else:
                nxt.append(x)                    # predicted position
        new_need = max(need, self.value * sigma)
        for x in ext:
            w = window_max(x)
            if w and w[1] > new_need and all(abs(w[0] - f) > 0.5 * spacing_now for f in found):
                found.append(w[0])
                vals.append(w[1])
                nxt.append(w[0])
        snr = float(np.median(vals) / sigma) if vals else 0.0
        coverage = len(vals) / max(inside, 1) if inside else 0.0
        outside = [x for x in pred if not 0 <= x <= len(m) - 1]
        return sorted(found), outside, per, snr, min(coverage, 1.0), spacing_now

    def measure(self, img):
        """Measure one photo -> Measurement (also moves the reference on)."""
        cfg = self.cfg
        snr = coverage = np.nan
        if cfg.detector == "template" and self.template is not None:
            found, outside, per, snr, coverage, expected = self._template_lines(img)
            found = [x + cfg.edge for x in found]
            outside = [x + cfg.edge for x in outside]
            # the period is the best guess of the grid; the lines are then counted on it
            hint = per if per and expected and abs(per / expected - 1) < 0.2 else expected
            sp = spacing_with_rule(found, hint=hint)
            fit = fit_grid(sp.lines, hint=hint)
            # next reference: the lines on the grid and the grid positions of the
            # missed ones (a stray detection does not lead the next photo astray)
            nxt = sorted((fit.lines + fit.missing if fit else sp.lines) + outside)
        else:
            found, nxt, per = self.lines(img, self.reference)
            if self.reference:
                coverage = min(len(found) / max(len(self.reference), 1), 1.0)
            sp = spacing_with_rule(found)
            drop = set(sp.excluded)
            nxt = [x for x in nxt if x not in drop]
        res = Measurement(found, sp, nxt, per, snr, coverage)
        if sp.spacing and self.spacing:
            res.jump = sp.spacing / self.spacing - 1
        res.doubts = self.doubts(res)
        return res

    def doubts(self, res):
        """Reasons why a measurement is doubtful (empty = fine)."""
        cfg, sp, out = self.cfg, res.spacing, []
        if sp.spacing is None:
            return ["fewer than 2 lines"]
        if not np.isnan(res.snr) and res.snr < cfg.q_snr:
            out.append(f"weak lines ({res.snr:.1f} sigma)")
        if not np.isnan(res.coverage) and res.coverage < cfg.q_coverage:
            out.append(f"only {res.coverage:.0%} of the lines found")
        if not np.isnan(sp.residual) and sp.residual > cfg.q_residual * sp.spacing:
            out.append(f"irregular ({sp.residual / sp.spacing:.0%} of the spacing off the grid)")
        if res.period and abs(res.period / sp.spacing - 1) > cfg.q_period:
            out.append(f"period {res.period:.1f} px vs spacing {sp.spacing:.1f} px")
        if not np.isnan(res.jump) and abs(res.jump) > cfg.q_jump:
            out.append(f"spacing jumped {res.jump:+.0%}")
        return out

    def accept(self, res):
        """Take a measurement as the reference for the next photo.

        The spacing carried on is that of the lines, unless the period of the
        pattern disagrees with it by over q_period and is close to the spacing
        before: then the period (a few wrong lines must not throw the search
        of the next photo off).
        """
        self.reference = res.reference
        sp, per = res.spacing.spacing, res.period
        if sp and per and abs(per / sp - 1) > self.cfg.q_period and self.spacing \
                and abs(per / self.spacing - 1) < 0.2:
            self.spacing = per
        elif sp:
            self.spacing = sp


def run_series(images, cfg=None):
    """Non-interactive analysis of photos (arrays) -> found lines per photo (whole-photo x).

    The first photo is prepared at cfg.contrast_diff sigmas (default 6) and
    every photo is measured and accepted as it is. Used by the test bench.
    """
    cfg = cfg or JumpConfig()
    an = Analyser(cfg)
    an.set_weights(images[0])
    lines, _ = an.prep_lines(images[0], an.value)
    an.set_reference(images[0], spacing_with_rule(lines).lines)
    out = []
    for img in images:
        res = an.measure(img)
        an.accept(res)
        out.append(res.lines)
    return out


# ---------------------------------------------------------------------------
# pictures
# ---------------------------------------------------------------------------
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
        text += f", spacing {sp.spacing:.1f}"
        if not np.isnan(sp.err):
            text += f" +- {sp.err:.1f}"
        text += " px"
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


# ---------------------------------------------------------------------------
# interactive command
# ---------------------------------------------------------------------------
def prepare(photo, img, an, out_dir, interactive=True, show=True, ask=input):
    """The preparation on one photo -> lines (whole-photo x), or None (quit / 15 tries).

    Sets the channel weights, ``an.value`` (the kept contrast_diff) and, when
    accepted, the template and the reference (Analyser.set_reference).
    """
    from .folder import _show_image
    cfg = an.cfg
    an.set_weights(img)
    value = an.value
    low = high = None
    prep_dir = Path(out_dir) / "preparation"
    for attempt in range(1, MAX_TRIES + 1):
        found, sigma = an.prep_lines(img, value)
        sp = spacing_with_rule(found)
        lines = sp.lines
        an.value = value
        if not interactive:
            an.set_reference(img, lines)
            return lines
        trial = Analyser(cfg)
        trial.weights, trial.value = an.weights, value
        trial.set_reference(img, lines)
        thin = trial.measure(img).spacing
        path = save_marked(img, lines, prep_dir / f"try{attempt}_{Path(photo).stem}.jpg",
                           sp.excluded)
        print(f"\nPreparation, try {attempt} of {MAX_TRIES} on {Path(photo).name}: "
              f"contrast_diff {value:.3g} sigma (= {value * sigma:.4g}) -> {_describe(sp)}")
        print("  channels R, G, B weighted " + ", ".join(f"{w:.2f}" for w in an.weights))
        print("  x = " + ", ".join(f"{x:.0f}" for x in lines))
        print(f"  (the {cfg.rows}-row analysis strip of this photo then gives {_describe(thin)})")
        print(f"  marked photo: {path}")
        if show and not _show_image(path):
            print("  (could not open an image viewer - open the file above yourself)")
        while True:
            answer = ask("Is this okay? [y = yes, n = no, q = quit] ").strip().lower()
            if answer in ("y", "yes", "q", "quit", "n", "no"):
                break
            print("Please answer y, n or q.")
        if answer in ("y", "yes"):
            an.set_reference(img, lines)
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


RESULTS_EXTRA = ["spacing_err_px", "quality"]
LINES_HEADER = ["photo", "file", "n_lines", "contrast_diff", "checked", "period_px",
                "period_vs_spacing_pct", "snr", "coverage", "x_px", "excluded_x", "long_gaps"]


def _row(time_info, n, name, res, warning=""):
    """results.csv row (folder.RESULTS_HEADER + RESULTS_EXTRA) from a Measurement."""
    sp = res.spacing
    mean = std = err = ""
    if sp.spacing is None:
        warning = "; ".join(w for w in (warning, "fewer than 2 lines") if w)
    else:
        mean = round(sp.spacing, 3)
        std = "" if np.isnan(sp.std) else round(sp.std, 3)
        err = "" if np.isnan(sp.err) else round(sp.err, 3)
    quality = "; ".join(d for d in res.doubts if d != "fewer than 2 lines") or "ok"
    return (time_info[0], n, name, mean, len(sp.lines), std, warning, time_info[1],
            sp.n_missing, sp.n_extra, err, quality)


def _line_row(n, name, value, checked, res):
    sp = res.spacing
    diff = (100 * (res.period / sp.spacing - 1)) if res.period and sp.spacing else None
    fmt = lambda xs: " ".join(f"{x:.1f}" for x in xs)
    return (n, name, len(sp.lines), round(value, 4), checked,
            "" if res.period is None else round(res.period, 2),
            "" if diff is None else round(diff, 1),
            "" if np.isnan(res.snr) else round(res.snr, 2),
            "" if np.isnan(res.coverage) else round(res.coverage, 3),
            fmt(sp.lines), fmt(sp.excluded),
            " ".join(f"{a:.0f}-{b:.0f}" for a, b in sp.long_gaps))


def _failed(e):
    return Measurement([], Spacing([], [], []), [], doubts=[f"failed: {e}"])


def overview_plot(rows, out_path, title=""):
    """Spacing (with error bars) against the photo number, doubtful photos in red."""
    from .style import BLUE, figure, finish
    fig, ax = figure(figsize=(11, 4.5))
    n = np.array([r[1] for r in rows])
    sp = np.array([np.nan if r[3] == "" else r[3] for r in rows], float)
    er = np.array([0 if r[10] == "" else r[10] for r in rows], float)
    bad = np.array([r[11] != "ok" or bool(r[6]) for r in rows])
    ax.errorbar(n[~bad], sp[~bad], yerr=er[~bad], fmt="o", ms=4, color=BLUE, mec="white",
                mew=0.8, elinewidth=1, capsize=2, label="ok")
    if bad.any():
        ax.plot(n[bad], sp[bad], "o", ms=7, mfc="none", mec="#d62728", mew=1.5,
                label="doubtful / warning")
        for x, y in zip(n[bad], sp[bad]):
            if not np.isnan(y):
                ax.annotate(str(x), (x, y), textcoords="offset points", xytext=(4, 4),
                            fontsize=8, color="#d62728")
    ax.set_xlabel("photo")
    ax.set_ylabel("spacing (px)")
    ax.set_title(title, loc="left")
    ax.legend(frameon=False)
    return finish(fig, out_path)


def main_jumps(path, output_dir=None, input_dir=None, config=None, interactive=True,
               show=True, ask=input):
    """``analysis jumps NAME``: preparation, then every photo; see the module doc.

    Writes <output_dir>/jumps/<name>/:
      results.csv       as the folder analysis plus spacing_err_px and quality
                        (for analysis report --results)
      lines.csv         photo, file, n_lines, contrast_diff, checked, period_px,
                        period_vs_spacing_pct, snr, coverage, x_px, excluded_x, long_gaps
      parameters.json   the settings and every preparation
      overview.png      spacing against the photo number, doubtful photos in red
      preparation/      the marked photos of every preparation try
      <photo>_marked.jpg  every photo with its lines in navy blue
    Returns the result rows ([] if the first preparation was not accepted).
    """
    from .folder import RESULTS_HEADER, _show_image, get_sorted_photos, result_row
    from .logs import resolve_folder
    from .paths import output_root

    cfg = config or JumpConfig()
    if cfg.ask not in ("doubtful", "count", "review"):
        raise ValueError("ask must be doubtful, count or review")
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
                             "template": None if an.template is None
                             else [round(float(v), 5) for v in an.template],
                             "initial_positions": [round(x, 2) for x in lines]})

    note_preparation(photos[0], initial)
    live = interactive and cfg.ask in ("doubtful", "count")
    print(f"\ncontrast_diff {an.value:.3g} sigma, {len(initial)} initial lines. Analysing "
          f"{len(photos)} photos on the middle {cfg.rows} rows with the {cfg.detector} detector"
          + (", asking about doubtful photos" if live and cfg.ask == "doubtful" else "")
          + (", asking when the line count changes" if live and cfg.ask == "count" else "")
          + (", review at the end" if interactive and cfg.ask == "review" else "") + ".")

    header = RESULTS_HEADER + RESULTS_EXTRA

    def write(rows, line_rows):
        params = dict(asdict(cfg), contrast_diff=an.value, method="jumps",
                      preparations=preparations)
        (out_dir / "parameters.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
        write_csv(out_dir / "lines.csv", LINES_HEADER, line_rows)
        if rows:
            overview_plot(rows, out_dir / "overview.png", f"{folder.name}: spacing per photo")
        return write_csv(out_dir / "results.csv", header, rows)

    def needs_question(res, previous):
        if cfg.ask == "count":
            return len(res.spacing.lines) != previous
        return res.doubtful

    rows, line_rows, measured = [], [], []
    previous = len(initial)
    for n, photo in enumerate(photos, start=1):
        checked = ""
        try:
            img = img if n == 1 else _read_image(photo)
            res = an.measure(img)
            while live and needs_question(res, previous):
                sp = res.spacing
                marked = save_marked(img, sp.lines, out_dir / f"{photo.stem}_marked.jpg",
                                     sp.excluded)
                why = (f"the photo before had {previous} lines" if cfg.ask == "count"
                       else "doubtful: " + "; ".join(res.doubts))
                print(f"\n[{n}/{len(photos)}] {photo.name}: {_describe(sp)} - {why}")
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
                previous = len(again)
                checked = "prepared again"
                res = an.measure(img)
            sp = res.spacing
            save_marked(img, sp.lines, out_dir / f"{photo.stem}_marked.jpg", sp.excluded)
            an.accept(res)
            previous = len(sp.lines)
            row = _row(times[photo], n, photo.name, res)
        except Exception as e:
            res = _failed(e)
            row = result_row(times[photo], n, photo.name, None, f"failed: {e}") + ("", "")
        rows.append(row)
        measured.append((photo, res))
        line_rows.append(_line_row(n, photo.name, an.value, checked, res))
        print(f"[{n}/{len(photos)}] {photo.name}: {_describe(res.spacing)}"
              + (f" ({checked})" if checked else "") + (f" {row[6]}" if row[6] else "")
              + ("" if row[11] in ("ok", "") else f" - doubtful: {row[11]}"))

    if interactive and cfg.ask == "review":
        rows, line_rows = _review(rows, line_rows, measured, an, out_dir, times, show, ask,
                                  note_preparation, folder.name)
    return _finish(rows, write(rows, line_rows))


def _review(rows, line_rows, measured, an, out_dir, times, show, ask, note_preparation, name):
    """Review mode: the overview, then every doubtful photo -> (rows, line_rows)."""
    from .folder import _show_image
    over = overview_plot(rows, out_dir / "overview.png", f"{name}: spacing per photo")
    doubtful = [i for i, r in enumerate(rows) if r[11] not in ("ok", "")]
    print(f"\nReview: {len(doubtful)} of {len(rows)} photos are doubtful. Overview: {over}")
    if show and doubtful and not _show_image(over):
        print("  (could not open an image viewer - open the file above yourself)")
    for i in doubtful:
        photo, res = measured[i]
        n = i + 1
        while True:
            sp = res.spacing
            marked = Path(out_dir) / f"{photo.stem}_marked.jpg"
            print(f"\n[{n}/{len(rows)}] {photo.name}: {_describe(sp)} - doubtful: {rows[i][11]}")
            print(f"  marked photo: {marked}")
            if show and not _show_image(marked):
                print("  (could not open an image viewer - open the file above yourself)")
            answer = ask("y = keep, x = exclude, p = prepare again on it, q = stop reviewing: "
                         ).strip().lower()
            if answer in ("y", "yes"):
                line_rows[i] = line_rows[i][:4] + ("kept",) + line_rows[i][5:]
                break
            if answer == "x":
                r = list(rows[i])
                r[6] = "; ".join(w for w in (r[6], "excluded in review") if w)
                rows[i] = tuple(r)
                line_rows[i] = line_rows[i][:4] + ("excluded",) + line_rows[i][5:]
                break
            if answer in ("q", "quit"):
                return rows, line_rows
            if answer == "p":
                img = _read_image(photo)
                again = prepare(photo, img, an, out_dir, True, show, ask)
                if again is None:
                    return rows, line_rows
                note_preparation(photo, again)
                res = an.measure(img)
                save_marked(img, res.spacing.lines, marked, res.spacing.excluded)
                rows[i] = _row(times[photo], n, photo.name, res)
                line_rows[i] = _line_row(n, photo.name, an.value, "prepared again", res)
                measured[i] = (photo, res)
                if not res.doubtful:
                    break
                continue
            print("Please answer y, x, p or q.")
    return rows, line_rows


def _finish(rows, csv_path):
    print(f"Data: {csv_path}")
    print(f"For the report: analysis report NAME --results {csv_path}")
    return rows
