"""Learned line detector for ``analysis jumps --detector learned``.

A small neural network (numpy only) learns from the photos of the series what
a line looks like, and gives every x of the analysis strip a probability that
a line is there.

How it learns:
  * the preparation finds the lines of the first photo as before and you
    accept them (y/n);
  * the network is then trained on that photo: many strips of ``rows`` rows
    (as thin as the analysis strip, so it learns their noise) from different
    heights, every x within ~1.5 px of an accepted line is "line", every x
    further than ~12 % of the spacing is "no line" (the x in between is not
    used, so the exact centre does not have to be perfect);
  * every photo accepted without doubts later is added to what it learned
    (``--no-learn`` stops that), so slow changes of the line shapes and of
    the light are followed;
  * the trained network is saved as line_model.npz and can be loaded for
    another series with ``--model FILE``: then it starts already trained.

What the network sees at every x: the log brightness and its gradient in a
window of +-``half`` px around x (in units of the local noise, so bright and
dark parts look alike), and the classical line strength there. It has one
hidden layer of 32 units.

Following the lines from photo to photo works as with the template detector
(every line keeps its own template, so it is known which line is which): the
whole row of lines is shifted and stretched to fit the templates, then every
line is searched within +-window of the spacing where sqrt(probability x
template match) is highest, and found if that is over sqrt(p_min x ncc_min).
So the network decides what is a line (dust, scratches and edges it has been
shown as "no line" do not count), the template which line it is. The photo's
quality score (doubtful photos) stays the template match.
"""
from pathlib import Path

import numpy as np

from .lines import NOISE_FLOOR_LEVELS, centre, gradient, line_strength, log_profile, median_filter, \
    peaks, uniform_filter1d

P_MIN = 0.5          # a line is found where the probability is over this
HIDDEN = 32
MAX_SAMPLES = 120_000   # what the network remembers (oldest dropped first)


def _windows(v, half, step):
    """Rows of v[x + o] for o in -half..half (every ``step``), one row per x (edge padded)."""
    p = np.pad(np.asarray(v, float), half, mode="edge")
    w = np.lib.stride_tricks.sliding_window_view(p, 2 * half + 1)
    return w[:, ::step]


def features(gray, sz):
    """Feature matrix (one row per x of the strip) of a rows x cols brightness strip."""
    gray = np.asarray(gray, float)
    L = log_profile(gray)
    G = gradient(L)
    rows = max(gray.shape[0], 1)
    level = uniform_filter1d(gray.mean(axis=0), sz.win)
    floor = 0.5 * NOISE_FLOOR_LEVELS / np.sqrt(rows) / (level + 1)
    med = median_filter(G, sz.win)
    s = np.maximum(1.4826 * median_filter(np.abs(G - med), sz.win), floor)
    half = sz.half
    step = max(1, half // 15)
    zg = np.tanh((G - med) / s / 4.0)
    zl = (L - uniform_filter1d(L, 2 * half + 1)) / (s * half / 4.0)
    e, _ = line_strength(gray, sz, bands=1 if rows < 20 else 6)
    Wg = _windows(zg, half, step)
    Wl = _windows(zl, half, step)
    Wl = np.tanh((Wl - Wl[:, [Wl.shape[1] // 2]]) / 3.0)      # relative to the centre
    We = np.tanh(_windows(e, half, max(step, half // 4)) / 6.0)
    return np.hstack([Wg, Wl, We]).astype(np.float32)


class LineModel:
    """One hidden layer network: features -> probability of a line."""

    def __init__(self, n_in=None, seed=0):
        self.rng = np.random.default_rng(seed)
        self.n_in = n_in
        self.params = None
        self.mu = self.sd = None
        self.X = self.y = None
        if n_in:
            self._init(n_in)

    def _init(self, n_in):
        self.n_in = n_in
        r = self.rng
        self.params = {"W1": (r.normal(0, 1, (n_in, HIDDEN)) / np.sqrt(n_in)).astype(np.float32),
                       "b1": np.zeros(HIDDEN, np.float32),
                       "W2": (r.normal(0, 1, (HIDDEN, 1)) / np.sqrt(HIDDEN)).astype(np.float32),
                       "b2": np.zeros(1, np.float32)}
        self._adam = {k: (np.zeros_like(v), np.zeros_like(v)) for k, v in self.params.items()}
        self._t = 0

    @property
    def trained(self):
        return self.params is not None and self.mu is not None

    # data ---------------------------------------------------------------------
    @staticmethod
    def samples(strips, lines, spacing, sz, lo=None, hi=None):
        """(X, y) from strips (each rows x cols) whose lines are at ``lines`` (strip x)."""
        width = strips[0].shape[1]
        pos_r = max(1.0, 1.5 * width / 2576)
        neg_r = max(3 * pos_r, 0.12 * spacing)
        lines = np.sort(np.asarray(lines, float))
        lo = sz.margin if lo is None else max(lo, sz.margin)
        hi = width - sz.margin if hi is None else min(hi, width - sz.margin)
        X, y = [], []
        for g in strips:
            F = features(g, sz)
            L = log_profile(g)
            # the line may sit a px or two away in another strip: put it on the
            # centre of the brightness change there, as the preparation does
            r = max(2, int(round(2 * pos_r)))
            here = []
            for x in lines:
                c = centre(L, int(round(x)), sz.w)
                here.append(c if abs(c - x) <= r else x)
            here = np.asarray(here, float)
            xs = np.arange(width)
            d = np.min(np.abs(xs[:, None] - here[None, :]), axis=1) if len(here) else \
                np.full(width, np.inf)
            use = (xs >= lo) & (xs < hi) & ((d <= pos_r) | (d >= neg_r))
            X.append(F[use])
            y.append((d[use] <= pos_r).astype(np.float32))
        return np.vstack(X), np.concatenate(y)

    def add(self, X, y):
        if self.X is None:
            self.X, self.y = X, y
        else:
            self.X, self.y = np.vstack([self.X, X]), np.concatenate([self.y, y])
        if len(self.y) > MAX_SAMPLES:
            # keep every line sample, drop the oldest no-line samples
            pos = np.flatnonzero(self.y > 0.5)
            neg = np.flatnonzero(self.y <= 0.5)
            neg = neg[-(MAX_SAMPLES - len(pos)):] if len(pos) < MAX_SAMPLES else neg[:0]
            keep = np.sort(np.r_[pos[-MAX_SAMPLES:], neg])
            self.X, self.y = self.X[keep], self.y[keep]

    # training -----------------------------------------------------------------
    def _forward(self, Xn):
        P = self.params
        h = np.maximum(Xn @ P["W1"] + P["b1"], 0)
        z = (h @ P["W2"] + P["b2"])[:, 0]
        return h, z

    def fit(self, epochs=300, lr=3e-3, batch=8192, l2=1e-4):
        """Train on everything added so far (class-balanced logistic loss, Adam)."""
        X, y = self.X, self.y
        if X is None or len(np.unique(y)) < 2:
            return self
        if self.params is None or self.n_in != X.shape[1]:
            self._init(X.shape[1])
        if self.mu is None:
            self.mu = X.mean(axis=0)
            self.sd = X.std(axis=0) + 1e-3
        Xn = (X - self.mu) / self.sd
        npos = max(y.sum(), 1.0)
        wpos, wneg = 0.5 / npos, 0.5 / max(len(y) - npos, 1.0)
        w = np.where(y > 0.5, wpos, wneg).astype(np.float32) * len(y)
        n = len(y)
        b1, b2, eps = 0.9, 0.999, 1e-8
        for _ in range(epochs):
            idx = self.rng.permutation(n)[:batch] if n > batch else np.arange(n)
            xb, yb, wb = Xn[idx], y[idx], w[idx]
            h, z = self._forward(xb)
            p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
            dz = (wb * (p - yb) / len(yb))[:, None]
            P = self.params
            grads = {"W2": h.T @ dz + l2 * P["W2"], "b2": dz.sum(0)}
            dh = (dz @ P["W2"].T) * (h > 0)
            grads["W1"] = xb.T @ dh + l2 * P["W1"]
            grads["b1"] = dh.sum(0)
            self._t += 1
            for k, g in grads.items():
                m, v = self._adam[k]
                m[:] = b1 * m + (1 - b1) * g
                v[:] = b2 * v + (1 - b2) * g * g
                mh = m / (1 - b1 ** self._t)
                vh = v / (1 - b2 ** self._t)
                P[k] -= (lr * mh / (np.sqrt(vh) + eps)).astype(np.float32)
        return self

    # use ----------------------------------------------------------------------
    def prob(self, gray, sz):
        """Probability of a line at every x of a strip (0 within the margins)."""
        F = features(gray, sz)
        _, z = self._forward((F - self.mu) / self.sd)
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        p[:sz.margin] = 0
        p[-sz.margin:] = 0
        return p

    def find(self, gray, sz, p_min=P_MIN):
        """Lines of a strip without following: peaks of the probability -> (x, p) lists."""
        p = self.prob(gray, sz)
        ks = peaks(p, p_min, sz.merge)
        return [refine(p, k) for k in ks], [float(p[k]) for k in ks]

    # file ---------------------------------------------------------------------
    def save(self, path):
        np.savez_compressed(Path(path), mu=self.mu, sd=self.sd,
                            **{k: v for k, v in self.params.items()})

    @classmethod
    def load(cls, path):
        d = np.load(Path(path))
        m = cls(int(d["W1"].shape[0]))
        m.params = {k: d[k].astype(np.float32) for k in ("W1", "b1", "W2", "b2")}
        m.mu, m.sd = d["mu"], d["sd"]
        return m


def refine(p, k):
    """Sub-pixel position of a probability peak at index k (centroid of +-2 px)."""
    lo, hi = max(k - 2, 0), min(k + 3, len(p))
    w = np.maximum(p[lo:hi] - 0.5 * p[k], 0)
    return float(lo + (np.arange(hi - lo) * w).sum() / w.sum()) if w.sum() > 0 else float(k)


def training_strips(gray_full, rows, n=24, spread=None):
    """``n`` strips of ``rows`` rows from the middle of a (rows x cols) brightness image."""
    h = gray_full.shape[0]
    spread = spread or h
    lo = max(0, h // 2 - spread // 2)
    hi = min(h - rows, h // 2 + spread // 2 - rows)
    starts = np.unique(np.linspace(lo, max(lo, hi), n).astype(int))
    return [gray_full[s:s + rows] for s in starts]
