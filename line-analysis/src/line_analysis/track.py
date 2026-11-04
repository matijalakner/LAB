"""Line tracking from photo to photo (alternative to detecting every photo anew).

The first photo is tuned and confirmed as usual; its line positions become the
reference. Every later photo is searched only around the reference positions:

  1. Each reference line ``x`` gets a bracket. A line is first looked for in
     ``x +- x_tolerance`` (narrow). If nothing is there, the search widens to
     half the distance to the neighbouring reference line on each side (wide),
     so neighbouring wide brackets touch but never overlap.
  2. A bracket holds at most one line: the strongest confirmed peak in it.
  3. A bracket whose wide range reaches past the image edge may be empty (the
     line has left the picture). Every other bracket must hold one line.
  4. If a required bracket is still empty, the detection threshold (the
     minimum contrast) is lowered step by step (``contrast_steps``) and the
     empty brackets are searched again, narrow first, then wide.
  5. If a required bracket stays empty after the last step, the photo is
     *reported*: its result gets a warning and the next photo is searched
     around the previous reference positions. Otherwise the found positions
     become the reference for the next photo (an empty edge bracket keeps its
     old position, so a line that comes back into the picture is found again).

A peak counts as a line with the same rules as the normal detection: a local
maximum of the band-averaged signal above the threshold that is also visible
(``band_rel * threshold``) in ``min_fraction`` of the bands.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

CONTRAST_STEPS = (1.0, 0.7, 0.5, 0.35)


@dataclass
class TrackingConfig:
    """Settings of the line tracking."""
    x_tolerance: Optional[float] = None    # narrow search half-width (px); None = 0.2 * median spacing
    contrast_steps: Tuple[float, ...] = CONTRAST_STEPS   # threshold factors, tried in order


def check_tracking(tracking):
    steps = tuple(tracking.contrast_steps)
    if not steps or any(not 0 < s <= 1 for s in steps):
        raise ValueError("contrast_steps must be factors in (0, 1]")
    if tracking.x_tolerance is not None and tracking.x_tolerance <= 0:
        raise ValueError("x_tolerance must be positive")


def resolve_tolerance(reference, tracking, x_tol=2):
    """The narrow search half-width in px for this reference."""
    if tracking.x_tolerance:
        return float(tracking.x_tolerance)
    ref = np.sort(np.asarray(reference, dtype=float))
    if len(ref) < 2:
        return float(max(3 * x_tol, 10))
    return float(max(x_tol, 0.2 * np.median(np.diff(ref))))


def brackets(reference, width, tolerance):
    """Search ranges per reference line.

    Returns a list of dicts: x, narrow (lo, hi), wide (lo, hi), optional
    (True if the wide range reaches past the image edge, so the bracket may
    be empty). Ranges are half-open [lo, hi) in px.
    """
    ref = np.sort(np.asarray(reference, dtype=float))
    gaps = np.diff(ref)
    out = []
    for i, x in enumerate(ref):
        if len(ref) == 1:
            left = right = 3 * tolerance
        else:
            left = 0.5 * (gaps[i - 1] if i > 0 else gaps[0])
            right = 0.5 * (gaps[i] if i < len(gaps) else gaps[-1])
        tol = min(tolerance, left, right)          # narrow always inside wide
        wide = (x - left, x + right)
        out.append({"x": float(x), "narrow": (x - tol, x + tol), "wide": wide,
                    "optional": wide[0] < 0 or wide[1] > width - 1})
    return out


def _local_maxima(mean_sig):
    s = mean_sig
    return np.flatnonzero((s[1:-1] >= s[:-2]) & (s[1:-1] > s[2:])) + 1


def _best_in(sig, mean_sig, maxima, lo, hi, threshold, config, x_tol):
    """Strongest confirmed line with its peak in [lo, hi), or None."""
    width = sig.shape[1]
    need = max(1, int(np.ceil(config.min_fraction * config.n_blocks)))
    cand = maxima[(maxima >= lo) & (maxima < hi)]
    cand = cand[mean_sig[cand] >= threshold]
    for c in cand[np.argsort(-mean_sig[cand])]:
        a, b = max(0, c - x_tol), min(width, c + x_tol + 1)
        seg = sig[:, a:b]
        seen = seg.max(axis=1) >= config.band_rel * threshold
        if seen.sum() >= need:
            return float(np.median(a + seg[seen].argmax(axis=1)))
    return None


def track_lines(sig, reference, threshold, config, x_tol, tracking=None):
    """Find the lines of one photo near the reference positions.

    sig        line signal of the photo (n_blocks x W), from compute_signal
    reference  x positions found in the previous photo
    threshold  the normal detection threshold of this photo (threshold_from)
    config     DetectionConfig (min_fraction, band_rel, n_blocks are used)
    x_tol      allowed x shift between the bands (px)

    Returns a dict:
      lines       sorted x of the lines found
      reported    True if a required bracket stayed empty
      missing     reference x of the required brackets left empty
      left        reference x of edge brackets left empty (allowed)
      reference   the reference for the next photo
      widened     number of lines found only in the wide range
      lowered     number of lines found only below the normal threshold
      min_factor  lowest contrast factor that was needed (1.0 = none)
      tolerance   narrow half-width used (px)
    """
    tracking = tracking or TrackingConfig()
    check_tracking(tracking)
    reference = [float(x) for x in sorted(reference)]
    if not reference:
        raise ValueError("tracking needs at least one reference line")
    width = sig.shape[1]
    tol = resolve_tolerance(reference, tracking, x_tol)
    brs = brackets(reference, width, tol)
    mean_sig = sig.mean(axis=0)
    maxima = _local_maxima(mean_sig)

    found = [None] * len(brs)
    how = [None] * len(brs)
    for factor in tracking.contrast_steps:
        thr = threshold * factor
        for i, br in enumerate(brs):
            if found[i] is not None:
                continue
            if br["optional"] and factor != tracking.contrast_steps[0]:
                continue                       # an edge bracket may be empty: no lowering
            for stage in ("narrow", "wide"):
                x = _best_in(sig, mean_sig, maxima, *br[stage], thr, config, x_tol)
                if x is not None:
                    found[i], how[i] = x, (stage, factor)
                    break
        if all(f is not None or br["optional"] for f, br in zip(found, brs)):
            break

    missing = [br["x"] for f, br in zip(found, brs) if f is None and not br["optional"]]
    left = [br["x"] for f, br in zip(found, brs) if f is None and br["optional"]]
    reported = bool(missing)
    lines = sorted(f for f in found if f is not None)
    if reported:
        next_ref = reference
    else:
        next_ref = [f if f is not None else br["x"] for f, br in zip(found, brs)]
    used = [h for h in how if h is not None]
    first = tracking.contrast_steps[0]
    return {"lines": lines, "reported": reported, "missing": missing, "left": left,
            "reference": sorted(next_ref),
            "widened": sum(1 for h in used if h[0] == "wide"),
            "lowered": sum(1 for h in used if h[1] < first),
            "min_factor": min((h[1] for h in used), default=first),
            "tolerance": tol}
