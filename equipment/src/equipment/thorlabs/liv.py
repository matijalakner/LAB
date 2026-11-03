import csv
import time
from contextlib import ExitStack
from pathlib import Path

from .common import (DC2200_PRODUCT_ID, PM_PRODUCT_ID, close_quietly, dc2200_resource,
                     pm_resource, sleep_until)
from .dc2200 import MAX_CURRENT_A
from .pm400 import PM400
from .usb_driver import ThorlabsUSBDriver

CSV_HEADER = ["time_s", "cycle", "direction", "current_A", "power_W"]


def _read_cfg(cfg):
    """Parses and validates configuration for the combined DC2200 + PM400 measurement."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k))

    defaults = {
        "i_min": 0.0,
        "i_max": 0.1,
        "ramp_duration": 10.0,
        "update_rate": 10.0,
        "cycles": 1,
        "wavelength": 450.0,
        "averaging_count": 10,
        "settle_time": None,   # s to wait after setting the current; None = auto
        "output_csv": None,    # path; None = do not write a file
        "dc2200_serial": None,
        "pm400_serial": None,
    }

    p = {}
    for k, default_val in defaults.items():
        try:
            val = get(k)
            p[k] = default_val if val is None else val
        except (KeyError, AttributeError):
            p[k] = default_val

    if p["i_min"] < 0 or p["i_max"] < 0:
        raise ValueError("currents must be >= 0 A")
    if p["i_max"] < p["i_min"]:
        raise ValueError("i_max must be >= i_min")
    if p["i_max"] > MAX_CURRENT_A:
        raise ValueError(f"i_max must be <= {MAX_CURRENT_A} A")
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


def _write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(rows)


def _run_ramp(dc2200, powermeter, p, cycle, direction, start, stop,
              t0, k, dt, n_steps, rows, skip_first):
    """One up or down ramp. k is the global point counter that schedules the clock."""
    for step in range(1 if skip_first else 0, n_steps + 1):
        current = start + (step / n_steps) * (stop - start)
        sleep_until(t0 + k * dt)
        dc2200.configure_constant_current(current)
        time.sleep(p["settle_time"])
        power_w = powermeter.read_power()
        rows.append((round(time.monotonic() - t0, 4), cycle, direction, current, power_w))
        print(f"Current: {current * 1e3:.2f} mA | Power: {power_w * 1e3:.4f} mW")
        k += 1
    return k


def main_liv_measurement(cfg):
    """Ramps the DC2200 current while logging power from the PM400.

    The DC2200 is controlled through `measurement_control`; the PM400 is read
    directly over SCPI with PyVISA (see PM400.py).

    Returns the list of rows (time_s, cycle, direction, current_A, power_W);
    if cfg.output_csv is set, the same rows are written there, also when the
    run is interrupted (partial data is kept).
    """
    p = _read_cfg(cfg)

    try:
        from measurement_control.communicators import USBCommunicator
        from measurement_control.instruments.thorlabs_dc2200 import DC2200
    except ImportError as e:
        raise RuntimeError(
            f"Could not import the DC2200 driver from 'measurement_control': {e}"
        ) from e

    n_steps = max(1, int(round(p["ramp_duration"] * p["update_rate"])))
    dt = p["ramp_duration"] / n_steps
    rows = []

    try:
        with ExitStack() as stack:
            stack.enter_context(ThorlabsUSBDriver(product_id=DC2200_PRODUCT_ID))
            stack.enter_context(ThorlabsUSBDriver(product_id=PM_PRODUCT_ID))
            print("Connecting to DC2200 and PM400 via PyVISA...")

            dc_comm = USBCommunicator(dc2200_resource(p["dc2200_serial"]))
            stack.callback(close_quietly, dc_comm)
            dc2200 = DC2200(dc_comm)

            powermeter = PM400(pm_resource(p["pm400_serial"]))
            stack.callback(powermeter.close)
            print("PM400 connected:", powermeter.idn())
            powermeter.set_wavelength(p["wavelength"])
            powermeter.set_averaging(p["averaging_count"])

            dc2200.set_user_current_limit(p["i_max"])
            dc2200.configure_constant_current(p["i_min"])
            stack.callback(dc2200.switch_off)   # runs before the communicators close
            dc2200.switch_on()
            print("LED Driver switched ON. Starting synchronized ramp & power log...")

            t0 = time.monotonic()
            k = 0
            for cycle in range(1, p["cycles"] + 1):
                print(f"--- Cycle {cycle}/{p['cycles']} (Ramping Up) ---")
                k = _run_ramp(dc2200, powermeter, p, cycle, "up", p["i_min"], p["i_max"],
                              t0, k, dt, n_steps, rows, skip_first=False)
                print(f"--- Cycle {cycle}/{p['cycles']} (Ramping Down) ---")
                # skip_first: the peak was already measured at the end of the up-ramp
                k = _run_ramp(dc2200, powermeter, p, cycle, "down", p["i_max"], p["i_min"],
                              t0, k, dt, n_steps, rows, skip_first=True)
    finally:
        if p["output_csv"] and rows:
            _write_csv(p["output_csv"], rows)
            print(f"Data saved to {p['output_csv']}")
        print("LED output switched off. Measurement ended.")
    return rows
