"""Log optical power with the Thorlabs PM400, then measure a light-current (LIV) curve.

Needs pyusb + pyvisa + pyvisa-py (pip install -e ".[thorlabs]"), the
`measurement_control` package for the DC2200, and both instruments connected.
Currents are in AMPERES - check your LED head's rating before running.

Run:  python 03_pm400_liv.py
"""
from equipment import main_liv_measurement, main_power_measurement
from equipment.utils import output_csv_path

# 1. 5 s of power readings at 10 Hz  ->  output/pm/pm_<UTC>.csv  (time_s, power_W)
readings = main_power_measurement({
    "wavelength": 450, "averaging_count": 10, "sample_duration": 5, "sample_rate": 10,
    "output_csv": output_csv_path("output", "pm")})
print(f"{len(readings)} readings")

# 2. 0 -> 50 mA in 10 s and back, power at every point  ->  output/liv/liv_<UTC>.csv
try:
    rows = main_liv_measurement({
        "i_min": 0.0, "i_max": 0.05, "ramp_duration": 10, "update_rate": 10,
        "wavelength": 450, "output_csv": output_csv_path("output", "liv")})
    print(f"{len(rows)} points")
except KeyboardInterrupt:
    print("Interrupted - LED output switched off, partial data saved.")
