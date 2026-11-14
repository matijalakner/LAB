"""Line detection in a thin strip of every photo (``analysis jumps NAME``).

How the lines look in the real photos (series 08, see lines.py and
tests/data/real): a sharp brightness change through every row, a step DOWN
left of the brightest part of the photo, a step UP right of it, and a thin
dark or bright line near the brightest part. The distances between them are
uneven (narrow bands next to wide ones).

Preparation (first photo, and again whenever you ask for it):
  1. Cut out the middle ``prep_rows`` (300) rows and cut ``edge`` (200 px of a
     6000 px wide photo) off the left and the right.
  2. Brightness per pixel: the colour channels weighted by how bright they are
     (channel_weights).
  3. Line strength (lines.line_strength): the step, and the thin-line value, of
     log(brightness) over ``jump_width`` px, both signs, as the median of 6
     bands of rows (dust in some rows does not count), in local noise sigmas
     (with a floor of about a third of a brightness level, for flat dark areas).
  4. Every peak over ``contrast_diff`` sigmas is a line; a step that happens
     within one pixel (a JPEG block edge) must be far stronger (lines.sharpness).
     Then the gap rule (below).
  5. The whole photo is saved with the lines as navy blue lines from top to
     bottom and opened; you answer y (keep), n (then + = more lines, - = fewer
     lines, or a new value) or q. After 15 tries it stops by itself.
  6. Every kept line keeps its own shape: a template from this strip.

Analysis (every photo, in time order, the first included), detector "template":
  The middle row and the rows above and below it (``rows`` = 3), without the
  edges. The whole row of lines of the photo before is shifted and stretched
  (+-``stretch``) to where the lines fit best, then every line is refined
  within +-``window`` (10 %) of the spacing; it is found if the normalized
  correlation with its own template is over ``ncc_min``. A line not found is
  followed at its predicted position; templates slowly follow the lines; new
  lines beyond the outer ones are found as in the preparation.
  Detector "learned" (learned.py) is the template detector plus a small neural
  network that learns from the accepted lines what a line looks like: it is
  trained on the preparation photo, then on every photo without doubts, and
  every line is found where sqrt(network probability x template match) is
  highest (over sqrt(p_min x ncc_min)); new lines at the edges must be
  confirmed by the network. The network is saved as line_model.npz.
  Detector "threshold" is the earlier one (largest jump near each line).

Quality: a photo is doubtful when the median match of its lines is under
``q_snr``, fewer than ``q_coverage`` of the lines in the picture are found, the
spacing changed by more than ``q_jump`` from the photo before, a distance is
over ``q_gap`` (1.7) x the average (a missed line would make it ~2x; in the
real photos the widest band was 1.4x), or the lines
differ (by more than ``check_tol`` px) from those found as in the preparation
on the middle ``check_rows`` (300) rows of the same photo: a strong line there
(1.5 x contrast_diff) that is not followed, or a followed line with no line
there even at half the limit. The check only
decides whether the photo is doubtful; the spacing is always that of the
3-row strip.

Asking (``ask``):
  doubtful (default)  a doubtful photo is shown: y = keep it, n = prepare again
                      on it and measure it again, q = stop (results written)
  count               when the number of lines changes
  review              nothing during the run; afterwards an overview of the
                      spacing (overview.png) and every doubtful photo is shown:
                      y = keep, x = exclude (warning, left out of the report),
                      p = prepare again on it and measure it again, q = stop
  --yes asks nothing: the first preparation is kept, and a doubtful photo is
  prepared again automatically and measured again.

Gap rule (every photo and the preparation): a distance between neighbouring
lines below half the average distance (the average of the normal distances,
average_gap) means a possible false line: the weaker line of the pair is
excluded, but only if it is weaker than 0.4 x the median line (real narrow
bands, two strong lines, stay). A distance over twice the average (lines lost)
is left out. The spacing is the mean of the remaining distances (the lines are
not assumed evenly spaced). std_spacing_px is the spread of the distances (how
uneven the bands are); spacing_err_px is how precisely the spacing is measured,
from how far the 3-row lines lie from the same lines of the 300-row check.

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
from .spacing import _trimmed_k, fit_grid, trimmed_mean
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
    contrast_diff: float = None   # preparation: line strength limit in noise sigmas; None = 6
    edge: int = 200               # px cut off the left and the right (of a 6000 px wide photo)
    prep_rows: int = 300          # rows of the preparation strip
    rows: int = 3                 # rows of the analysis strip (middle row +- 1)
    merge: int = 47               # lines closer than this (px) are one line
    jump_width: int = 18          # step over this many px (template: 2 x smoothing)
    template_half: int = 70       # half width of a line's template (px)
    channels: str = "auto"        # auto (weighted by brightness), mean, r, g or b
    detector: str = "template"    # template (every line its own shape), learned (a network
                                  # trained on the accepted lines) or threshold
    model: str = None             # learned: start from this saved network (line_model.npz)
    learn: bool = True            # learned: keep learning from every photo without doubts
    p_min: float = 0.5            # learned: a line is found where its probability is over this
    track: bool = True            # threshold detector: search near the previous lines
    window: float = None          # search +- this fraction of the spacing; None = 0.1
                                  # (template) / 0.2 (threshold)
    ncc_min: float = 0.3          # template: a line is found if its match is over this
    stretch: float = 0.06         # template: the row of lines may stretch +- this per photo
    min_sigma: float = 2.0        # threshold detector: a tracked line over this many sigmas
    min_rel: float = 0.35         # ... and over this fraction of the typical line
    ask: str = "doubtful"         # doubtful | count | review
    q_snr: float = 0.5            # doubtful: median match of the lines under this
    q_coverage: float = 0.75      # ... fewer than this share of the lines found
    q_jump: float = 0.08          # ... the spacing changed by more than this
    q_gap: float = 1.7            # ... a distance is over this x the average (a line may be
                                  # missing; over GAP_HIGH it is left out of the spacing)
    check_rows: int = 300         # ... the lines differ from those found as in the preparation
                                  # on this many middle rows (0 = no check)
    check_tol: int = 35           # px a line may differ from the check
    # every px value is for a photo REF_WIDTH (6000 px) wide and scales with the width
    # (jump_width 1 stays 1)


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
    n_used: int = 0               # distances in the average (after trimming)


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


WEAK = 0.4      # a too-close line is excluded only if weaker than this x the median line


def gap_rule(xs, low=GAP_LOW, high=GAP_HIGH, strengths=None, weak=WEAK):
    """(kept lines, excluded lines, parts): the gap rule, see the module doc.

    With ``strengths`` (one per line), of a pair closer than low x the average
    the weaker line is excluded only if it is weaker than ``weak`` x the median
    strength: real narrow bands (two strong lines) stay. Without, as before.
    """
    order = np.argsort(np.asarray(xs, float)) if len(xs) else []
    xs = [float(xs[i]) for i in order]
    st = None if strengths is None else [float(strengths[i]) for i in order]
    excluded = []
    while len(xs) >= 3:
        gaps = np.diff(xs)
        avg = average_gap(gaps, low, high)
        short = [i for i in range(len(gaps)) if gaps[i] < low * avg]
        if not short:
            break
        typical = float(np.median(gaps))   # not pulled by the short distance itself

        def score(j):                      # distance closest to typical after removing xs[j]
            if 0 < j < len(xs) - 1:
                return abs(xs[j + 1] - xs[j - 1] - typical)
            other = xs[2] - xs[1] if j == 0 else xs[-2] - xs[-3]
            return abs(other - typical)
        drop = None
        if st is None:
            i = min(short, key=lambda i: gaps[i])
            drop = i if score(i) <= score(i + 1) else i + 1
        else:
            med = float(np.median(st))
            for i in short:
                j = i if st[i] <= st[i + 1] else i + 1
                if st[j] < weak * med and (drop is None or st[j] < st[drop]):
                    drop = j
            if drop is None:
                break
        excluded.append(xs.pop(drop))
        if st is not None:
            st.pop(drop)
    parts = [xs[:1]] if xs else []
    if len(xs) >= 2:
        avg = average_gap(np.diff(xs), low, high)
        for a, b in zip(xs, xs[1:]):
            if b - a > high * avg:
                parts.append([b])
            else:
                parts[-1].append(b)
    return xs, sorted(excluded), parts


def spacing_with_rule(xs, low=GAP_LOW, high=GAP_HIGH, hint=None, strengths=None):
    """Spacing after the gap rule -> Spacing.

    The spacing is the average distance between neighbouring lines, the
    distances over high x the average (lines lost there) left out; with more
    than 3 lines the largest and smallest 10% are left out too (trimmed_mean). The lines
    are not assumed evenly spaced: in real photos the bands differ a lot.
    err is the standard error of that mean. ``hint`` is not used any more.
    """
    kept, excluded, parts = gap_rule(xs, low, high, strengths)
    res = Spacing(kept, excluded, [(p[-1], q[0]) for p, q in zip(parts, parts[1:])])
    gaps = np.concatenate([np.diff(p) for p in parts if len(p) >= 2]) if parts else []
    if len(gaps):
        res.spacing = trimmed_mean(gaps, n_lines=len(kept))
        res.n_used = len(gaps) - 2 * _trimmed_k(len(gaps), len(kept))
        if len(gaps) > 1:
            res.std = float(np.std(gaps, ddof=1))
            res.err = res.std / np.sqrt(len(gaps))
            res.residual = res.std
        res.n_missing = sum(max(0, int(round((b - a) / res.spacing)) - 1)
                            for a, b in res.long_gaps)
    res.n_extra = len(excluded)
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
@dataclass
class Measurement:
    lines: list                   # found lines (whole-photo x), before the gap rule
    spacing: Spacing
    reference: list               # positions to follow in the next photo
    period: float = None
    snr: float = float("nan")     # median match (correlation 0..1) of the lines found
    coverage: float = float("nan")  # found / predicted lines in the picture
    jump: float = float("nan")    # spacing change from the photo before
    doubts: list = field(default_factory=list)
    templates: list = None        # line shapes to follow in the next photo
    strengths: list = None        # per found line (correlation)
    check: list = None            # lines found as in the preparation (check_rows rows)
    lost: list = field(default_factory=list)   # lines followed but not found (predicted x)
    image: object = None          # learned detector: the photo, to learn from in accept()

    @property
    def doubtful(self):
        return bool(self.doubts)


class Analyser:
    """The detection of one series: settings, channel weights, lines and their shapes."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.weights = None
        self.value = cfg.contrast_diff or START_SIGMAS
        self.reference = []        # whole-photo x
        self.templates = []        # one per reference line (template detector)
        self.spacing = None        # spacing of the photo before
        self._width = None
        self.model = None          # learned detector: the network
        if cfg.detector == "learned" and cfg.model:
            from .learned import LineModel
            self.model = LineModel.load(cfg.model)

    # sizes ------------------------------------------------------------------
    def edge_px(self, img):
        """``cfg.edge`` (px of a 6000 px wide photo) for this photo's width."""
        return int(round(self.cfg.edge * img.shape[1] / REF_WIDTH))

    def sizes(self, img):
        """(jump_width, merge) in px for this photo's width (threshold detector)."""
        s = img.shape[1] / REF_WIDTH
        jw = 1 if self.cfg.jump_width <= 1 else max(2, int(round(self.cfg.jump_width * s)))
        return jw, max(3, int(round(self.cfg.merge * s)))

    def line_sizes(self, img):
        from .lines import LineSizes
        return LineSizes.for_width(img.shape[1], jump_width=max(self.cfg.jump_width, 2),
                                   merge=self.cfg.merge, half=self.cfg.template_half)

    def _cfg(self, img):
        jw, merge = self.sizes(img)
        return replace(self.cfg, jump_width=jw, merge=merge, edge=self.edge_px(img))

    def strip(self, img, rows):
        return middle_strip(img, rows, self.edge_px(img))

    def gray(self, img, rows):
        """Brightness (channels weighted) of the middle ``rows`` rows, edges cut."""
        return np.asarray(self.strip(img, rows), np.float32) @ np.asarray(self.weights,
                                                                          np.float32)

    def strip_profile(self, img, rows):
        return collapsed_contrast(self.strip(img, rows), self.weights)

    # preparation ------------------------------------------------------------
    def set_weights(self, img):
        self.weights = channel_weights(self.strip(img, self.cfg.prep_rows), self.cfg.channels)

    def prep_lines(self, img, value):
        """(lines in whole-photo x, strengths) of the preparation strip at ``value`` sigmas."""
        edge = self.edge_px(img)
        if self.cfg.detector == "threshold":
            cfg = self._cfg(img)
            profile = self.strip_profile(img, cfg.prep_rows)
            sigma = noise_sigma(jump_profile(profile, cfg.jump_width)[0])
            xs = find_jumps(profile, value * sigma, cfg.merge, cfg.jump_width)
            return [x + edge for x in xs], None
        from .lines import detect
        xs, st = detect(self.gray(img, self.cfg.prep_rows), value, self.line_sizes(img))
        return [x + edge for x in xs], st

    def set_reference(self, img, lines):
        """Start following ``lines`` (accepted in the preparation of ``img``)."""
        self.reference = sorted(lines)
        # the lines were kept in the preparation: their spacing without excluding any
        sp = spacing_with_rule(lines, strengths=[1.0] * len(lines))
        self.spacing = sp.spacing
        self.templates = []
        if self.cfg.detector in ("template", "learned"):
            from .lines import log_profile, make_templates
            edge = self.edge_px(img)
            L = log_profile(self.gray(img, self.cfg.prep_rows))
            self.templates = make_templates(L, [x - edge for x in self.reference],
                                            self.line_sizes(img).half)
        if self.cfg.detector == "learned":
            self.learn(img, self.reference, epochs=300)

    def learn(self, img, lines, epochs=60):
        """Teach the network the accepted ``lines`` (whole-photo x) of ``img``."""
        from .learned import LineModel, training_strips
        if len(lines) < 2 or not self.spacing:
            return
        if self.model is None:
            self.model = LineModel()
        edge, sz = self.edge_px(img), self.line_sizes(img)
        full = self.gray(img, self.cfg.prep_rows)
        xs = [x - edge for x in lines]
        X, y = self.model.samples(training_strips(full, self.cfg.rows, n=30), xs,
                                  self.spacing, sz, lo=min(xs) - 0.5 * self.spacing,
                                  hi=max(xs) + 0.5 * self.spacing)
        self.model.add(X, y)
        self.model.fit(epochs=epochs)

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

    def _template_measure(self, img):
        """Measurement with the per-line templates (lines.track)."""
        from .lines import detect, log_profile, make_templates, refresh, track
        cfg, sz, edge = self.cfg, self.line_sizes(img), self.edge_px(img)
        g = self.gray(img, cfg.rows)
        L = log_profile(g)
        ref = [x - edge for x in self.reference]
        learned = cfg.detector == "learned"
        shape = None
        if learned:
            # The whole row of lines is shifted/stretched with the templates (they
            # know which line is which); then every line is found where
            # sqrt(probability of a line x match of its own template) is highest:
            # the network says what is a line, the template which line it is.
            from .lines import gradient, match_map
            P = np.clip(self.model.prob(g, sz), 0, 1)
            G = gradient(L)
            tmaps = [np.clip(np.nan_to_num(match_map(L, t, G)), 0, 1) if t is not None
                     else None for t in self.templates]
            found, score, pred = track(
                L, ref, self.templates, self.spacing, cfg.window or 0.1,
                np.sqrt(cfg.p_min * cfg.ncc_min), cfg.stretch,
                refine_maps=[np.sqrt(P * m) if m is not None else P for m in tmaps])
            # the quality score stays the template match: a big change of the line
            # shapes makes the photo doubtful as with the template detector
            shape = [float(np.interp(x, np.arange(len(L)), m)) if x is not None and m is not None
                     else np.nan for x, m in zip(found, tmaps)]
        else:
            found, score, pred = track(L, ref, self.templates, self.spacing,
                                       cfg.window or 0.1, cfg.ncc_min, cfg.stretch)
        lines, strengths, nxt, temps, shapes = [], [], [], [], []
        inside = 0
        for i, (x, sc, pr, t) in enumerate(zip(found, score, pred, self.templates)):
            in_picture = sz.margin <= pr <= len(L) - 1 - sz.margin
            inside += in_picture
            if x is not None:
                lines.append(x)
                strengths.append(sc)
                if shape is not None:
                    shapes.append(shape[i])
            if x is not None or in_picture:
                nxt.append(x if x is not None else pr)      # lost: follow the prediction
                temps.append(t)
        temps = refresh(temps, L, [x if x in lines else None for x in nxt],
                        [strengths[lines.index(x)] if x in lines else np.nan for x in nxt],
                        sz.half)
        # new lines coming into the picture beyond the outer ones
        if lines and self.spacing:
            new, new_st = detect(g, self.value, sz)
            if learned:      # ... and the network must agree that it is a line
                ok = [P[max(int(x) - 3, 0):int(x) + 4].max() >= cfg.p_min for x in new]
                new = [x for x, k in zip(new, ok) if k]
                new_st = [v for v, k in zip(new_st, ok) if k]
            lo, hi = min(nxt) - 0.6 * self.spacing, max(nxt) + 0.6 * self.spacing
            for x, s in zip(new, new_st):
                if x < lo or x > hi:
                    lines.append(x)
                    strengths.append(1.0)
                    nxt.append(x)
                    temps.append(make_templates(L, [x], sz.half)[0])
        order = np.argsort(nxt)
        nxt = [nxt[i] for i in order]
        temps = [temps[i] for i in order]
        sp = spacing_with_rule(lines, strengths=strengths)
        drop = set(sp.excluded)
        keep = [i for i, x in enumerate(nxt) if x not in drop]
        # a line lost between two found ones is still a step of the spacing: its
        # predicted position goes into the spacing (as a missed line), so the
        # distance across it is not taken as one wide band
        lost = [x for x in nxt if x not in lines and min(lines or [x]) < x < max(lines or [x])]
        full = spacing_with_rule([x + edge for x in lines + lost],
                                 strengths=strengths + [float(np.median(strengths))] * len(lost)
                                 if strengths else None)
        full.lines = [x for x in full.lines if x - edge not in lost]
        full.n_missing += len(lost)
        lost_whole = [x + edge for x in lost]
        res = Measurement([x + edge for x in lines], full,
            [nxt[i] + edge for i in keep], None,
            float(np.nanmedian(shapes)) if shapes and not np.all(np.isnan(shapes))
            else float(np.median(strengths)) if strengths else 0.0,
            min(len(lines) / inside, 1.0) if inside else 0.0,
            templates=[temps[i] for i in keep], strengths=strengths, lost=lost_whole)
        res.image = img if learned else None
        res.period = period(L - np.convolve(L, np.ones(sz.win) / sz.win, "same"),
                            sp.spacing)
        if cfg.check_rows:
            res.check = self.check_lines(img)
        self._position_error(res, img)
        return res

    def _position_error(self, res, img):
        """spacing_err_px from how precisely the lines are placed.

        The spread of the band widths is in std_spacing_px; it says how uneven
        the bands are, not how well the spacing is measured. The error of the
        mean spacing is sqrt(2) x the position error / sqrt(number of distances
        averaged): with the 10% trimming the distances in the average no longer
        add up to (last - first line), so each one's error counts. The position error is the rms difference
        between the 3-row lines and the same lines of the check (at least 0.5 px);
        without a check, 1 px of a 2576 px wide photo, scaled.
        """
        sp = res.spacing
        if not sp.spacing or len(sp.lines) < 2:
            return
        sigma = 1.0 * img.shape[1] / 2576
        if res.check:
            tol = self.cfg.check_tol * img.shape[1] / REF_WIDTH
            d = [min(abs(x - c) for c, _ in res.check) for x in sp.lines]
            d = [v for v in d if v <= tol]
            if len(d) >= 2:
                sigma = max(float(np.sqrt(np.mean(np.square(d)))), 0.5)
        sp.err = float(np.sqrt(2) * sigma / np.sqrt(max(sp.n_used, 1)))

    def check_lines(self, img):
        """Lines of the middle ``check_rows`` rows, found as in the preparation.

        -> (x, strength) pairs (whole-photo x) down to half the preparation
        limit; doubts() uses the strong ones (1.5 x the limit) to see whether a
        line is not followed, and all of them to see whether a followed line is
        not there at all (a faint line is found in one strip and not in another).
        """
        from .lines import detect
        rows = min(self.cfg.check_rows, img.shape[0])
        xs, st = detect(self.gray(img, rows), 0.5 * self.value, self.line_sizes(img))
        edge = self.edge_px(img)
        kept = set(gap_rule(xs, strengths=st)[0])
        return [(x + edge, v) for x, v in zip(xs, st) if x in kept]

    def measure(self, img):
        """Measure one photo -> Measurement (accept() moves the reference on)."""
        cfg = self.cfg
        self._width = img.shape[1]
        if cfg.detector in ("template", "learned") and self.templates:
            res = self._template_measure(img)
        else:
            found, nxt, per = self.lines(img, self.reference)
            coverage = (min(len(found) / max(len(self.reference), 1), 1.0)
                        if self.reference else np.nan)
            sp = spacing_with_rule(found)
            drop = set(sp.excluded)
            res = Measurement(found, sp, [x for x in nxt if x not in drop], per, np.nan,
                              coverage)
        sp = res.spacing
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
            out.append(f"weak lines (match {res.snr:.2f})")
        if not np.isnan(res.coverage) and res.coverage < cfg.q_coverage:
            out.append(f"only {res.coverage:.0%} of the lines found")
        if not np.isnan(res.jump) and abs(res.jump) > cfg.q_jump:
            out.append(f"spacing jumped {res.jump:+.0%}")
        if len(sp.lines) >= 3:
            gaps = np.diff(sp.lines)
            avg = average_gap(gaps)
            # a known lost line (followed, not found) is already counted as a step
            wide = [(a, b) for a, b, g in zip(sp.lines, sp.lines[1:], gaps)
                    if cfg.q_gap * avg < g <= GAP_HIGH * avg
                    and not any(a < x < b for x in res.lost)]
            if wide:
                out.append("a line may be missing between x=" + ", ".join(
                    f"{a:.0f}-{b:.0f}" for a, b in wide))
        if res.check is not None:
            tol = cfg.check_tol * self._width / REF_WIDTH if self._width else cfg.check_tol
            strong = [x for x, v in res.check if v >= 1.5 * self.value]
            anyline = [x for x, _ in res.check]
            missed = [x for x in strong if all(abs(x - f) > tol for f in sp.lines)]
            stray = [f for f in sp.lines if all(abs(x - f) > tol for x in anyline)]
            if missed or stray:
                out.append(f"lines differ from the {cfg.check_rows}-row check ("
                           + ", ".join(t for t in (
                               f"not followed at x={', '.join(f'{x:.0f}' for x in missed)}"
                               if missed else "",
                               f"no line at x={', '.join(f'{x:.0f}' for x in stray)}"
                               if stray else "") if t) + ")")
        return out

    def accept(self, res):
        """Take a measurement as the reference for the next photo.

        Learned detector: a photo without doubts is also learned from.
        """
        img = getattr(res, "image", None)
        # only photos where every followed line was found: a lost line would be
        # taught as "no line"
        if img is not None and self.cfg.learn and not res.doubtful and res.spacing.lines \
                and not res.lost and not res.spacing.n_missing:
            self.learn(img, res.spacing.lines)
        res.image = None
        self.reference = res.reference
        if res.templates is not None:
            self.templates = res.templates
        if res.spacing.spacing:
            self.spacing = res.spacing.spacing


def run_series(images, cfg=None, reprepare=True, details=False):
    """Non-interactive analysis of photos (arrays) -> found lines per photo (whole-photo x).

    The first photo is prepared at cfg.contrast_diff sigmas (default 6). A
    doubtful photo is prepared again (``reprepare``) and measured again, as
    with --yes. With ``details`` the Measurements are returned instead.
    """
    cfg = cfg or JumpConfig()
    an = Analyser(cfg)
    an.set_weights(images[0])
    _prepare_auto(an, images[0])
    out = []
    for img in images:
        res = an.measure(img)
        if res.doubtful and reprepare:
            _prepare_auto(an, img)
            res = an.measure(img)
        an.accept(res)
        out.append(res if details else res.lines)
    return out


def _prepare_auto(an, img):
    an.set_weights(img)
    lines, st = an.prep_lines(img, an.value)
    kept = gap_rule(lines, strengths=st)[0]
    an.set_reference(img, kept)
    return kept


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
        found, strengths = an.prep_lines(img, value)
        sp = spacing_with_rule(found, strengths=strengths)
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
              f"contrast_diff {value:.3g} sigma -> {_describe(sp)}")
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
               show=True, ask=input, final_review=None):
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
      line_model.npz    learned detector: the trained network (for --model)
    At the end, every photo that is still doubtful (and was not kept with y
    during the run) is shown again: y = keep, x = exclude, p = prepare again,
    q = stop (``final_review``; default: when ``interactive``; the CLI also does
    it with --yes unless --no-review).
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
                             "line_templates": sum(t is not None for t in an.templates),
                             "line_model_samples": (0 if an.model is None or an.model.y is None
                                                    else int(len(an.model.y))),
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
        if an.model is not None and an.model.trained:
            an.model.save(out_dir / "line_model.npz")
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
            if not interactive and res.doubtful:
                why = "; ".join(res.doubts)
                note_preparation(photo, _prepare_auto(an, img))
                res = an.measure(img)
                checked = f"prepared again automatically ({why})"
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

    if interactive if final_review is None else final_review:
        rows, line_rows = _review(rows, line_rows, measured, an, out_dir, times, show, ask,
                                  note_preparation, folder.name)
    return _finish(rows, write(rows, line_rows))


def _review(rows, line_rows, measured, an, out_dir, times, show, ask, note_preparation, name):
    """End of the run: the overview, then every photo still doubtful -> (rows, line_rows).

    Photos already kept with y during the run are not asked again.
    """
    from .folder import _show_image
    doubtful = [i for i, r in enumerate(rows) if r[11] not in ("ok", "")
                and line_rows[i][4] != "accepted"]
    if not doubtful:
        print("\nNo photo is still doubtful.")
        return rows, line_rows
    over = overview_plot(rows, out_dir / "overview.png", f"{name}: spacing per photo")
    print(f"\nReview: {len(doubtful)} of {len(rows)} photos are still doubtful. "
          f"Overview: {over}")
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
            try:
                answer = ask("y = keep, x = exclude, p = prepare again on it, "
                             "q = stop reviewing: ").strip().lower()
            except EOFError:                     # no terminal (e.g. run from a script)
                print("  (no answer possible here; the photos are left as they are)")
                return rows, line_rows
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
