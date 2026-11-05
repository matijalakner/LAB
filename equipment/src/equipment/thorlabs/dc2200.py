"""Thorlabs DC2200 LED driver, as a light source (sources.py) in amperes.

The instrument itself is driven by the separate `measurement_control` package;
this module adds the USB kernel-driver handling, the safety limit and the
LightSource interface, so the DC2200 can be paired with any instrument.

Currents are in AMPERES (the DC2200 accepts up to 2 A; check your LED head's rating).
"""
from contextlib import ExitStack

from ..ramp import main_source_ramp, read_ramp_cfg
from ..ramp import ramp_levels, ramp_sequence  # noqa: F401  (part of this module's API)
from ..sources import LightSource
from ..utils import read_cfg
from .common import DC2200_PRODUCT_ID, close_quietly, dc2200_resource
from .usb_driver import ThorlabsUSBDriver

MAX_CURRENT_A = 2.0
RAMP_CSV_HEADER = ["time_s", "cycle", "direction", "current_A"]


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


class DC2200Source(LightSource):
    """DC2200 in constant-current mode. ``prepare(limit)`` sets the user current limit."""

    key = "dc2200"
    name = "DC2200"
    unit = "A"
    column = "current_A"
    max_level = MAX_CURRENT_A

    def __init__(self, serial=None):
        self.resource = dc2200_resource(serial)
        self.dev = None
        self._stack = None

    @classmethod
    def from_cfg(cls, cfg):
        return cls(serial=read_cfg(cfg)("dc2200_serial"))

    def open(self):
        USBCommunicator, DC2200 = _import_dc2200()
        stack = ExitStack()
        try:
            stack.enter_context(ThorlabsUSBDriver(product_id=DC2200_PRODUCT_ID))
            print("Kernel USB driver detached. Connecting to DC2200 via PyVISA...")
            communicator = USBCommunicator(self.resource)
            stack.callback(close_quietly, communicator)
            self.dev = DC2200(communicator)
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        return self

    def close(self):
        self.dev = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None

    def prepare(self, limit=None):
        if limit is not None:
            self.dev.set_user_current_limit(self.check_level(limit, "limit"))

    def set_level(self, level):
        self.dev.configure_constant_current(self.check_level(level, "current"))

    def switch_on(self):
        self.dev.switch_on()

    def switch_off(self):
        if self.dev is not None:
            self.dev.switch_off()

    def fmt(self, level):
        return f"{level * 1e3:.2f} mA"


# ---------------------------------------------------------------------------
# commands (unchanged API)
# ---------------------------------------------------------------------------
def _read_cfg(cfg):
    """Ramp settings with the DC2200 names i_min/i_max (A); adds the VISA resource."""
    get = read_cfg(cfg)
    p = read_ramp_cfg(cfg, DC2200Source)
    p.update(i_min=p["min"], i_max=p["max"], resource=dc2200_resource(get("dc2200_serial")))
    return p


def main_ramp(cfg, on_start=None, on_step=None):
    """Stepped current ramp for the DC2200: min -> max -> min (see ramp.run_ramp).

    cfg needs: i_min, i_max (A), step (A), step_time (s); optional: cycles,
    output_csv, dc2200_serial. The user current limit is set to i_max. Returns
    rows (time_s, cycle, direction, current_A). The LED is switched off at the
    end and on any error, including Ctrl+C.
    """
    get = read_cfg(cfg)
    keys = ("i_min", "i_max", "step", "step_time", "cycles", "output_csv", "dc2200_serial",
            "final_hold")
    return main_source_ramp({**{k: get(k) for k in keys}, "source": "dc2200"},
                            on_start, on_step)


def _read_set_cfg(cfg):
    """Accepts a dict or an object with the key `current` (A); optional dc2200_serial."""
    get = read_cfg(cfg)
    if get("current") is None:
        raise ValueError("setting 'current' is missing")
    current = float(get("current"))
    if not 0 <= current <= MAX_CURRENT_A:
        raise ValueError(f"current must be between 0 and {MAX_CURRENT_A} A")
    return current, get("dc2200_serial")


def main_set_current(cfg):
    """Set a constant current and LEAVE THE LED ON; 0 switches the output off.

    cfg needs: current (A); optional dc2200_serial. The user current limit is
    set to the same value, so the device cannot exceed it.
    """
    current, serial = _read_set_cfg(cfg)
    with DC2200Source(serial) as dc:
        if current == 0:
            dc.set_level(0.0)
            print("LED output switched off.")
            return
        dc.prepare(limit=current)
        dc.set_level(current)
        dc.switch_on()
        dc.leave_on = True
        print(f"LED output ON at {current * 1e3:.2f} mA "
              f"(user limit {current * 1e3:.2f} mA).")
