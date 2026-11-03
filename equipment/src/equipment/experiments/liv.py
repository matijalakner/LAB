"""Light-power curve: ramp any light source linearly up and down while the
PM400 reads the power at every point.

    equipment liv --source dc2200 --max 0.05            (A)
    equipment liv --source pe300 --max 100 --channels B (%)

CSV (no time stamp line, as before):
    time_s, cycle, direction, <source column>, power_W
"""
import csv
import time
from contextlib import ExitStack
from pathlib import Path

from ..sources import make_source, source_class
from ..thorlabs.pm400 import open_pm400
from ..utils import read_cfg, sleep_until

# default (min, max) per source when not given
DEFAULT_RANGE = {"dc2200": (0.0, 0.1), "pe300": (0, 100)}


def _read_cfg(cfg):
    get = read_cfg(cfg)
    key = get("source") or "dc2200"
    cls = source_class(key)
    lo, hi = DEFAULT_RANGE.get(key, (0, cls.max_level))
    defaults = {"i_min": lo, "i_max": hi, "ramp_duration": 10.0, "update_rate": 10.0,
                "cycles": 1, "wavelength": 450.0, "averaging_count": 10,
                "settle_time": None, "output_csv": None, "pm400_serial": None}
    p = {k: (d if get(k) is None else get(k)) for k, d in defaults.items()}
    if get("min") is not None:
        p["i_min"] = get("min")
    if get("max") is not None:
        p["i_max"] = get("max")
    p["source"] = key

    if p["i_min"] < 0 or p["i_max"] < 0:
        raise ValueError("levels must be >= 0")
    if p["i_max"] < p["i_min"]:
        raise ValueError("max must be >= min")
    if p["i_max"] > cls.max_level:
        raise ValueError(f"max must be <= {cls.max_level:g} {cls.unit} for the {cls.name}")
    if p["ramp_duration"] <= 0 or p["update_rate"] <= 0:
        raise ValueError("ramp_duration and update_rate must be > 0")
    if p["cycles"] < 1:
        raise ValueError("cycles must be >= 1")
    if p["wavelength"] <= 0:
        raise ValueError("wavelength must be > 0 nm")
    if p["averaging_count"] < 1:
        raise ValueError("averaging_count must be >= 1")
    period = 1.0 / p["update_rate"]
    if p["settle_time"] is None:
        p["settle_time"] = min(0.02, period / 2)
    if not 0 <= p["settle_time"] < period:
        raise ValueError("settle_time must be >= 0 and shorter than 1/update_rate")
    return p


def _write_csv(path, header, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _run_ramp(light, meter, p, cycle, direction, start, stop, t0, k, dt, n_steps, rows,
              skip_first):
    """One up or down ramp. k is the global point counter that schedules the clock."""
    for step in range(1 if skip_first else 0, n_steps + 1):
        level = light.quantize(start + (step / n_steps) * (stop - start))
        sleep_until(t0 + k * dt)
        light.set_level(level)
        time.sleep(p["settle_time"])
        power_w = meter.read_power()
        rows.append((round(time.monotonic() - t0, 4), cycle, direction, level, power_w))
        print(f"{light.fmt(level)} | Power: {power_w * 1e3:.4f} mW")
        k += 1
    return k


def main_liv_measurement(cfg):
    """Ramp a light source and log the PM400 power at every point.

    cfg: source ('dc2200' default, or 'pe300'), i_min/i_max (or min/max) in the
    source's unit, ramp_duration (s, one way), update_rate (Hz), cycles,
    wavelength (nm), averaging_count, settle_time, output_csv, pm400_serial;
    the source settings (dc2200_serial; port, channels).
    Returns rows (time_s, cycle, direction, level, power_W); written to
    output_csv also when the run is interrupted.
    """
    p = _read_cfg(cfg)
    n_steps = max(1, int(round(p["ramp_duration"] * p["update_rate"])))
    dt = p["ramp_duration"] / n_steps
    rows = []
    light = make_source(p["source"], cfg)
    header = ["time_s", "cycle", "direction", light.column, "power_W"]
    try:
        with ExitStack() as stack:
            meter = stack.enter_context(open_pm400(p["pm400_serial"], p["wavelength"],
                                                   p["averaging_count"]))
            stack.enter_context(light)           # switched off before the meter closes
            light.prepare(limit=p["i_max"])
            light.set_level(light.quantize(p["i_min"]))
            light.switch_on()
            print(f"{light.name} ON. Starting synchronized ramp & power log...")
            t0, k = time.monotonic(), 0
            for cycle in range(1, p["cycles"] + 1):
                print(f"--- Cycle {cycle}/{p['cycles']} (up) ---")
                k = _run_ramp(light, meter, p, cycle, "up", p["i_min"], p["i_max"],
                              t0, k, dt, n_steps, rows, skip_first=False)
                print(f"--- Cycle {cycle}/{p['cycles']} (down) ---")
                k = _run_ramp(light, meter, p, cycle, "down", p["i_max"], p["i_min"],
                              t0, k, dt, n_steps, rows, skip_first=True)
    finally:
        if p["output_csv"] and rows:
            _write_csv(p["output_csv"], header, rows)
            print(f"Data saved to {p['output_csv']}")
        print("Light switched off. Measurement ended.")
    return rows
