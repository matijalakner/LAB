"""Readers for the files written by the ``equipment`` package.

    <input_dir>/folder/<name>/<name>_XXXX.jpg|png|tif|mp4   photos and videos
    <output_dir>/ramp/<ramp>.csv           time_s, cycle, direction, LEVEL
    <output_dir>/ramp/<ramp>_photos.csv    time_s, index, file, utc, step, cycle, direction, LEVEL
    <output_dir>/ramp/<ramp>_power.csv     time_s, power_W, utc, step, cycle, direction, LEVEL
    <output_dir>/camera/<camera|flir>_<UTC>.csv          time_s, index, file, utc
    <output_dir>/camera/flir_<UTC>_frames.csv            frame, time_s, camera_time_s, frame_id
    <output_dir>/liv/liv_<UTC>.csv         time_s, cycle, direction, LEVEL, power_W

All but the LIV file start with ``time_stamp,<UTC time at t = 0>``. LEVEL is
``current_A`` (DC2200) or ``intensity_pct`` (pE-300).
"""
from pathlib import Path

from .paths import input_root, output_root
import pandas as pd

from .utils import read_time_stamp

# level column -> (quantity, unit, column name in the report table)
LEVELS = {
    "current_A": ("current", "A", "current[A]"),
    "intensity_pct": ("intensity", "%", "intensity[%]"),
}
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}
COMPANIONS = ("photos", "power")


def read_log(path):
    """-> (t0, DataFrame); t0 is the tz-aware UTC time of the time stamp line or None."""
    stamp = read_time_stamp(path)
    df = pd.read_csv(path, skiprows=1 if stamp else 0)
    return (pd.Timestamp(stamp) if stamp else None), df


def level_column(df, path=""):
    """The level column of a ramp/photo/power/LIV table (current_A or intensity_pct)."""
    for c in LEVELS:
        if c in df.columns:
            return c
    raise ValueError(f"{path}: no level column (expected one of {', '.join(LEVELS)})")


# ---------------------------------------------------------------------------
# ramps
# ---------------------------------------------------------------------------
def companion(ramp_csv, kind):
    """<ramp>_photos.csv or <ramp>_power.csv next to a ramp CSV."""
    p = Path(ramp_csv)
    return p.with_name(f"{p.stem}_{kind}.csv")


def ramp_files(output_dir=None):
    """Every ramp CSV in <output_dir>/ramp/, oldest first (by its time stamp line)."""
    output_dir = output_root(output_dir)
    folder = Path(output_dir) / "ramp"
    files = [p for p in folder.glob("*.csv")
             if not any(p.stem.endswith("_" + k) for k in COMPANIONS)]

    def key(p):
        try:
            stamp = read_time_stamp(p)
            return (pd.Timestamp(stamp).value if stamp else 0, p.name)
        except (OSError, ValueError):
            return (0, p.name)
    return sorted(files, key=key)


def read_ramp(path):
    """-> (t0, DataFrame with time_s, cycle, direction, LEVEL and step, level column)."""
    t0, ramp = read_log(path)
    if t0 is None:
        raise ValueError(f"{path}: the first line must be 'time_stamp,<UTC time>' "
                         "(is this a ramp written by equipment?)")
    if "time_s" not in ramp.columns:
        raise ValueError(f"{path}: missing column time_s")
    col = level_column(ramp, path)
    ramp = ramp.copy()
    ramp["step"] = range(1, len(ramp) + 1)
    return t0, ramp, col


# ---------------------------------------------------------------------------
# photo times
# ---------------------------------------------------------------------------
def capture_times(output_dir=None):
    """{file name: (utc Timestamp, log path)} from every capture log and ramp photo log.

    The utc column is the computer time when the capture started, so it does not
    depend on the camera clock. Later logs win when a name appears twice.
    """
    output_dir = output_root(output_dir)
    out = {}
    root = Path(output_dir)
    logs = [p for p in (root / "camera").glob("*.csv") if not p.stem.endswith("_frames")]
    logs += list((root / "ramp").glob("*_photos.csv"))
    for log in sorted(logs, key=lambda p: (read_time_stamp(p) or "", p.name)):
        try:
            _, df = read_log(log)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if not {"file", "utc"} <= set(df.columns):
            continue
        for file, utc in zip(df["file"].astype(str), df["utc"]):
            try:
                out[file] = (pd.Timestamp(utc), log)
            except (ValueError, TypeError):
                pass
    return out


def find_frames_log(video, output_dir=None):
    """The FLIR ``_frames.csv`` that belongs to a video, or None.

    The video's capture log (``<output_dir>/camera/flir_<UTC>.csv``) lists the
    video file; its frame log sits next to it with ``_frames`` added.
    """
    output_dir = output_root(output_dir)
    name = Path(video).name
    for log in sorted((Path(output_dir) / "camera").glob("*.csv")):
        if log.stem.endswith("_frames"):
            continue
        frames = log.with_name(log.stem + "_frames.csv")
        if not frames.exists():
            continue
        try:
            _, df = read_log(log)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if "file" in df.columns and name in set(df["file"].astype(str)):
            return frames
    return None


def read_frames_log(path):
    """-> (t0, list of real frame times in s, indexed by frame number)."""
    t0, df = read_log(path)
    if not {"frame", "time_s"} <= set(df.columns):
        raise ValueError(f"{path}: not a frame log (needs frame, time_s)")
    df = df.sort_values("frame")
    return t0, df["time_s"].astype(float).tolist()


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def resolve_folder(path, input_dir=None):
    """A photo folder, given as a path or as the measurement name."""
    input_dir = input_root(input_dir)
    p = Path(path)
    if p.is_dir():
        return p
    q = Path(input_dir) / "folder" / str(path)
    if q.is_dir():
        return q
    raise FileNotFoundError(f"No folder '{path}' (also tried {q})")


def resolve_media(path, input_dir=None):
    """A photo or video, given as a path or as a file name like mysample_0003.mp4."""
    input_dir = input_root(input_dir)
    p = Path(path)
    if p.is_file():
        return p
    name = p.name
    stem = Path(name).stem
    if "_" in stem:
        q = Path(input_dir) / "folder" / stem.rsplit("_", 1)[0] / name
        if q.is_file():
            return q
    raise FileNotFoundError(f"File not found: {path}")
