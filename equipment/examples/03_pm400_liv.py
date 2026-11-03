"""Log optical power with the Thorlabs PM400, then measure light-power (LIV) curves
with the DC2200 and the pE-300 (any light source works with main_liv_measurement).

Needs pyusb + pyvisa + pyvisa-py (pip install -e ".[thorlabs]"), the
`measurement_control` package for the DC2200, pyserial for the pE-300.
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

# 2. DC2200: 0 -> 50 mA in 10 s and back, power at every point -> output/liv/liv_<UTC>.csv
try:
    rows = main_liv_measurement({
        "source": "dc2200", "i_min": 0.0, "i_max": 0.05, "ramp_duration": 10,
        "update_rate": 10, "wavelength": 450, "output_csv": output_csv_path("output", "liv")})
    print(f"{len(rows)} points")
except KeyboardInterrupt:
    print("Interrupted - light switched off, partial data saved.")

# 3. the same with the pE-300 (levels in %), blue channel only
main_liv_measurement({
    "source": "pe300", "channels": "B", "i_min": 0, "i_max": 100, "ramp_duration": 20,
    "update_rate": 5, "wavelength": 470, "output_csv": output_csv_path("output", "liv")})
