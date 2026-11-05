"""DC2200 current ramp with a Canon EOS R10 photo in the middle of every step.

Needs the `measurement_control` package, pyusb and python-gphoto2, a connected
DC2200 and the camera (USB, Wi-Fi/Bluetooth off, mode dial on M).
Currents are in AMPERES - check your LED head's rating before running.

Photos:     <data>/input/folder/<NAME>/<NAME>_XXXX.jpg
Ramp:       <data>/output/ramp/example_ramp_camera.csv
Photo log:  <data>/output/ramp/example_ramp_camera_photos.csv  (same t = 0, with current_A)

Run:  python 06_ramp_with_photos.py
"""
from equipment import main_ramp_camera
from equipment.utils import output_csv_path

cfg = {
    # ramp
    "i_min": 0.05, "i_max": 0.5, "step": 0.05, "step_time": 10.0, "cycles": 1,
    "output_csv": output_csv_path(None, "ramp", "example_ramp_camera.csv"),
    # camera
    "camera": "sample-1-measurement",   # measurement name = photo folder and file prefix
    "photo_delay": 5.0,                 # one photo 5 s after every step starts
    # "photo_interval": 2.0,            # or: a photo every 2 s instead
    "shutter": "1/250", "iso": 100, "whitebalance": "Daylight",
    "sync_clock": True,
    # FLIR Blackfly S instead of the Canon:
    # "camera_type": "flir", "shutter": "1/250", "gain": 0, "whitebalance": "off",
}

try:
    rows, photos = main_ramp_camera(cfg)    # LED off at the end and on any error
    print(f"{len(rows)} steps, {len(photos)} photos")
except KeyboardInterrupt:
    print("Interrupted - LED output switched off, photos and partial data kept.")
