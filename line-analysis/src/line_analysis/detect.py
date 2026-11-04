"""Vertical line detection (column method).

1. The image is cut into ``n_blocks`` horizontal bands. Each band is reduced
   to one colour profile along x by taking the median over its rows (robust
   against dust and local defects).
2. Per colour channel a moving-median background (``bg_window`` px) is
   subtracted at 1-px resolution; the largest deviation over R, G and B is the
   line strength of that column. Colour steps between wide stripes stay in the
   background, only narrow features remain.
3. After a light smoothing, the band-averaged signal is searched for local
   maxima above ``max(k * sigma, rel * strong-response level)`` that are at
   least ``min_dist`` px apart (the strongest wins).
4. A candidate is accepted only if it is also visible (at least
   ``band_rel * threshold``, within ``x_tol`` px) in ``min_fraction`` of the
   bands. This removes specks and defects such as a bubble that covers only
   part of the image height, while faint lines in compressed video survive.

Size-dependent parameters (``bg_window``, ``min_dist``, ``x_tol``) default to
``None`` and are scaled from the image width (tuned on a 6000 px wide frame).
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np

REF_WIDTH = 6000.0
LINE_COLOR = (255, 0, 0)
MIN_THRESHOLD = 2.0      # 0-255 levels; never chase quantisation noise
MAD_TO_SIGMA = 1.4826


@dataclass
class DetectionConfig:
    """Detection parameters shared by the image, video and CLI entry points."""
    n_blocks: int = 8                      # horizontal bands that must agree
    bg_window: Optional[int] = None        # background filter width (px); None = from width
    k: float = 3.0                         # noise floor in sigmas
    rel: float = 0.25                      # floor as a fraction of the strong responses
    min_dist: Optional[int] = None         # minimum distance between lines (px); None = from width
    x_tol: Optional[int] = None            # max x shift between bands for one line (px); None = from width
    min_fraction: float = 0.6              # fraction of bands a line must appear in
    band_rel: float = 0.5                  # per-band visibility, as a fraction of the threshold
    smooth: int = 5                        # smoothing width (px) that merges split peaks
    half_width: int = 1                    # painted half-width of a line (px)
    strip_height: Optional[int] = 200        # analyse only this many rows around the image middle (None or 0 = all rows)
    min_threshold: float = MIN_THRESHOLD   # absolute floor of the threshold (0-255 levels); lower it for dark images


def moving_median(signal, window):
    """Median filter (edge padded): the local 'background' level."""
    window = max(3, int(window) | 1)
    pad = window // 2
    padded = np.pad(signal, pad, mode="edge")
    views = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(views, axis=1)


def auto_sizes(width, config):
    """(bg_window, min_dist, x_tol) from the config, filling gaps from the width."""
    s = width / REF_WIDTH
    bg = int(config.bg_window) if config.bg_window else max(15, int(round(100 * s)))
    md = int(config.min_dist) if config.min_dist else max(5, int(round(100 * s)))
    xt = int(config.x_tol) if config.x_tol else max(2, int(round(10 * s)))
    return bg | 1, md, xt


def line_signal(img, n_blocks=8, bg_window=101):
    """Line strength per band and column -> array (n_blocks x W)."""
    arr = np.asarray(img, dtype=np.float32)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=2)
    H, W, _ = arr.shape
    edges = np.linspace(0, H, n_blocks + 1, dtype=int)
    out = np.empty((n_blocks, W), np.float32)
    for b in range(n_blocks):
        prof = np.median(arr[edges[b]:edges[b + 1]], axis=0)         # (W, 3)
        dev = np.stack([prof[:, c] - moving_median(prof[:, c], bg_window)
                        for c in range(3)], axis=1)
        out[b] = np.abs(dev).max(axis=1)
    return out


def peaks_1d(sig, threshold, min_dist):
    """Local maxima >= threshold, at least min_dist apart (strongest wins)."""
    cand = np.flatnonzero((sig[1:-1] >= sig[:-2]) & (sig[1:-1] > sig[2:]) &
                          (sig[1:-1] >= threshold)) + 1
    cand = cand[np.argsort(-sig[cand])]
    kept = []
    for c in cand:
        if all(abs(c - k) >= min_dist for k in kept):
            kept.append(int(c))
    return sorted(kept)


def check_config(config):
    if config.n_blocks < 1:
        raise ValueError("n_blocks must be at least 1")
    if not 0 < config.min_fraction <= 1:
        raise ValueError("min_fraction must be in (0, 1]")


def compute_signal(img, config):
    """Smoothed line strength per band and column.

    Returns (signal n_blocks x W, bg_window, min_dist, x_tol) with the size
    parameters resolved to pixels.
    """
    img = np.asarray(img)
    h = img.shape[0]
    sh = config.strip_height
    if sh and sh < h:                            # None or 0 = all rows
        sh = max(int(sh), config.n_blocks)       # at least one row per band
        r0 = (h - sh) // 2
        img = img[r0:r0 + sh]
    width = img.shape[1]
    bg_window, min_dist, x_tol = auto_sizes(width, config)
    sig = line_signal(img, config.n_blocks, bg_window)
    if config.smooth > 1:
        kern = np.ones(config.smooth, np.float32) / config.smooth
        sig = np.stack([np.convolve(r, kern, mode="same") for r in sig])
    return sig, bg_window, min_dist, x_tol


def threshold_from(sig, config):
    """The detection threshold of a config for this signal."""
    mean_sig = sig.mean(axis=0)
    sigma = MAD_TO_SIGMA * float(np.median(mean_sig))
    # Flat or dark regions pull the median to ~0, so the threshold is never
    # allowed below a fraction of the strong responses.
    return max(config.k * sigma,
               config.rel * float(np.percentile(mean_sig, 99.5)),
               config.min_threshold)


def select_lines(sig, threshold, config, min_dist, x_tol, details=False):
    """Accept the lines of a signal at a given threshold.

    Candidates are local maxima of the band-averaged signal above ``threshold``
    (at least ``min_dist`` apart); each must also be visible in enough bands.
    Returns the sorted x positions, or with ``details=True`` a list of
    (x, band_positions, seen_bands) per line, where band_positions are the
    positions of the response in the bands that saw the line.
    """
    width = sig.shape[1]
    need = max(1, int(np.ceil(config.min_fraction * config.n_blocks)))
    found = []
    for c in peaks_1d(sig.mean(axis=0), threshold, min_dist):
        lo, hi = max(0, c - x_tol), min(width, c + x_tol + 1)
        seg = sig[:, lo:hi]
        seen = seg.max(axis=1) >= config.band_rel * threshold
        if seen.sum() >= need:
            pos = lo + seg[seen].argmax(axis=1)
            found.append((float(np.median(pos)), pos, int(seen.sum())))
    return found if details else [f[0] for f in found]


def detect_lines(img, config=None):
    """Detect vertical lines. Returns (positions, signal, threshold).

    positions: sorted x of every accepted line (median over the bands).
    signal:    line strength, array (n_blocks x W), after smoothing.
    threshold: the detection threshold that was applied.
    """
    config = config or DetectionConfig()
    check_config(config)
    sig, _, min_dist, x_tol = compute_signal(img, config)
    threshold = threshold_from(sig, config)
    return select_lines(sig, threshold, config, min_dist, x_tol), sig, threshold


def mark_image(img, xs, half_width=1):
    """Copy of the image (same size) with each line painted red."""
    marked = np.array(img, dtype=np.uint8, copy=True)
    for x in xs:
        x = int(round(x))
        marked[:, max(0, x - half_width):x + half_width + 1] = LINE_COLOR
    return marked


def plot_line_signal(sig, xs, threshold, out_path):
    """Plot the band-averaged line strength with the accepted lines marked."""
    from .style import BLUE, MUTED, ORANGE, figure, finish

    mean_sig = sig.mean(axis=0)
    fig, ax = figure(figsize=(12, 4))
    ax.plot(mean_sig, lw=1.0, color=BLUE, label="line strength (mean of bands)")
    ax.axhline(threshold, color=MUTED, ls="--", lw=1, label="threshold")
    xi = np.round(xs).astype(int)
    ax.plot(xi, mean_sig[xi], "o", ms=5, color=ORANGE, mec="white", mew=1,
            label="accepted lines")
    ax.set_xlabel("x position (px)")
    ax.set_ylabel("deviation from background (0-255)")
    ax.legend(frameon=False)
    finish(fig, out_path)
