"""FLIR Blackfly S (BFS-U3-27S5C-C) over USB3: settings, one photo, a time-lapse, a video.

Needs Spinnaker + PySpin, or Aravis + PyGObject (see README, "FLIR camera setup"),
and the camera on a USB3 port.

Files go to <data>/input/folder/<name>/<name>_XXXX.jpg (and .mp4),
the capture log to <data>/output/camera/.

Run:  python 05_flir_camera.py
"""
from equipment import (main_flir_info, main_flir_list, main_flir_photo,
                         main_flir_timelapse, main_flir_video)
from equipment.utils import output_csv_path, utc_timestamp

NAME = "sample-1-measurement"
# fixed exposure / gain / white balance, so every photo is taken the same way
SETTINGS = {"shutter": "1/250", "gain": 0, "whitebalance": "off",
            "wb_red": 1.4, "wb_blue": 2.0, "gamma": "off"}


def log():
    return output_csv_path(None, "camera", f"flir_{utc_timestamp(compact=True)}.csv")


# 1. which cameras are connected, what the camera is set to and what it accepts
main_flir_list()
main_flir_info()

# 2. one photo  ->  <data>/input/folder/sample-1-measurement/sample-1-measurement_XXXX.jpg
main_flir_photo({"name": NAME, **SETTINGS, "output_csv": log()})

# 3. a photo every 5 s for one minute, lossless PNG
main_flir_timelapse({"name": NAME, "interval": 5, "duration": 60, **SETTINGS,
                     "save_format": "png", "output_csv": log()})

# 4. a 10 s video at 20 fps, written on the computer as .mp4
main_flir_video({"name": NAME, "duration": 10, "fps": 20, **SETTINGS, "output_csv": log()})
