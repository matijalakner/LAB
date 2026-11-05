"""CoolLED pE-300: status, a constant intensity, and a stepped intensity ramp.

Needs pyserial (pip install -e ".[coolled]") and the pE-300 on USB. The port is
found automatically; set it with port="/dev/ttyACM0" (or $EQUIPMENT_PE300_PORT)
if more than one serial device is connected. Levels are intensities in %.

Run:  python 07_pe300.py
"""
import time

from equipment import main_pe300_off, main_pe300_set, main_pe300_status, main_source_ramp
from equipment.utils import output_csv_path

# 1. port, firmware, wavelengths and the state of channels A, B, C
main_pe300_status()

# 2. white light (all three channels) at 30 %, left on for 5 s, then off
main_pe300_set({"intensity": 30, "channels": "ABC"})
time.sleep(5)
main_pe300_off()

# 3. blue channel only: 0 -> 100 % in 10 % steps, 2 s each, and back
#    -> <data>/output/ramp/example_pe300_ramp.csv   (time_s, cycle, direction, intensity_pct)
try:
    rows = main_source_ramp({"source": "pe300", "channels": "B",
                             "min": 0, "max": 100, "step": 10, "step_time": 2,
                             "output_csv": output_csv_path(None, "ramp", "example_pe300_ramp.csv")})
except KeyboardInterrupt:
    print("Interrupted - light switched off, partial data saved.")
