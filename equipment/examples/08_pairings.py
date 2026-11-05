"""Pair any light source with any measurement: one function, main_paired_ramp.

    source       "dc2200" (levels in A) or "pe300" (levels in %)
    photos       camera=<name>, camera_type "canon" or "flir" (+ camera settings)
    power        power=True (PM400), wavelength, averaging_count

Each paired instrument measures in its own thread, once per step by default.
All are connected before the light is switched on; if one fails, the ramp
stops and the light is switched off. Logs: <ramp>.csv, <ramp>_photos.csv,
<ramp>_power.csv, all with the same t = 0 and the level of every measurement.

Run one of the blocks below:  python 08_pairings.py
"""
from equipment import main_paired_ramp
from equipment.utils import output_csv_path

RAMP_PE300 = {"source": "pe300", "channels": "ABC",
              "min": 0, "max": 100, "step": 10, "step_time": 10}
RAMP_DC2200 = {"source": "dc2200", "min": 0.05, "max": 1.0, "step": 0.05, "step_time": 100}
FLIR = {"camera_type": "flir", "shutter": "1/250", "gain": 0, "whitebalance": "off"}
CANON = {"camera_type": "canon", "shutter": "1/250", "iso": 100,
         "whitebalance": "Daylight", "sync_clock": True}
PM400 = {"power": True, "wavelength": 450, "averaging_count": 10}

# pE-300 + PM400: optical power at every intensity step
main_paired_ramp({**RAMP_PE300, **PM400, "output_csv": output_csv_path(None, "ramp", "pe300_pm400.csv")})

# pE-300 + FLIR: a photo in the middle of every step
main_paired_ramp({**RAMP_PE300, **FLIR, "camera": "pe300-flir",
                  "output_csv": output_csv_path(None, "ramp", "pe300_flir.csv")})

# pE-300 + FLIR + PM400 at once (power every 2 s instead of once per step)
main_paired_ramp({**RAMP_PE300, **FLIR, **PM400, "camera": "pe300-flir-pm",
                  "power_interval": 2, "output_csv": output_csv_path(None, "ramp", "pe300_flir_pm400.csv")})

# DC2200 + Canon (the classic ramp with photos) + PM400
main_paired_ramp({**RAMP_DC2200, **CANON, **PM400, "camera": "dc-canon-pm",
                  "output_csv": output_csv_path(None, "ramp", "dc2200_canon_pm400.csv")})
