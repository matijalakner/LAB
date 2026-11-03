"""Step the LED current of a Thorlabs DC2200 up and down.

Needs the `measurement_control` package and a connected DC2200.
Currents are in AMPERES - check your LED head's rating before running.

Run:  python 01_dc2200_ramp.py
"""
from types import SimpleNamespace

from equipment import main_ramp

cfg = SimpleNamespace(
    i_min=0.0,            # A, start current
    i_max=0.5,            # A, also set as the device's user current limit
    step=0.05,            # A, current increase per step
    step_time=2.0,        # s, how long EACH step is held
    cycles=1,             # number of min -> max -> min cycles
    output_csv="output/ramp/example_ramp.csv",   # first line: time_stamp,<UTC>
)

try:
    rows = main_ramp(cfg)   # switches the LED off again, even on errors
    print(f"{len(rows)} steps done; data in {cfg.output_csv}")
except KeyboardInterrupt:
    print("Interrupted - LED output switched off, partial data saved.")
