"""Line the photo results up with a light-source ramp and plot them.

Inputs
    results CSV   written by ``analysis folder``
    ramp CSV      written by ``equipment dc2200 ramp`` / ``equipment pe300 ramp``
                  (level column current_A or intensity_pct)
    <ramp>_photos.csv  (ramp with --photos) the level, step and direction of
                  every photo, recorded when it was taken
    <ramp>_power.csv   (ramp with --power) the PM400 reading of every step
    LIV CSV       (optional) power against level, for runs without --power

How each photo gets its level, in this order:
  1. "photo log": the photo's row in <ramp>_photos.csv. No clock is involved.
  2. "time": the photo time from results.csv against the ramp's time stamp
     (latest step at or before the photo). Only photos taken during the ramp
     are kept. For photos from another camera or an older run.

Power per photo, in this order: the PM400 reading of the photo's step
(<ramp>_power.csv), the LIV curve interpolated at the photo's level, or for a
pE-300 ramp the calibrated power ``intensity * PE300_W_PER_PCT[color]``, or for
a DC2200 ramp the calibrated power ``dc2200_power_w(current)``. A DC2200 ramp
also gets the intensity [mW/cm^2] of its calibration, and with an objective the
calibrated intensity ``current * COEFF[objective]`` [W/um^2].
"""
from pathlib import Path

from .paths import input_root, output_root
import numpy as np
import pandas as pd

from .calibration import (COEFF, DC2200_CALIBRATION, OBJECTIVES, PE300_W_PER_PCT, PX_TO_UM,
                          THETA, dc2200_intensity_mw_cm2, dc2200_power_w)
from .fits import FIT_CHOICES, fit_curve, outlier_mask
from .calibration import px_to_um as calibrated_px_to_um
from .logs import LEVELS, companion, level_column, ramp_files, read_log, read_ramp

BASE_COLUMNS = ["time[s]", "step", "cycle", "direction"]
RESULT_COLUMNS = ["mean_spacing_px", "std_spacing_px", "warning", "n_lines", "file"]
OPTIONAL_COLUMNS = ["spacing_err_px", "quality"]     # from analysis jumps


# ---------------------------------------------------------------------------
# finding the files
# ---------------------------------------------------------------------------
def find_results_csv(results, output_dir=None):
    """A results CSV, or the name of a photo folder analysed with 'analysis folder'."""
    output_dir = output_root(output_dir)
    p = Path(results)
    if p.is_file():
        return p
    q = Path(output_dir) / "folder" / Path(results).name / "results.csv"
    if q.exists():
        return q
    raise FileNotFoundError(f"No results found for '{results}' (tried {p} and {q}). "
                            "Run 'analysis folder' first.")


def _photo_log_files(ramp_csv):
    p = companion(ramp_csv, "photos")
    if not p.exists():
        return set()
    try:
        return set(read_log(p)[1]["file"].astype(str))
    except (KeyError, ValueError, pd.errors.ParserError):
        return set()


def find_ramp_csv(ramp=None, output_dir=None, files=()):
    """The ramp CSV to use.

    Given: that file (or that name in <output_dir>/ramp/). Not given: the ramp
    whose photo log lists most of ``files`` (the photos of the folder), else the
    newest ramp.
    """
    output_dir = output_root(output_dir)
    if ramp:
        p = Path(ramp)
        if not p.exists():
            p = Path(output_dir) / "ramp" / p.name
        if not p.exists():
            raise FileNotFoundError(f"Ramp file not found: {ramp}")
        return p
    ramps = ramp_files(output_dir)
    if not ramps:
        raise FileNotFoundError(f"No ramp CSV in {Path(output_dir) / 'ramp'}. "
                                "Run 'equipment ... ramp' first or pass --ramp.")
    files = set(files)
    best = max(ramps, key=lambda r: (len(files & _photo_log_files(r)), ramps.index(r)))
    return best


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------
def _by_photo_log(photos, ramp_csv, col):
    log_path = companion(ramp_csv, "photos")
    if not log_path.exists():
        return None
    _, log = read_log(log_path)
    if level_column(log, log_path) != col:
        raise ValueError(f"{log_path} and {ramp_csv} have different level columns")
    log = log.rename(columns={"time_s": "time[s]"})
    log["file"] = log["file"].astype(str)
    log = log.drop_duplicates("file", keep="last")
    table = photos.merge(log[["file", "time[s]", "step", "cycle", "direction", col]],
                         on="file", how="inner")
    return table if not table.empty else None


def _by_time(photos, t0, ramp, col, camera_offset_s):
    utc = pd.to_datetime(photos["time_stamp"], utc=True) \
        + pd.to_timedelta(camera_offset_s, unit="s")
    photos = photos.assign(**{"time[s]": (utc - t0).dt.total_seconds()})
    photos = photos.sort_values("time[s]")
    steps = ramp[["time_s", "step", "cycle", "direction", col]].rename(
        columns={"time_s": "time[s]"}).sort_values("time[s]")
    table = pd.merge_asof(photos, steps, on="time[s]", direction="backward")
    end = ramp["time_s"].max() + (np.diff(ramp["time_s"]).mean() if len(ramp) > 1 else 0)
    return table[(table["time[s]"] >= 0) & (table["time[s]"] <= end)]


def _power_by_step(ramp_csv):
    p = companion(ramp_csv, "power")
    if not p.exists():
        return None
    _, df = read_log(p)
    if not {"step", "power_W"} <= set(df.columns):
        return None
    return df.groupby("step")["power_W"].mean()


def liv_curve(path):
    """(level column, levels, mean power) of an LIV CSV, sorted by level."""
    _, df = read_log(path)
    col = level_column(df, path)
    if "power_W" not in df.columns:
        raise ValueError(f"{path}: missing column power_W")
    g = df.groupby(col)["power_W"].mean().sort_index()
    return col, g.index.to_numpy(dtype=float), g.to_numpy(dtype=float)


def acquire(ramp_csv, results_csv, camera_offset_s=0.0, liv=None, objective=None,
            color=None):
    """One row per photo with its ramp level (and power when known).

    Columns: time[s] (since the ramp start), step, cycle, direction, the level
    (current[A] or intensity[%]), power[W] and/or intensity[W/um2] when known,
    then mean_spacing_px, std_spacing_px, warning, n_lines, file.
    Returns (table, info) with info: level, level_label, unit, matched_by,
    power_source.
    """
    t0, ramp, col = read_ramp(ramp_csv)
    photos = pd.read_csv(results_csv)
    photos["file"] = photos["file"].astype(str)
    photos["warning"] = photos["warning"].fillna("") if "warning" in photos else ""

    table, matched_by = _by_photo_log(photos, ramp_csv, col), "photo log"
    if table is None:
        table, matched_by = _by_time(photos, t0, ramp, col, camera_offset_s), "time"
    table = table.sort_values("time[s]").reset_index(drop=True)
    quantity, unit, label = LEVELS[col]
    table = table.rename(columns={col: label})
    level = table[label].to_numpy(dtype=float)

    power_source = None
    by_step = _power_by_step(ramp_csv)
    if by_step is not None:
        table["power[W]"] = table["step"].map(by_step)
        power_source = "PM400 during the ramp"
    elif liv:
        liv_col, x, y = liv_curve(liv)
        if liv_col != col:
            raise ValueError(f"the LIV file has {liv_col}, the ramp has {col}")
        table["power[W]"] = np.interp(level, x, y, left=np.nan, right=np.nan)
        power_source = f"LIV curve {Path(liv).name}"
    elif col == "intensity_pct" and color:
        if color not in PE300_W_PER_PCT:
            raise ValueError(f"unknown colour '{color}'; choose from {sorted(PE300_W_PER_PCT)}")
        table["power[W]"] = level * PE300_W_PER_PCT[color]
        power_source = f"pE-300 {color} calibration ({PE300_W_PER_PCT[color]:.4g} W/%)"
    elif col == "current_A":
        table["power[W]"] = dc2200_power_w(level)
        power_source = "DC2200 calibration"
    if col == "current_A":
        table["intensity[mW/cm2]"] = dc2200_intensity_mw_cm2(level)
        lo, hi = DC2200_CALIBRATION[0][0], DC2200_CALIBRATION[-1][0]
        out = level[np.isfinite(level) & ((level < lo) | (level > hi))]
        if len(out):
            print(f"  note: {len(out)} photos at currents outside the DC2200 calibration "
                  f"({lo * 1e3:.0f}-{hi * 1e3:.0f} mA); their power and intensity are "
                  f"extrapolated")
    if col == "current_A" and objective:
        if objective not in OBJECTIVES:
            raise ValueError(f"unknown objective '{objective}'; choose from {OBJECTIVES}")
        if objective in COEFF:
            table["intensity[W/um2]"] = level * COEFF[objective]
        else:
            print(f"  note: no DC2200 intensity calibration for {objective} "
                  f"(calibration.COEFF has {', '.join(sorted(COEFF))}); intensity axis left out")

    extra = [c for c in ("power[W]", "intensity[mW/cm2]", "intensity[W/um2]") if c in table]
    optional = [c for c in OPTIONAL_COLUMNS if c in table]
    table = table[BASE_COLUMNS + [label] + extra + RESULT_COLUMNS + optional]
    info = {"level": col, "level_label": label, "quantity": quantity, "unit": unit,
            "matched_by": matched_by, "power_source": power_source,
            "t0": t0, "ramp": ramp}
    return table, info


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------
def _x_axes(table, info, objective):
    axes = [(info["level_label"], f"{info['quantity']} [{info['unit']}]")]
    if "power[W]" in table and table["power[W]"].notna().any():
        axes.append(("power[mW]", "optical power [mW]"))
    if "intensity[mW/cm2]" in table:
        axes.append(("intensity[mW/cm2]", "intensity [mW/cm²]"))
    elif "power[W]" in table and table["power[W]"].notna().any():
        pass
    elif "intensity[W/um2]" in table:
        axes.append(("intensity[W/um2]", f"intensity [W/µm²] ({objective})"))
    axes.append(("time[s]", "time since the ramp start [s]"))
    return axes


def linear_fit(x, y):
    """Least-squares line y = slope * x + intercept -> (slope, intercept, r2, n) or None."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if len(x) < 2 or np.ptp(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(((y - slope * x - intercept) ** 2).sum()) / ss_tot if ss_tot else 1.0
    return float(slope), float(intercept), r2, int(len(x))


FITS_COLUMNS = ["y", "x", "direction", "model", "formula", "params", "slope", "intercept",
                "slope_at_mean_x", "r2", "rmse", "aicc", "n", "n_excluded"]


def _fit_label(direction, fit):
    if fit.model == "linear":
        return f"{direction}: slope {fit.params[0]:.4g}, R² {fit.r2:.3f}"
    return f"{direction}: {fit.model} ({fit.describe(3)}), R² {fit.r2:.3f}"


def plot_report(table, info, out_png, name="", objective="20x", theta="0.8wt",
                px_to_um=PX_TO_UM, fits_csv=None, fit="auto", reject_outliers=True):
    """Average distance and pitch against the level, power and time.

    Up and down branches of the ramp are drawn separately (hysteresis shows),
    each with its fit on the level and power axes (not against time). ``fit``
    is one of fits.FIT_CHOICES: a model ('linear', 'quadratic', 'cubic',
    'saturating', 'power', 'mm'), 'auto' (the best by AICc for each branch and
    axis) or 'none'. The fits are written to ``fits_csv`` if given. Photos with
    a warning are left out. Returns the number of photos plotted.

    With ``reject_outliers`` the photos far from the trend of their branch
    (fits.outlier_mask on distance against the level, e.g. a photo where every
    second line was missed) are left out of the fits and drawn hollow.
    """
    from .style import DIRECTION_STYLE, MUTED, figure, finish

    if fit not in FIT_CHOICES:
        raise ValueError(f"unknown fit '{fit}'; choose from {', '.join(FIT_CHOICES)}")
    if theta not in THETA:
        raise ValueError(f"unknown sample '{theta}'; choose from {sorted(THETA)}")
    ok = table[(table["warning"] == "") & table["mean_spacing_px"].notna()].copy()
    if ok.empty:
        raise ValueError("every photo has a warning; nothing to plot.")
    ok["distance"] = ok["mean_spacing_px"].astype(float) * px_to_um
    ok["pitch"] = 2 * THETA[theta] * ok["distance"]
    has_err = "spacing_err_px" in ok and pd.to_numeric(ok["spacing_err_px"],
                                                         errors="coerce").notna().any()
    if has_err:
        err = pd.to_numeric(ok["spacing_err_px"], errors="coerce") * px_to_um
        ok["distance_err"] = err
        ok["pitch_err"] = 2 * THETA[theta] * err
    if "power[W]" in ok:
        ok["power[mW]"] = ok["power[W]"] * 1e3

    xs = _x_axes(table, info, objective)
    ok["excluded"] = False
    if reject_outliers and fit != "none":
        for _, part in ok.groupby("direction", sort=False):
            ok.loc[part.index, "excluded"] = outlier_mask(part[xs[0][0]], part["distance"], fit)
    fits = []
    ys = [("distance", "average distance [µm]"), ("pitch", f"pitch [µm] ({theta})")]
    fig, axes = figure(2, len(xs), figsize=(5 * len(xs), 8), sharey="row", squeeze=False)
    for r, (ycol, ylabel) in enumerate(ys):
        for c, (xcol, xlabel) in enumerate(xs):
            ax = axes[r, c]
            fit_handles = []
            for direction, part in ok.groupby("direction", sort=False):
                color, marker = DIRECTION_STYLE.get(direction, (MUTED, "s"))
                inl, exc = part[~part["excluded"]], part[part["excluded"]]
                ax.scatter(inl[xcol], inl[ycol], s=30, color=color, marker=marker,
                           edgecolors="white", linewidths=1, label=f"ramp {direction}",
                           zorder=3)
                if has_err:
                    ax.errorbar(inl[xcol], inl[ycol], yerr=inl[f"{ycol}_err"].fillna(0),
                                fmt="none", ecolor=color, elinewidth=1, alpha=0.6, zorder=2)
                if len(exc):
                    ax.scatter(exc[xcol], exc[ycol], s=30, facecolors="none",
                               edgecolors=color, marker=marker, linewidths=1,
                               label=f"{direction}: left out of the fit", zorder=3)
                if xcol == "time[s]" or fit == "none":
                    continue
                f = fit_curve(inl[xcol], inl[ycol], fit,
                              inl[f"{ycol}_err"] if has_err else None)
                if f is None:
                    continue
                xmean = float(np.nanmean(inl[xcol]))
                fits.append({"y": ycol, "x": xcol, "direction": direction,
                             "model": f.model, "formula": f.formula, "params": f.describe(8),
                             "slope": f.params[0] if f.model == "linear" else np.nan,
                             "intercept": f.params[1] if f.model == "linear" else np.nan,
                             "slope_at_mean_x": f.slope_at(xmean), "r2": f.r2,
                             "rmse": f.rmse, "aicc": f.aicc, "n": f.n,
                             "n_excluded": int(len(exc))})
                xx = np.linspace(np.nanmin(inl[xcol]), np.nanmax(inl[xcol]), 200)
                line, = ax.plot(xx, f.predict(xx), color=color, lw=1.5, zorder=2,
                                label=_fit_label(direction, f))
                fit_handles.append(line)
            ax.set_xlabel(xlabel)
            if c == 0:
                ax.set_ylabel(ylabel)
            ax.tick_params(labelleft=True)
            if fit_handles:
                ax.legend(handles=fit_handles, loc="lower right", fontsize=8)
    fit_legend = axes[0, 0].get_legend()
    axes[0, 0].legend(handles=list(axes[0, 0].collections), loc="upper left")
    if fit_legend is not None:
        axes[0, 0].add_artist(fit_legend)
    if fits_csv:
        pd.DataFrame(fits, columns=FITS_COLUMNS).to_csv(fits_csv, index=False)
    note = f"level by {info['matched_by']}"
    if info["power_source"]:
        note += f", power from {info['power_source']}"
    fig.suptitle(f"{name}: average distance and pitch  ({note})", x=0.01, ha="left")
    fig.tight_layout()
    finish(fig, out_png)
    return len(ok)


def plot_timeline(table, info, out_png, name="", theta="0.8wt", px_to_um=PX_TO_UM):
    """Light level (and power) of the ramp above the pitch of the photos, one time axis.

    t = 0 is the ramp start for every panel: the photo log and the ramp share
    their clock, so nothing is shifted or stretched.
    """
    from .style import BLUE, ORANGE, TEXT_2, figure, finish

    ramp = info["ramp"]
    ok = table[(table["warning"] == "") & table["mean_spacing_px"].notna()]
    has_power = "power[W]" in table and table["power[W]"].notna().any()
    n = 3 if has_power else 2
    fig, axes = figure(n, 1, figsize=(11, 2.6 * n + 1), sharex=True)
    t = np.append(ramp["time_s"].to_numpy(dtype=float),
                  ramp["time_s"].iloc[-1] + (np.diff(ramp["time_s"]).mean()
                                             if len(ramp) > 1 else 0))
    level = ramp[info["level"]].to_numpy(dtype=float)
    axes[0].step(t, np.append(level, level[-1]), where="post", color=ORANGE, lw=2)
    axes[0].set_ylabel(f"{info['quantity']} [{info['unit']}]")
    if has_power:
        pw = table.dropna(subset=["power[W]"])
        axes[1].plot(pw["time[s]"], pw["power[W]"] * 1e3, "o", ms=5, color=ORANGE,
                     mec="white", mew=1)
        axes[1].set_ylabel("optical power [mW]")
    pitch = 2 * THETA[theta] * ok["mean_spacing_px"].astype(float) * px_to_um
    axes[-1].plot(ok["time[s]"], pitch, "o", ms=5, color=BLUE, mec="white", mew=1)
    axes[-1].set_ylabel(f"pitch [µm] ({theta})")
    axes[-1].set_xlabel(f"time since the ramp start [s]  (t = 0 at {info['t0']:%Y-%m-%d %H:%M:%S} UTC)")
    axes[-1].set_xlim(0, t[-1])
    fig.suptitle(f"{name}: light and pitch against time", x=0.01, ha="left",
                 color=TEXT_2)
    fig.tight_layout()
    finish(fig, out_png)


def detect_camera(photo_dir, files):
    """'flir' or 'canon' from the EXIF Make of the first readable photo, else None."""
    from PIL import Image
    for f in list(files)[:5]:
        path = Path(photo_dir) / f
        try:
            with Image.open(path) as im:
                make = str(im.getexif().get(0x010F, "")).lower()
        except Exception:
            continue
        if "flir" in make or "teledyne" in make:
            return "flir"
        if "canon" in make:
            return "canon"
    return None


def choose_px_to_um(px_to_um=None, camera=None, objective=None, photo_dir=None, files=()):
    """Micrometers per pixel -> (value, how it was found).

    An explicit px_to_um wins; else the calibration table for the camera (given,
    or read from the photos' EXIF) and the objective (default 20x).
    """
    if px_to_um is not None:
        return float(px_to_um), "given with --px-um"
    if camera in (None, "auto"):
        camera = detect_camera(photo_dir, files) if photo_dir else None
        found = "camera from the photos"
    else:
        found = "camera given"
    if camera is None:
        return PX_TO_UM, ("camera unknown, old default (Canon, 20x); pass --camera and "
                          "--objective, or --px-um")
    value, how = calibrated_px_to_um(camera, objective or "20x")
    if objective is None:
        how += "; objective not given, 20x assumed (pass --objective)"
    return value, f"{how}; {found}"


def main_report(name, ramp=None, results=None, output_dir=None, objective=None,
                theta="0.8wt", px_to_um=None, camera_offset_s=0.0, liv=None,
                color=None, camera="auto", input_dir=None, fit="auto",
                reject_outliers=True):
    """Align, save and plot -> <output_dir>/report/<name>/data.csv, plots.png, timeline.png.

    ``results`` defaults to ``name`` (the folder name used with 'analysis folder').
    Micrometers per pixel: ``px_to_um`` if given, else from the calibration table
    for ``camera`` ('flir', 'canon', or 'auto' = from the photos' EXIF) and
    ``objective`` (calibration.px_to_um). ``fit``: the function drawn through
    each branch (see plot_report).
    """
    output_dir = output_root(output_dir)
    results_path = find_results_csv(results or name, output_dir)
    files = pd.read_csv(results_path)["file"].astype(str)
    photo_dir = input_root(input_dir) / "folder" / Path(name).name
    px_to_um, px_source = choose_px_to_um(px_to_um, camera, objective, photo_dir, files)
    objective = objective or "20x"
    ramp_path = find_ramp_csv(ramp, output_dir, files)
    table, info = acquire(ramp_path, results_path, camera_offset_s, liv, objective,
                          color)
    if table.empty:
        raise ValueError(f"No photo of '{name}' belongs to {ramp_path.name}: it is not in "
                         "the ramp's photo log and was not taken while the ramp ran. Pass "
                         "--ramp, or check the camera clock (--camera-offset).")
    out_dir = Path(output_dir) / "report" / Path(name).name
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "data.csv"
    table.to_csv(csv_path, index=False)
    plot_path, timeline_path = out_dir / "plots.png", out_dir / "timeline.png"
    fits_path = out_dir / "fits.csv"
    plotted = plot_report(table, info, plot_path, name, objective, theta, px_to_um,
                          fits_csv=fits_path, fit=fit, reject_outliers=reject_outliers)
    plot_timeline(table, info, timeline_path, name, theta, px_to_um)
    return {"table": table, "ramp_path": str(ramp_path), "results_path": str(results_path),
            "csv_path": str(csv_path), "plot_path": str(plot_path),
            "timeline_path": str(timeline_path), "fits_path": str(fits_path),
            "photos": len(table), "plotted": plotted,
            "matched_by": info["matched_by"], "power_source": info["power_source"],
            "level": info["level"], "px_um": px_to_um, "px_source": px_source,
            "fit": fit}
