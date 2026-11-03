"""Kept for older imports: a ramp with photos is one case of the paired ramp
(experiments/paired_ramp.py), which works with any light source."""
from .paired_ramp import main_paired_ramp, schedule_times

PHOTO_HEADER = ["time_s", "index", "file", "utc", "step", "cycle", "direction", "current_A"]


def photo_times(n_steps, step_time, photo_delay=None, photo_interval=None):
    """Photo times in seconds from the ramp start."""
    return schedule_times(n_steps, step_time, photo_delay, photo_interval)


def main_ramp_camera(cfg):
    """Ramp with photos, as before: returns (ramp rows, list of saved photos).

    cfg as for main_paired_ramp; ``camera`` (the measurement name) is required,
    ``source`` defaults to the DC2200.
    """
    out = main_paired_ramp(cfg)
    return out["rows"], out["photos"]
