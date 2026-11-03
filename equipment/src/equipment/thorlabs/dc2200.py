import math
import time

from ..utils import utc_timestamp, write_csv
from .common import DC2200_PRODUCT_ID, close_quietly, dc2200_resource, sleep_until
from .usb_driver import ThorlabsUSBDriver

# Currents are in AMPERES (the DC2200 accepts up to 2 A; check your LED head's rating).
MAX_CURRENT_A = 2.0
MAX_STEPS = 100_000
RAMP_CSV_HEADER = ["time_s", "cycle", "direction", "current_A"]


def ramp_levels(i_min, i_max, step):
    """Currents (A) of one upward ramp: i_min, i_min + step, ... , i_max.

    The last level is always exactly i_max; if (i_max - i_min) is not a
    multiple of step, the last step is simply shorter.
    """
    if step <= 0:
        raise ValueError("step must be > 0 A")
    if i_max < i_min:
        raise ValueError("max must be >= min")
    n = int(math.floor((i_max - i_min) / step + 1e-9))
    if n + 1 > MAX_STEPS:
        raise ValueError(f"too many steps ({n + 1}); use a larger step")
    levels = [round(min(i_min + i * step, i_max), 9) for i in range(n + 1)]
    if levels[-1] < i_max - 1e-9:
        levels.append(round(i_max, 9))
    return levels


def ramp_sequence(levels, cycles=1):
    """Ordered (cycle, direction, current) list: up to the maximum, then back down.

    The maximum is not repeated. Cycle 2 and later skip their first up level,
    because the previous cycle already ended on it.
    """
    seq = []
    for cycle in range(1, cycles + 1):
        up = levels if cycle == 1 else levels[1:]
        seq += [(cycle, "up", i) for i in up]
        seq += [(cycle, "down", i) for i in levels[-2::-1]]
    return seq


def _read_cfg(cfg):
    """Accepts a dict or an object (e.g. SimpleNamespace) with the ramp settings."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k, None))

    def value(key, default=None):
        v = get(key)
        if v is None:
            if default is None:
                raise ValueError(f"ramp setting '{key}' is missing")
            return default
        return v

    p = {"i_min": float(value("i_min")), "i_max": float(value("i_max")),
         "step": float(value("step")), "step_time": float(value("step_time")),
         "cycles": int(value("cycles", 1)), "output_csv": get("output_csv"),
         "resource": dc2200_resource(get("dc2200_serial"))}
    if p["i_min"] < 0:
        raise ValueError("min must be >= 0 A")
    if p["i_max"] < p["i_min"]:
        raise ValueError("max must be >= min")
    if p["i_max"] > MAX_CURRENT_A:
        raise ValueError(f"max must be <= {MAX_CURRENT_A} A")
    if p["step"] <= 0 or p["step_time"] <= 0:
        raise ValueError("step and step_time must be > 0")
    if p["cycles"] < 1:
        raise ValueError("cycles must be >= 1")
    return p


def _import_dc2200():
    """Imported lazily so the rest of the package works without the instrument library."""
    try:
        from measurement_control.communicators import USBCommunicator
        from measurement_control.instruments.thorlabs_dc2200 import DC2200
    except ImportError as e:
        raise RuntimeError(
            "The 'measurement_control' package is required to control the DC2200."
        ) from e
    return USBCommunicator, DC2200


def main_ramp(cfg, on_start=None, on_step=None):
    """Stepped current ramp for the ThorLabs DC2200: min -> max -> min.

    cfg needs: i_min, i_max (A), step (A), step_time (s, how long every step is
    held); optional: cycles (default 1), output_csv (path), dc2200_serial.

    Optional hooks (used by the camera, see experiments/ramp_camera.py):
    ``on_start(t0, time_stamp, sequence)`` right before the first step, with
    t0 the time.monotonic() of the ramp start; ``on_step(k, cycle, direction,
    current)`` right after every current change. An exception raised in a hook
    stops the ramp (and switches the LED off).

    Returns the list of rows (time_s, cycle, direction, current_A). If output_csv
    is set the rows are written there, also when the run is interrupted. The
    first line of that file is ``time_stamp,<UTC time at the start of the ramp>``.
    The LED is switched off at the end and on any error, including Ctrl+C.
    """
    p = _read_cfg(cfg)
    sequence = ramp_sequence(ramp_levels(p["i_min"], p["i_max"], p["step"]), p["cycles"])
    USBCommunicator, DC2200 = _import_dc2200()

    rows, time_stamp = [], None
    try:
        with ThorlabsUSBDriver(product_id=DC2200_PRODUCT_ID):
            print("Kernel USB driver detached. Connecting to DC2200 via PyVISA...")
            communicator = USBCommunicator(p["resource"])
            try:
                dc2200 = DC2200(communicator)
                try:
                    dc2200.set_user_current_limit(p["i_max"])
                    dc2200.configure_constant_current(p["i_min"])
                    dc2200.switch_on()
                    print(f"{len(sequence)} steps x {p['step_time']:g} s = "
                          f"{len(sequence) * p['step_time']:g} s")

                    time_stamp = utc_timestamp()
                    t0 = time.monotonic()
                    if on_start:
                        on_start(t0, time_stamp, sequence)
                    for k, (cycle, direction, current) in enumerate(sequence):
                        sleep_until(t0 + k * p["step_time"])    # clock-based, no drift
                        dc2200.configure_constant_current(current)
                        rows.append((round(time.monotonic() - t0, 4), cycle, direction, current))
                        if on_step:
                            on_step(k, cycle, direction, current)
                        print(f"[{k + 1}/{len(sequence)}] cycle {cycle} {direction}: "
                              f"{current * 1e3:.2f} mA")
                    sleep_until(t0 + len(sequence) * p["step_time"])   # hold the last step
                finally:
                    dc2200.switch_off()
            finally:
                close_quietly(communicator)
    finally:
        if p["output_csv"] and rows:
            write_csv(p["output_csv"], RAMP_CSV_HEADER, rows, time_stamp)
            print(f"Data saved to {p['output_csv']}")
    return rows


def _read_set_cfg(cfg):
    """Accepts a dict or an object with the key `current` (A); optional dc2200_serial."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k, None))
    if get("current") is None:
        raise ValueError("setting 'current' is missing")
    current = float(get("current"))
    if not 0 <= current <= MAX_CURRENT_A:
        raise ValueError(f"current must be between 0 and {MAX_CURRENT_A} A")
    return current, dc2200_resource(get("dc2200_serial"))


def main_set_current(cfg):
    """Set the DC2200 LED output to a constant current and leave it running.

    cfg needs: current (A); optional dc2200_serial. The user current limit is set to the same value, so
    the device cannot exceed it. Unlike main_ramp, the output is NOT switched
    off afterwards; a current of 0 switches the output off instead.
    """
    current, resource = _read_set_cfg(cfg)
    USBCommunicator, DC2200 = _import_dc2200()

    with ThorlabsUSBDriver(product_id=DC2200_PRODUCT_ID):
        print("Kernel USB driver detached. Connecting to DC2200 via PyVISA...")
        communicator = USBCommunicator(resource)
        try:
            dc2200 = DC2200(communicator)
            if current == 0:
                dc2200.configure_constant_current(0.0)
                dc2200.switch_off()
                print("LED output switched off.")
            else:
                dc2200.set_user_current_limit(current)
                dc2200.configure_constant_current(current)
                dc2200.switch_on()
                print(f"LED output ON at {current * 1e3:.2f} mA "
                      f"(user limit {current * 1e3:.2f} mA).")
        finally:
            close_quietly(communicator)
