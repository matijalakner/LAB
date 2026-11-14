"""Line detection core for ``analysis jumps``, built on real photos of series 08.

What a line looks like in these photos (see tests/data/real): a sharp change of
the brightness that runs through every row, either
  * a step DOWN (left of the brightest part of the photo),
  * a step UP (right of it), or
  * a thin dark or bright line (near the brightest part, where the step
    changes sign and almost vanishes).
The distances between the lines are uneven (here from ~100 to ~400 px at
2576 px width), and some bands are narrow.

Things that look similar but are not lines:
  * dust and scratches: in some rows only -> the step is measured in 6 bands of
    rows and the median of them is taken;
  * slow brightness changes in the dark edges, where the image sits on one
    brightness level for many pixels and then moves one level: the noise has a
    floor of about a third of a level (relative to the local brightness);
  * JPEG compression block edges: small (a few brightness levels) and sharp
    within one pixel (a real line changes over several pixels) -> ``sharpness``,
    used for steps under JPEG_LEVELS levels.

Preparation (300 rows): every peak of the line strength over ``sigmas`` noise
sigmas, weakened by its sharpness, is a line; then the gap rule.

Analysis (3 rows): every line keeps its own shape (template, from the
preparation) and is searched again near where it was: the whole row of lines
is first shifted and stretched together to fit best, then every line within
+- ``window`` of the spacing; it is found if its normalized correlation with
its template (brightness and gradient correlation multiplied) is over ``ncc_min``.

All sizes are px of a photo REF_WIDTH (6000 px) wide and scale with the width.
"""
from dataclasses import dataclass

import numpy as np

from .detect import REF_WIDTH, moving_median


def uniform_filter1d(x, w):
    """Moving mean over w px (edge padded), like scipy.ndimage.uniform_filter1d."""
    x = np.asarray(x, float)
    w = max(1, int(w))
    if w == 1:
        return x.copy()
    left = w // 2
    padded = np.pad(x, (left, w - 1 - left), mode="edge")
    c = np.cumsum(np.r_[0.0, padded])
    return (c[w:] - c[:-w]) / w


def median_filter(x, w, mode="nearest"):
    return moving_median(x, w)


@dataclass
class LineSizes:
    """Sizes in px for one photo width (from px of a 6000 px wide photo)."""
    w: int          # smoothing and half the step length
    margin: int     # px at both ends of the strip without lines (filter edges)
    merge: int      # peaks closer than this are one line
    half: int       # half width of a line template
    win: int        # window of the local noise
    sharp_px: int   # +- px looked at for the sharpness

    @classmethod
    def for_width(cls, width, jump_width=18, merge=47, half=70, win=468):
        s = width / REF_WIDTH
        odd = lambda v: int(v) | 1
        return cls(w=max(2, int(round(jump_width / 2 * s))), margin=max(10, int(round(70 * s))),
                   merge=max(5, int(round(merge * s))), half=max(6, int(round(half * s))),
                   win=odd(max(31, round(win * s))), sharp_px=max(3, int(round(14 * s))))


SHARP_LO, SHARP_HI = 0.3, 0.6     # sharpness: under LO counts fully, over HI not at all
JPEG_LEVELS = 6.0                 # ... only for steps under this many brightness levels
NOISE_FLOOR_LEVELS = 1.0          # noise floor, brightness levels (before the row average)


def log_profile(gray):
    """log(brightness + 1), averaged over the rows -> one value per x."""
    return np.log(np.maximum(np.asarray(gray, float).mean(axis=0), 0) + 1)


def _step(L, w, kind):
    sm = uniform_filter1d(L, w)
    d = np.zeros_like(L)
    if kind == "step":
        d[w:-w] = sm[2 * w:] - sm[:-2 * w]
    else:                                   # thin line: centre against both sides
        d[2 * w:-2 * w] = sm[2 * w:-2 * w] - 0.5 * (sm[:-4 * w] + sm[4 * w:])
    return d


def line_strength(gray, sz, bands=6):
    """Line strength per x in local noise sigmas (>= 0), and the signed step.

    ``gray``: rows x cols brightness. The step (and the thin-line value) is
    computed in ``bands`` bands of rows; the median over the bands is used, so
    dust in a few rows does not count. Strength = the larger of the two.
    """
    gray = np.asarray(gray, float)
    bands = max(1, min(bands, gray.shape[0] // 10)) if gray.shape[0] >= 20 else 1
    parts = np.array_split(gray, bands)
    level = uniform_filter1d(gray.mean(axis=0), sz.win)
    floor = NOISE_FLOOR_LEVELS / np.sqrt(max(gray.shape[0] / bands, 1)) / (level + 1)
    best, signed = None, None
    for kind in ("step", "line"):
        D = np.median([_step(log_profile(p), sz.w, kind) for p in parts], axis=0)
        med = median_filter(D, sz.win, mode="nearest")
        mad = median_filter(np.abs(D - med), sz.win, mode="nearest")
        e = np.abs(D - med) / np.maximum(1.4826 * mad, floor)
        if best is None:
            best, signed = e, D
        else:
            take = e > best
            best = np.where(take, e, best)
            signed = np.where(take, D, signed)
    best[:sz.margin] = 0
    best[-sz.margin:] = 0
    return best, signed


def sharpness(gray, x, sz):
    """Share of the brightness change around x between two neighbouring pixels:
    ~1 for a JPEG block edge, ~0.1-0.45 for a real line."""
    L = log_profile(gray)
    d1 = np.abs(np.diff(L))
    w2 = 2 * sz.w
    lo, hi = max(x - sz.sharp_px // 2, 0), min(x + sz.sharp_px // 2 + 1, len(d1))
    tot = d1[max(x - w2, 0):min(x + w2, len(d1))].sum()
    return float(d1[lo:hi].max() / max(tot, 1e-12)) if hi > lo else 0.0


def peaks(e, limit, merge):
    """Local maxima of e over limit, the strongest first, at least merge apart."""
    c = np.flatnonzero((e[1:-1] > limit) & (e[1:-1] >= e[:-2]) & (e[1:-1] > e[2:])) + 1
    taken = []
    for k in c[np.argsort(-e[c], kind="stable")]:
        if all(abs(k - t) >= merge for t in taken):
            taken.append(int(k))
    return sorted(taken)


def detect(gray, sigmas, sz):
    """Lines of a strip (preparation) -> (x list, strength list), before the gap rule.

    A peak counts with its strength times a sharpness factor (1 under
    SHARP_LO, 0 over SHARP_HI), so a JPEG block edge needs to be far stronger.
    """
    e, _ = line_strength(gray, sz)
    L = log_profile(gray)
    I = np.asarray(gray, float).mean(axis=0)
    xs, st = [], []
    for k in peaks(e, sigmas, sz.merge):
        f = float(np.clip((SHARP_HI - sharpness(gray, k, sz)) / (SHARP_HI - SHARP_LO), 0, 1))
        # a JPEG block edge is a few levels at most; a big sharp step is a line
        a, b = I[max(k - 2 * sz.w, 0)], I[min(k + 2 * sz.w, len(I) - 1)]
        if abs(b - a) >= JPEG_LEVELS:
            f = 1.0
        if e[k] * f > sigmas:
            xs.append(centre(L, k, sz.w))
            st.append(float(e[k] * f))
    return xs, st


def centre(L, k, w):
    """Position of a line near index k: the centre of the brightness change there.

    For a step that is the step; for a thin line (two opposite flanks) the
    middle between them - whichever measure found the peak.
    """
    g = np.abs(np.diff(uniform_filter1d(L, max(2, w // 2))))
    lo, hi = max(k - 2 * w, 0), min(k + 2 * w + 1, len(g))
    seg = g[lo:hi]
    if not len(seg):
        return float(k)
    seg = np.maximum(seg - np.median(seg), 0) ** 2
    if seg.sum() <= 0:
        return float(k)
    return float(lo + 0.5 + (np.arange(len(seg)) * seg).sum() / seg.sum())


# ---------------------------------------------------------------------------
# per-line templates and tracking
# ---------------------------------------------------------------------------
def gradient(L, w=4):
    """Smoothed gradient of the log profile (a slope gives a constant, a line a peak)."""
    return np.r_[0.0, np.diff(uniform_filter1d(L, w))]


def _piece(v, k, half):
    seg = v[k - half:k + half + 1] - v[k - half:k + half + 1].mean()
    n = np.linalg.norm(seg)
    return seg / n if n > 0 else None


def make_templates(L, xs, half):
    """Shape of every line: (brightness piece, gradient piece), zero-mean, unit length.

    None at the ends of the profile. The match uses both: a gentle slope between
    two lines looks like a step in brightness but not in the gradient, and
    noise can look like a line in the gradient but not in brightness.
    """
    G = gradient(L)
    out = []
    for x in xs:
        k = int(round(x))
        if k - half < 0 or k + half >= len(L):
            out.append(None)
            continue
        a, b = _piece(L, k, half), _piece(G, k, half)
        out.append((a, b) if a is not None and b is not None else None)
    return out


def ncc_map(v, t):
    """Normalized correlation of template t at every x (NaN where it does not fit)."""
    half = len(t) // 2
    n = len(v)
    out = np.full(n, np.nan)
    if n < len(t):
        return out
    win = np.lib.stride_tricks.sliding_window_view(v, len(t))
    win = win - win.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(win, axis=1)
    out[half:n - half] = np.where(norm > 0, win @ t / np.maximum(norm, 1e-12), np.nan)
    return out


def match_map(L, template, G=None):
    """Match of a line's template at every x: brightness x gradient correlation (0..1)."""
    G = gradient(L) if G is None else G
    a, b = template
    return np.clip(ncc_map(L, a), 0, 1) * np.clip(ncc_map(G, b), 0, 1)


def track(L, ref, temps, spacing, window=0.1, ncc_min=0.3, stretch=0.06, shift=0.5,
          maps=None, refine_maps=None):
    """Find the lines ``ref`` (with templates ``temps``) again in profile L.

    1. The whole row is stretched (+-stretch around the median line) and
       shifted (+-shift of the spacing) to where the sum of the correlations
       is largest.
    2. Every line is then refined within +-window of the spacing.
    Returns (positions or None per line, correlation per line, predicted positions).
    ``maps``: one score map (0..1) per line to use instead of the template
    matches; ``refine_maps``: other maps for step 2 only (the learned detector
    aligns the row with the templates and finds every line with its network).
    """
    ref = np.asarray(ref, float)
    G = gradient(L)
    if maps is None:
        maps = [match_map(L, t, G) if t is not None else None for t in temps]
    xs_axis = np.arange(len(L))
    centre = float(np.median(ref)) if len(ref) else 0.0

    def total(pred):
        v = 0.0
        for m, x in zip(maps, pred):
            if m is None or not 0 <= x < len(L) - 1:
                continue
            y = np.interp(x, xs_axis, np.nan_to_num(m, nan=-1.0))
            v += y
        return v

    best = (-np.inf, 1.0, 0.0)
    if len(ref) >= 2 and spacing:
        for a in np.linspace(1 - stretch, 1 + stretch, 25):
            base = centre + a * (ref - centre)
            for b in np.arange(-shift * spacing, shift * spacing + 1, 2.0):
                v = total(base + b)
                if v > best[0]:
                    best = (v, a, b)
        # finer shift around the best
        _, a, b0 = best
        for b in np.arange(b0 - 2, b0 + 2.01, 0.5):
            v = total(centre + a * (ref - centre) + b)
            if v > best[0]:
                best = (v, a, b)
    _, a, b = best
    pred = centre + a * (ref - centre) + b
    r = max(2, int(round(window * spacing))) if spacing else 10
    found, score = [], []
    for m, x in zip(refine_maps if refine_maps is not None else maps, pred):
        if m is None or not 0 <= x < len(L):
            found.append(None)
            score.append(np.nan)
            continue
        lo, hi = max(int(x) - r, 0), min(int(x) + r, len(L) - 1)
        seg = np.nan_to_num(m[lo:hi + 1], nan=-1.0)
        k = lo + int(np.argmax(seg))
        v = float(seg[k - lo])
        if v >= ncc_min:
            dx = 0.0
            if lo < k < hi:
                y0, y1, y2 = seg[k - lo - 1], seg[k - lo], seg[k - lo + 1]
                den = y0 - 2 * y1 + y2
                if den < 0:
                    dx = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
            found.append(k + dx)
        else:
            found.append(None)
        score.append(v)
    return found, score, list(pred)


def refresh(temps, L, found, score, half, alpha=0.15, min_ncc=0.5):
    """Let every well-found line's template follow its slowly changing shape."""
    new = []
    for t, x, s in zip(temps, found, score):
        if t is None or x is None or not s >= min_ncc:
            new.append(t)
            continue
        seg = make_templates(L, [x], half)[0]
        if seg is None:
            new.append(t)
            continue
        pair = []
        for old, cur in zip(t, seg):
            u = (1 - alpha) * old + alpha * cur
            n = np.linalg.norm(u)
            pair.append(u / n if n > 0 else old)
        new.append(tuple(pair))
    return new
