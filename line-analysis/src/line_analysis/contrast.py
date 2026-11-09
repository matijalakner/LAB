"""Line detection from the contrast profile of a photo.

  1. Every pixel gets a contrast (I - background) / background, with I the mean
     of R, G and B and the background a moving median along x.
  2. The contrast is averaged over y, which gives a profile along x.
  3. Stretches where |contrast| exceeds the threshold, and that lie close
     together, are one feature. A bright peak followed by a dark dip is a line
     at the zero crossing between them; anything else is "one-sided" and
     placed at its largest extremum.
  4. Dust and defects stay at the same x while the lines move. One-sided
     features found at the same x in several of a few evenly spread photos,
     and visible there in all of them (fixed_positions), are not counted as lines.
"""
from dataclasses import dataclass

import numpy as np

from .detect import REF_WIDTH, moving_median


@dataclass
class ContrastConfig:
    """Sizes are in px for a photo REF_WIDTH wide and scale with the width."""
    threshold: float = 0.025     # |contrast| that starts a feature
    bg_window: int = 101         # moving median along x, the background
    merge_gap: int = 60          # stretches closer than this are one feature
    fixed_tol: int = 25          # same x within this many px counts as not moving
    fixed_photos: int = 3        # a feature in this many spread photos is a defect


def sizes(width, config):
    """(bg_window, merge_gap, fixed_tol) in px for this photo width."""
    s = width / REF_WIDTH
    return (max(15, int(round(config.bg_window * s))) | 1,
            max(3, int(round(config.merge_gap * s))),
            max(2, int(round(config.fixed_tol * s))))


def contrast_profile(img, config=None):
    """Contrast of every pixel averaged over y -> array of length W."""
    config = config or ContrastConfig()
    gray = np.asarray(img, dtype=np.float32).mean(axis=2)
    window = sizes(gray.shape[1], config)[0]
    background = np.stack([moving_median(row, window) for row in gray])
    return ((gray - background) / np.maximum(background, 1.0)).mean(axis=0)


def find_features(profile, config=None):
    """[(x, two_sided)] of the features of a contrast profile, sorted by x."""
    config = config or ContrastConfig()
    smooth = np.convolve(profile, np.ones(3) / 3, mode="same")
    above = np.flatnonzero(np.abs(smooth) > config.threshold)
    if not len(above):
        return []
    gap = sizes(len(profile), config)[1]
    features = []
    for run in np.split(above, np.flatnonzero(np.diff(above) > gap) + 1):
        lo, hi = max(0, run[0] - 5), min(len(smooth), run[-1] + 6)
        seg = smooth[lo:hi]
        top, bottom = lo + int(seg.argmax()), lo + int(seg.argmin())
        if seg.max() > config.threshold and seg.min() < -config.threshold and top < bottom:
            z = top + int(np.flatnonzero(smooth[top:bottom + 1] <= 0)[0])
            step = smooth[z] - smooth[z - 1]
            features.append((float(z - smooth[z] / step) if step else float(z), True))
        else:
            x = top if seg.max() > -seg.min() else bottom
            features.append((float(x), False))
    return features


def fixed_positions(feature_lists, profiles, config=None):
    """x of the defects: one-sided features that do not move between the photos.

    A defect is a one-sided feature in ``fixed_photos`` photos at the same x
    that also shows, at least at half the threshold, in every photo. A line
    that only comes back to an x (a ramp going up and down) is not everywhere.
    Returns [] when defects would be most of all features: then the lines
    themselves are not moving and cannot be told from defects this way.
    """
    config = config or ContrastConfig()
    tol = sizes(len(profiles[0]), config)[2]
    smooth = [np.convolve(p, np.ones(3) / 3, mode="same") for p in profiles]
    singles = [(i, x) for i, feats in enumerate(feature_lists) for x, two in feats if not two]

    def everywhere(x):
        lo, hi = max(0, int(x) - tol), int(x) + tol + 1
        return all(np.abs(p[lo:hi]).max() >= config.threshold / 2 for p in smooth)

    fixed = sorted(x for _, x in singles
                   if len({j for j, y in singles if abs(y - x) <= tol}) >= config.fixed_photos
                   and everywhere(x))
    if len(fixed) > sum(map(len, feature_lists)) / 2:
        return []
    groups = []
    for x in fixed:
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [float(np.median(g)) for g in groups]


def select_lines(features, defects, width, config=None):
    """x of the lines: the features without the one-sided ones at a defect."""
    config = config or ContrastConfig()
    tol = sizes(width, config)[2]
    return [x for x, two in features
            if two or not any(abs(x - d) <= tol for d in defects)]
