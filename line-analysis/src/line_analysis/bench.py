"""Test bench: synthetic photo series with known lines, and a score for every method.

``analysis bench`` (or run_bench()) makes series of photos whose true line
positions are known, runs the detection methods on them and prints how close
each comes to the true spacing. The photos imitate the real ones:

  dark    red light like series 08: only R is bright (~110 in the middle,
          down to ~10 at the edges), G and B nearly 0; the lines are steps
          down left of the centre and up right of it (large at the edges, a
          thin 2 % line at the centre), JPEG compressed (quality 92), so the
          noise between rows is only ~0.3 levels.
  bright  orange like the pE-300 photos: R saturated, G ~130; contrast ~3x.

Every series: the spacing follows a ramp (up and down) and the lines spread
from the centre; the bands are uneven (0.45-1.4 x the spacing, some narrow),
the lines wiggle by ~1 px along y, and there is dust and a fixed scratch.
Made to look like the real photos in tests/data/real (compare their profiles).

Score per method and series (photo by photo, against the true positions in
the analysed part of the photo):
  err_med / err_p95   median / 95th percentile of |spacing error| in %
  bad                 photos with |error| > 2 %
  hits / false        found lines within 8 % of the spacing of a true line /
                      found lines that are not
"""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image



@dataclass
class SeriesSpec:
    name: str = "dark"
    kind: str = "dark"            # dark | bright
    n: int = 24                   # photos
    width: int = 2400
    height: int = 400
    spacing: tuple = (210.0, 260.0)  # px at the ramp ends (up, then down again)
    faint: float = 0.35           # fraction of lines whose thin line is at 30-60 %
    contrast: float = 1.0         # scale of all line contrasts
    seed: int = 0


def _background(spec, rng):
    x = np.linspace(-1, 1, spec.width)
    y = np.linspace(-1, 1, spec.height)
    vig = np.clip(1 - 0.95 * np.abs(x) ** 1.8, 0.06, 1)                 # dark edges in x
    return np.outer(1 - 0.03 * y ** 2, vig)


def _scene(spec, spacing, phase, irregular, strength, rng):
    """(relative brightness change, true x of the lines in the middle row).

    As in the real photos of series 08: every band between two lines gets
    brighter towards the bright centre of the photo and changes by a step at
    the line, so the step goes DOWN left of the centre and UP right of it, and
    is large in the dark edges and small near the centre; every line also has
    a thin dark line (~2 %), which is all that is left of it at the centre.
    The bands are uneven (``irregular``: widths 0.45-1.4 x the spacing).
    """
    W, H = spec.width, spec.height
    centre = 0.5 * W
    widths = spacing * irregular
    k0 = int(np.argmin(np.abs(np.cumsum(widths) - 0.5 * len(widths) * spacing)))
    base = np.cumsum(widths) - np.cumsum(widths)[k0] + centre + phase * spacing
    keep = (base > -spacing) & (base < W + spacing)
    idx = np.flatnonzero(keep)
    xs0, amp = base[keep], strength[idx]
    rows = np.arange(H)
    img = np.zeros((H, W))
    xx = np.arange(W)[None, :]
    wig = rng.normal(0, 1, (len(xs0), H // 20 + 2)).cumsum(axis=1) * 0.35   # ~1 px wiggle
    t = np.arange(wig.shape[1]) * 20
    xr_all = [x0 + np.interp(rows, t, wig[i])[:, None] for i, x0 in enumerate(xs0)]
    for i in range(len(xs0) - 1):
        xa, xb = xr_all[i], xr_all[i + 1]
        mid = 0.5 * (xs0[i] + xs0[i + 1])
        a = spec.contrast * (0.02 + 0.45 * min(abs(mid - centre) / (0.5 * W), 1) ** 1.3)
        sgn = 1.0 if mid < centre else -1.0
        inside = (xx >= xa) & (xx < xb)
        img += inside * sgn * a * ((xx - xa) / np.maximum(xb - xa, 1) - 0.5)
    for i, a in enumerate(amp):
        img -= a * spec.contrast * 0.02 * np.exp(
            -0.5 * ((xx - xr_all[i]) / (0.012 * spacing)) ** 2)
    true_mid = np.array([x0 + np.interp(H // 2, t, wig[i]) for i, x0 in enumerate(xs0)])
    return img, np.sort(true_mid)


def _defects(spec, rng, img):
    H, W = img.shape
    yy, xx = np.mgrid[0:H, 0:W]
    for _ in range(25):                                                  # dust
        cx, cy, r = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(2, 7)
        img -= 0.05 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))
    sx = int(0.62 * W)                                                   # a fixed scratch
    img[:, sx:sx + 2] += 0.03
    return img


def make_photo(spec, spacing, phase, irregular, strength, seed):
    """(RGB uint8 photo as it comes out of the camera (JPEG), true line x)."""
    rng = np.random.default_rng(seed)
    rel, xs = _scene(spec, spacing, phase, irregular, strength, rng)
    # the optics spread a line over a few px (as in the real photos)
    k = np.exp(-0.5 * (np.arange(-5, 6) / 1.5) ** 2)
    k /= k.sum()
    rel = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, rel)
    rel = _defects(spec, np.random.default_rng(spec.seed + 999), rel)    # dust stays put
    light = _background(spec, rng) * (1 + rel)
    if spec.kind == "dark":
        r = 112 * light + rng.normal(0, 0.9, light.shape)
        g = 0.7 + rng.normal(0, 0.5, light.shape)
        b = 6 * light + rng.normal(0, 0.6, light.shape)
        scale = 3.0
    else:
        r = 300 * light + rng.normal(0, 1.5, light.shape)               # saturates
        g = 140 * light + rng.normal(0, 1.2, light.shape)
        b = 15 * light + rng.normal(0, 0.8, light.shape)
        scale = 1.0
    rgb = np.clip(np.stack([r, g, b], axis=2), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=92)
    img = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    return img, xs


def make_series(spec):
    """[(photo, true x)] of a whole ramp series."""
    rng = np.random.default_rng(spec.seed)
    s0, s1 = spec.spacing
    half = spec.n // 2
    ramp = np.r_[np.linspace(s0, s1, half), np.linspace(s1, s0, spec.n - half)]
    irregular = np.clip(rng.normal(1.0, 0.15, 81), 0.45, 1.4)            # uneven bands
    irregular[rng.choice(81, 8, replace=False)] = rng.uniform(0.4, 0.6, 8)  # narrow ones
    strength = np.where(rng.random(81) < spec.faint, rng.uniform(0.3, 0.6, 81),
                        rng.uniform(0.8, 1.2, 81))
    phase = rng.uniform(0, 1)
    return [make_photo(spec, s, phase, irregular, strength, spec.seed * 1000 + i)
            for i, s in enumerate(ramp)]


def true_spacing(xs, lo, hi):
    """Mean distance between the neighbouring true lines in [lo, hi] (bands are uneven)."""
    inside = [x for x in xs if lo <= x <= hi]
    return (float(np.mean(np.diff(inside))) if len(inside) >= 2 else None), inside


def score(found, xs, lo, hi, spacing=None):
    """(error % of the spacing, hits, false) of found lines vs true x in [lo, hi].

    ``spacing``: the method's own spacing (default: from the found lines).
    """
    from .jumps import spacing_with_rule
    sp_true, inside = true_spacing(xs, lo, hi)
    sp = spacing if spacing is not None else (
        spacing_with_rule(found).spacing if len(found) >= 2 else None)
    if sp is None or sp_true is None:
        return np.nan, 0, len(found)
    tol = 0.08 * sp_true
    t = np.asarray(inside)
    hits = sum(np.any(np.abs(t - x) < tol) for x in found)
    return 100 * (sp / sp_true - 1), hits, len(found) - hits


# ---------------------------------------------------------------------------
# methods: f(series) -> [found x per photo] (whole-photo x), analysed range
# ---------------------------------------------------------------------------
def method_contrast(series):
    """analysis folder default: contrast features on the middle 300 rows, 100 px cut."""
    from . import contrast as C
    out = []
    for img, _ in series:
        h = img.shape[0]
        strip = img[(h - 300) // 2:(h - 300) // 2 + 300, 100:-100]
        out.append([x + 100 for x, _ in C.find_features(C.contrast_profile(strip))])
    return out, None, 100


def method_jumps(series, detector):
    """analysis jumps, non-interactive (--yes), with the given detector."""
    from .detect import REF_WIDTH
    from .jumps import JumpConfig, run_series
    cfg = JumpConfig(detector=detector)
    res = run_series([img for img, _ in series], cfg, details=True)
    edge = int(round(cfg.edge * series[0][0].shape[1] / REF_WIDTH))
    margin = 30 if detector == "template" else 0
    return [r.lines for r in res], [r.spacing.spacing for r in res], edge + margin


METHODS = {
    "contrast (folder)": method_contrast,
    "jumps threshold": lambda s: method_jumps(s, "threshold"),
    "jumps template": lambda s: method_jumps(s, "template"),
}

DEFAULT_SERIES = (
    SeriesSpec("dark", "dark", spacing=(210.0, 260.0), seed=1),
    SeriesSpec("dark, wide", "dark", spacing=(270.0, 340.0), seed=2),
    SeriesSpec("dark, low contrast", "dark", spacing=(210.0, 260.0), faint=0.6, contrast=0.6,
               seed=3),
    SeriesSpec("bright", "bright", spacing=(210.0, 260.0), seed=4),
)


def run_bench(series_specs=DEFAULT_SERIES, methods=None, verbose=True):
    """Score every method on every series -> list of dicts (one per method and series)."""
    methods = methods or METHODS
    results = []
    for spec in series_specs:
        series = make_series(spec)
        for name, method in methods.items():
            found, spacings, edge = method(series)
            spacings = spacings or [None] * len(found)
            # the true spacing over the same span as the found lines (the bands are
            # uneven, so a line more or less at the edge changes the mean distance)
            rows = [score(f, xs, max(edge, min(f) - 15) if len(f) else edge,
                          min(spec.width - edge, max(f) + 15) if len(f) else spec.width - edge,
                          sp)
                    for f, sp, (_, xs) in zip(found, spacings, series)]
            err = np.abs(np.array([r[0] for r in rows], float))
            n_true = np.mean([len(true_spacing(xs, edge, spec.width - edge)[1])
                              for _, xs in series])
            res = {"series": spec.name, "method": name,
                   "err_med": float(np.nanmedian(err)),
                   "err_p95": float(np.nanpercentile(err, 95)),
                   "bad": int(np.sum(~(err <= 2.0))),
                   "photos": len(series),
                   "hits": float(np.mean([r[1] for r in rows])) / n_true,
                   "false": float(np.mean([r[2] for r in rows]))}
            results.append(res)
            if verbose:
                print(f"{spec.name:18s} {name:20s} err median {res['err_med']:5.2f} %  "
                      f"p95 {res['err_p95']:6.2f} %  bad {res['bad']:2d}/{res['photos']}  "
                      f"lines found {100 * res['hits']:4.0f} %  false {res['false']:4.1f}")
    return results
