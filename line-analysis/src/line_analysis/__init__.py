"""Line detection and analysis for the photos and videos taken with ``equipment``.

Names are imported lazily, so ``import line_analysis`` is fast and OpenCV or
matplotlib are only loaded when they are used.
"""
from importlib import import_module

__version__ = "1.0.0"

_EXPORTS = {
    "DetectionConfig": "detect", "detect_lines": "detect", "mark_image": "detect",
    "plot_line_signal": "detect",
    "load_image": "image", "analyse_image": "image",
    "split_video": "video", "process_video": "video",
    "read_lines_csv": "spacing", "spacing_stats": "spacing", "analyse_spacing": "spacing",
    "tune_candidates": "tune", "tune_parameters": "tune",
    "TrackingConfig": "track", "track_lines": "track", "track_folder": "folder",
    "main_jumps": "jumps", "JumpConfig": "jumps", "find_jumps": "jumps",
    "main_folder": "folder", "choose_parameters": "folder", "flag_unusual": "folder",
    "photo_times": "folder", "get_sorted_photos": "folder",
    "main_report": "report", "acquire": "report", "plot_report": "report",
    "plot_timeline": "report", "find_ramp_csv": "report", "liv_curve": "report",
    "read_log": "logs", "read_ramp": "logs", "capture_times": "logs",
    "find_frames_log": "logs", "read_frames_log": "logs",
    "read_time_stamp": "utils", "write_csv": "utils", "utc_timestamp": "utils",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
