"""Fit functions for the report plots (numpy only).

Every model is linear in all its parameters but at most one (the shape
parameter: k, n or K). That one is found on a log grid, refined around the
best value, and the others by least squares, so a fit cannot fail to converge.

    fit_curve(x, y, "auto")   -> Fit or None
    fit.predict(xx)           -> y on new x
"""
from dataclasses import dataclass

import numpy as np

# name -> formula shown in the legend and fits.csv
FORMULAS = {
    "linear": "a·x + c",
    "quadratic": "a·x + b·x² + c",
    "cubic": "a·x + b·x² + d·x³ + c",
    "saturating": "A·(1 − exp(−x/k)) + c",
    "power": "a·xⁿ + c",
    "mm": "A·x/(K + x) + c",
}
PARAM_NAMES = {
    "linear": ("a", "c"),
    "quadratic": ("a", "b", "c"),
    "cubic": ("a", "b", "d", "c"),
    "saturating": ("A", "k", "c"),
    "power": ("a", "n", "c"),
    "mm": ("A", "K", "c"),
}
MODELS = tuple(FORMULAS)
# 'auto' chooses among these by AICc; cubic is left out (4 parameters, wiggles
# between the steps of a short ramp)
AUTO_MODELS = ("linear", "quadratic", "saturating", "power", "mm")
FIT_CHOICES = MODELS + ("auto", "none")


@dataclass
class Fit:
    model: str
    params: tuple
    r2: float
    rmse: float
    aicc: float
    n: int

    @property
    def formula(self):
        return FORMULAS[self.model]

    @property
    def k(self):
        return len(self.params)

    def predict(self, x):
        return _evaluate(self.model, self.params, np.asarray(x, dtype=float))

    def slope_at(self, x):
        """dy/dx at x (numerical), e.g. the local sensitivity at the mean level."""
        x = float(x)
        h = 1e-6 * max(1.0, abs(x))
        y = self.predict([x - h, x + h])
        return float((y[1] - y[0]) / (2 * h))

    def describe(self, digits=4):
        names = PARAM_NAMES[self.model]
        return ", ".join(f"{n}={v:.{digits}g}" for n, v in zip(names, self.params))


def _basis(model, x, s):
    """Columns of the linear part for shape parameter s (None for polynomials)."""
    one = np.ones_like(x)
    if model == "linear":
        return np.column_stack([x, one])
    if model == "quadratic":
        return np.column_stack([x, x**2, one])
    if model == "cubic":
        return np.column_stack([x, x**2, x**3, one])
    if model == "saturating":
        return np.column_stack([1 - np.exp(-x / s), one])
    if model == "power":
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.column_stack([np.power(x, s), one])
    if model == "mm":
        return np.column_stack([x / (s + x), one])
    raise ValueError(f"unknown fit '{model}'; choose from {', '.join(FIT_CHOICES)}")


def _evaluate(model, params, x):
    if model in ("linear", "quadratic", "cubic"):
        return _basis(model, x, None) @ np.asarray(params)
    lin = np.asarray(params)[[0, 2]]          # (A or a, c); params[1] is the shape
    return _basis(model, x, params[1]) @ lin


def _lstsq(model, x, y, s):
    B = _basis(model, x, s)
    if not np.all(np.isfinite(B)):
        return None, np.inf
    coef, *_ = np.linalg.lstsq(B, y, rcond=None)
    rss = float(((y - B @ coef) ** 2).sum())
    return coef, rss


def _shape_grid(model, x):
    span = float(np.ptp(x)) or 1.0
    if model == "power":
        return np.geomspace(0.1, 5, 200)
    # k or K from 1/50 to 50 times the x range
    return np.geomspace(span / 50, span * 50, 200)


def _fit_one(model, x, y):
    if model in ("linear", "quadratic", "cubic"):
        coef, rss = _lstsq(model, x, y, None)
        return tuple(float(v) for v in coef), rss
    if model in ("power", "mm") and np.any(x < 0):
        return None, np.inf
    grid = _shape_grid(model, x)
    best = (None, np.inf, None)
    for _ in range(3):                            # coarse grid, then two refinements
        for s in grid:
            coef, rss = _lstsq(model, x, y, s)
            if rss < best[1]:
                best = (coef, rss, s)
        if best[2] is None:
            return None, np.inf
        i = int(np.argmin(np.abs(grid - best[2])))
        lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
        grid = np.geomspace(lo, hi, 60)
    coef, rss, s = best
    return (float(coef[0]), float(s), float(coef[1])), rss


def fit_curve(x, y, model="linear"):
    """Least-squares fit of ``model`` (or the best by AICc for 'auto') -> Fit or None.

    None when there are too few finite points (fewer than the parameters, or
    an x range of zero). 'auto' only considers models with at least
    parameters + 2 points, so AICc is defined; with fewer points it fits a line.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    n = len(x)
    if n < 2 or np.ptp(x) == 0:
        return None
    if model == "auto":
        fits = [fit_curve(x, y, m) for m in AUTO_MODELS if n >= len(PARAM_NAMES[m]) + 2]
        fits = [f for f in fits if f is not None]
        # too few points to compare models: a line, as before
        return min(fits, key=lambda f: f.aicc) if fits else fit_curve(x, y, "linear")
    if model not in MODELS:
        raise ValueError(f"unknown fit '{model}'; choose from {', '.join(FIT_CHOICES)}")
    k = len(PARAM_NAMES[model])
    if n < k:
        return None
    params, rss = _fit_one(model, x, y)
    if params is None:
        return None
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - rss / ss_tot if ss_tot else 1.0
    rss_n = max(rss / n, 1e-300)
    aic = n * np.log(rss_n) + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else np.inf)
    return Fit(model, params, float(r2), float(np.sqrt(rss / n)), float(aicc), n)
