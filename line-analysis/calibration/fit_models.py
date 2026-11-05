"""Try several functions for pE-300 power vs intensity and compare them.

Run: python fit_models.py  (defaults to the two pE-300 ramps in this folder)
Writes fit_comparison.csv and fit_comparison.png next to this script.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

HERE = Path(__file__).parent


def read(path):
    df = pd.read_csv(path, skiprows=1)
    df["P_mW"] = df["power_W"] * 1e3
    return df


# name -> (function, initial guess builder, number of parameters, formula)
def piecewise(x, x0, a1, a2, c):
    return np.where(x < x0, c + a1 * x, c + a1 * x0 + a2 * (x - x0))


MODELS = {
    "linear (through 0)": (lambda x, a: a * x,
                           lambda x, y: [y.max() / x.max()], "a·x"),
    "linear": (lambda x, a, c: a * x + c,
               lambda x, y: [y.max() / x.max(), 0], "a·x + c"),
    "quadratic": (lambda x, a, b, c: a * x + b * x**2 + c,
                  lambda x, y: [y.max() / x.max(), 0, 0], "a·x + b·x² + c"),
    "cubic": (lambda x, a, b, d, c: a * x + b * x**2 + d * x**3 + c,
              lambda x, y: [y.max() / x.max(), 0, 0, 0], "a·x + b·x² + d·x³ + c"),
    "power law": (lambda x, a, n, c: a * np.power(x, n) + c,
                  lambda x, y: [y.max() / x.max(), 1.0, 0], "a·xⁿ + c"),
    "saturating exp": (lambda x, A, k, c: A * (1 - np.exp(-x / k)) + c,
                       lambda x, y: [2 * y.max(), 2 * x.max(), 0], "A·(1 − e^(−x/k)) + c"),
    "Michaelis–Menten": (lambda x, A, K, c: A * x / (K + x) + c,
                         lambda x, y: [2 * y.max(), x.max(), 0], "A·x/(K + x) + c"),
    "two-segment linear": (piecewise,
                           lambda x, y: [10, 1.5 * y.max() / x.max(), y.max() / x.max(), 0],
                           "kink at x₀"),
}


def fit_all(x, y):
    rows, curves = [], {}
    n = len(x)
    for name, (f, guess, formula) in MODELS.items():
        try:
            p, _ = curve_fit(f, x, y, p0=guess(x, y), maxfev=50000)
        except RuntimeError:
            continue
        res = y - f(x, *p)
        k = len(p)
        rss = float((res**2).sum())
        r2 = 1 - rss / float(((y - y.mean()) ** 2).sum())
        aic = n * np.log(rss / n) + 2 * k
        bic = n * np.log(rss / n) + k * np.log(n)
        hi = x >= 10
        rel = np.abs(res[hi] / y[hi]).max() * 100
        rows.append({"model": name, "formula": formula, "k": k,
                     "params": ", ".join(f"{v:.5g}" for v in p),
                     "rmse_uW": np.sqrt(rss / n) * 1e3, "r2": r2,
                     "max_rel_err_%_(x>=10)": rel, "AIC": aic, "BIC": bic})
        curves[name] = (f, p)
    t = pd.DataFrame(rows)
    t["dAIC"] = t["AIC"] - t["AIC"].min()
    return t.sort_values("AIC").reset_index(drop=True), curves


def main(paths):
    tables = []
    show = ["linear", "quadratic", "power law", "saturating exp", "two-segment linear"]
    fig, axes = plt.subplots(2, len(paths), figsize=(6.5 * len(paths), 8),
                             sharex=True, gridspec_kw={"height_ratios": [3, 2]},
                             squeeze=False)
    for j, path in enumerate(paths):
        color = Path(path).stem.split("_")[1] if Path(path).stem.startswith("pe300_") else Path(path).stem
        df = read(path)
        for branch, part in [("up", df[df.direction == "up"]),
                             ("down", df[df.direction == "down"]),
                             ("both", df)]:
            t, curves = fit_all(part["intensity_pct"].to_numpy(float),
                                part["P_mW"].to_numpy(float))
            t.insert(0, "branch", branch)
            t.insert(0, "colour", color)
            tables.append(t)
            if branch != "up":
                continue
            x, y = part["intensity_pct"].to_numpy(float), part["P_mW"].to_numpy(float)
            ax, axr = axes[0, j], axes[1, j]
            ax.plot(x, y, "o", ms=4, color="0.4", label="up branch data")
            xx = np.linspace(0, 100, 400)
            for name in show:
                f, p = curves[name]
                ax.plot(xx, f(xx, *p), lw=1.4, label=name)
                axr.plot(x, (y - f(x, *p)) * 1e3, ".-", lw=0.8, ms=4, label=name)
            ax.set_title(f"{color}: power vs intensity (up branch)")
            ax.set_ylabel("power [mW]")
            ax.legend(fontsize=8)
            axr.axhline(0, color="k", lw=0.6)
            axr.set_ylabel("residual [µW]")
            axr.set_xlabel("pE-300 intensity [%]")
    fig.tight_layout()
    fig.savefig(HERE / "fit_comparison.png", dpi=130)
    out = pd.concat(tables, ignore_index=True)
    out.to_csv(HERE / "fit_comparison.csv", index=False)
    return out


if __name__ == "__main__":
    out = main(sys.argv[1:] or [HERE / "pe300_blue_0_100.csv", HERE / "pe300_green_0_100.csv"])
    pd.set_option("display.width", 220, "display.max_columns", 20)
    for (c, b), t in out.groupby(["colour", "branch"], sort=False):
        print(f"\n== {c} / {b} ==")
        print(t[["model", "k", "params", "rmse_uW", "r2", "max_rel_err_%_(x>=10)", "dAIC"]]
              .to_string(index=False, float_format=lambda v: f"{v:.4g}"))
