"""Canon EOS R10 over USB: settings, one photo, a time-lapse and a video.

Needs python-gphoto2 (pip install -e ".[canon]") and the camera connected
by USB with Wi-Fi/Bluetooth off and the mode dial on M.

Files go to input/folder/<name>/<name>_XXXX.jpg (and .mp4),
the capture log to output/camera/.

Run:  python 04_canon_camera.py
"""
from equipment import main_camera_info, main_photo, main_timelapse, main_video
from equipment.utils import output_csv_path

NAME = "sample-1-measurement"
SETTINGS = {"shutter": "1/250", "iso": 200, "whitebalance": "Daylight"}

# 1. what the camera is set to, and which values it accepts
main_camera_info()

# 2. one manual photo  ->  input/folder/sample-1-measurement/sample-1-measurement_0000.jpg
main_photo({"name": NAME, **SETTINGS, "sync_clock": True,
            "output_csv": output_csv_path("output", "camera")})

# 3. a photo every 5 s for one minute (13 photos: t = 0, 5, ..., 60 s)
main_timelapse({"name": NAME, "interval": 5, "duration": 60, **SETTINGS,
                "output_csv": output_csv_path("output", "camera")})

# 4. a 10 s video (photo/movie switch on movie, memory card inserted)
main_video({"name": NAME, "duration": 10})
