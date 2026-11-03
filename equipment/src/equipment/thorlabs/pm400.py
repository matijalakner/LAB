"""Thorlabs PM400 power meter, driven directly over SCPI with PyVISA.

The `measurement_control` package has no power meter driver, so the meter is
talked to here. The `PM400` class is also used by PM400_DC2200.py.
"""
import time

from ..utils import utc_timestamp, write_csv
from .common import PM_PRODUCT_ID, PM_RESOURCE, close_quietly, pm_resource, sleep_until
from .usb_driver import ThorlabsUSBDriver

PM_CSV_HEADER = ["time_s", "power_W"]


class PM400:
    """Minimal PM400 driver: wavelength, averaging and power readings (W)."""

    def __init__(self, resource=PM_RESOURCE, timeout_ms=5000):
        try:
            import pyvisa
        except ImportError as e:
            raise RuntimeError(
                "pyvisa is required for the PM400: pip install pyvisa pyvisa-py pyusb"
            ) from e
        self._rm = pyvisa.ResourceManager("@py")   # pure-Python backend, uses pyusb
        try:
            self._inst = self._rm.open_resource(resource)
        except Exception:
            close_quietly(self._rm)
            raise
        self._inst.timeout = timeout_ms

    def idn(self):
        return self._inst.query("*IDN?").strip()

    def set_wavelength(self, nm):
        self._inst.write(f"SENS:CORR:WAV {nm}")

    def set_averaging(self, count):
        self._inst.write(f"SENS:AVER:COUN {int(count)}")

    def read_power(self):
        """Optical power in watts."""
        return float(self._inst.query("MEAS:POW?"))

    def close(self):
        close_quietly(self._inst)
        close_quietly(self._rm)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def _read_cfg(cfg):
    """Accepts a dict or an object (e.g. SimpleNamespace) with the power meter settings."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k))

    defaults = {
        "wavelength": 633.0,
        "averaging_count": 10,
        "sample_duration": 5.0,
        "sample_rate": 10.0,
        "output_csv": None,    # path; None = do not write a file
        "pm400_serial": None,  # None = $EQUIPMENT_PM400_SERIAL or the default
    }

    p = {}
    for k, default_val in defaults.items():
        try:
            val = get(k)
            p[k] = default_val if val is None else val
        except (KeyError, AttributeError):
            p[k] = default_val

    if p["wavelength"] <= 0:
        raise ValueError("wavelength must be > 0 nm")
    if p["averaging_count"] < 1:
        raise ValueError("averaging_count must be >= 1")
    if p["sample_duration"] <= 0 or p["sample_rate"] <= 0:
        raise ValueError("sample_duration and sample_rate must be > 0")

    return p


def main_power_measurement(cfg):
    """Power measurement loop for the Thorlabs PM400.

    cfg needs: wavelength (nm), averaging_count, sample_duration (s), sample_rate (Hz);
    optional: output_csv (path), pm400_serial.
    Returns a list of (time_s, power_W). If output_csv is set the readings are
    written there (also when interrupted); the first line of the file is
    ``time_stamp,<UTC time at the start of the logging>``.
    """
    p = _read_cfg(cfg)

    readings, time_stamp = [], None
    try:
        with ThorlabsUSBDriver(product_id=PM_PRODUCT_ID):
            with PM400(pm_resource(p["pm400_serial"])) as meter:
                print("Connected to:", meter.idn())
                meter.set_wavelength(p["wavelength"])
                meter.set_averaging(p["averaging_count"])
                print(f"Starting power logging at {p['wavelength']} nm...")

                total = max(1, int(round(p["sample_duration"] * p["sample_rate"])))
                dt = 1.0 / p["sample_rate"]
                time_stamp = utc_timestamp()
                t0 = time.monotonic()
                for i in range(total):
                    sleep_until(t0 + i * dt)
                    power = meter.read_power()
                    readings.append((round(time.monotonic() - t0, 4), power))
                    print(f"Sample {i + 1}/{total} - Power: {power * 1e3:.4f} mW")
    finally:
        if p["output_csv"] and readings:
            write_csv(p["output_csv"], PM_CSV_HEADER, readings, time_stamp)
            print(f"Data saved to {p['output_csv']}")
    print("Power measurement sequence completed.")
    return readings
