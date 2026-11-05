"""Thorlabs DC2200 LED driver, as a light source (sources.py) in amperes.

Two drivers, chosen with $EQUIPMENT_DC2200_DRIVER (auto / builtin / measurement_control):

builtin
    SCPI over VISA (visa.py), on Linux and Windows alike (DC2200 Operation
    Manual, SCPI command reference):
        SOURce1:MODe CC                          constant-current mode
        SOURce1:CURRent:LIMit:AMPLitude <A>      user current limit
        SOURce1:CCURrent:CURRent <A>             LED current
        OUTPut1:STATe ON|OFF                     LED output
    Every setting is read back, and the error queue (SYSTem:ERRor?) is
    checked: if the instrument does not accept a command, the run stops
    before the LED is switched on.
measurement_control
    The lab's separate package (Linux). ``auto`` uses it when it is installed
    on Linux, because it is the combination tested on the hardware, and the
    built-in driver otherwise (always on Windows).

Currents are in AMPERES (the DC2200 accepts up to 2 A; check your LED head's rating).
"""
import os
from contextlib import ExitStack

from ..ramp import main_source_ramp, read_ramp_cfg
from ..ramp import ramp_levels, ramp_sequence  # noqa: F401  (part of this module's API)
from ..sources import LightSource
from ..utils import read_cfg
from .common import DC2200_PRODUCT_ID, close_quietly, dc2200_resource
from .usb_driver import ThorlabsUSBDriver
from .visa import is_windows, open_instrument, scpi_errors

MAX_CURRENT_A = 2.0
MIN_LIMIT_A = 0.001          # the DC2200 does not accept a user limit below 1 mA
RAMP_CSV_HEADER = ["time_s", "cycle", "direction", "current_A"]
DRIVER_ENV = "EQUIPMENT_DC2200_DRIVER"


class DC2200SCPI:
    """Built-in DC2200 driver over an open PyVISA resource (same methods as
    measurement_control's DC2200, so DC2200Source works with either)."""

    def __init__(self, inst, check_idn=True):
        self.inst = inst
        self.idn = inst.query("*IDN?").strip()
        if check_idn and "DC2200" not in self.idn.upper():
            raise RuntimeError(f"this is not a DC2200: {self.idn}")
        inst.write("*CLS")
        self._cc = False

    # -- helpers -------------------------------------------------------------------
    def _write(self, cmd):
        self.inst.write(cmd)
        errors = scpi_errors(self.inst)
        if errors:
            text = "; ".join(f"{c} {m}" for c, m in errors)
            raise RuntimeError(f"DC2200 refused '{cmd}': {text}")

    def _query_float(self, cmd):
        return float(self.inst.query(cmd).strip())

    @staticmethod
    def _close_enough(got, want):
        return abs(got - want) <= max(2e-4, 0.01 * abs(want))

    def _set_checked(self, cmd, query, value, what):
        self._write(f"{cmd} {value:.6f}")
        got = self._query_float(query)
        if not self._close_enough(got, value):
            raise RuntimeError(f"DC2200 {what} is {got:g} A after setting {value:g} A")
        return got

    # -- the four operations ---------------------------------------------------------
    def set_constant_current_mode(self):
        self._write("SOUR1:MODE CC")
        mode = self.inst.query("SOUR1:MODE?").strip().upper()
        if mode not in ("CC", "1"):
            raise RuntimeError(f"DC2200 is in mode {mode}, not constant current")
        self._cc = True

    def set_user_current_limit(self, amps):
        return self._set_checked("SOUR1:CURR:LIM:AMPL", "SOUR1:CURR:LIM:AMPL?",
                                 max(float(amps), MIN_LIMIT_A), "user current limit")

    def configure_constant_current(self, amps):
        if not self._cc:
            self.set_constant_current_mode()
        return self._set_checked("SOUR1:CCUR:CURR", "SOUR1:CCUR:CURR?", float(amps),
                                 "LED current")

    def _output(self, on):
        self._write(f"OUTP1:STAT {'ON' if on else 'OFF'}")
        state = self.inst.query("OUTP1:STAT?").strip().upper()
        if state not in (("1", "ON") if on else ("0", "OFF")):
            raise RuntimeError(f"DC2200 output is {state} after switching it "
                               f"{'on' if on else 'off'}")

    def switch_on(self):
        self._output(True)

    def switch_off(self):
        self._output(False)

    def measured_current(self):
        return self._query_float("MEAS:CURR?")


def dc2200_driver():
    """'builtin' or 'measurement_control' (see the module docstring)."""
    choice = (os.environ.get(DRIVER_ENV) or "auto").strip().lower()
    if choice not in ("auto", "builtin", "measurement_control"):
        raise ValueError(f"{DRIVER_ENV} must be auto, builtin or measurement_control")
    if choice != "auto":
        return choice
    if is_windows():
        return "builtin"
    try:
        _import_dc2200()
        return "measurement_control"
    except RuntimeError:
        return "builtin"


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
        driver = dc2200_driver()
        stack = ExitStack()
        try:
            if driver == "measurement_control":
                USBCommunicator, DC2200 = _import_dc2200()
                stack.enter_context(ThorlabsUSBDriver(product_id=DC2200_PRODUCT_ID))
                print("Kernel USB driver detached. Connecting to DC2200 via PyVISA...")
                communicator = USBCommunicator(self.resource)
                stack.callback(close_quietly, communicator)
                self.dev = DC2200(communicator)
            else:
                inst = stack.enter_context(open_instrument(self.resource, DC2200_PRODUCT_ID))
                self.dev = DC2200SCPI(inst)
                print(f"DC2200 connected (built-in driver): {self.dev.idn}")
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
