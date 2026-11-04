"""Video analysis: take a frame every N seconds and analyse each like an image.

For a FLIR video the real time of every frame is in the ``_frames.csv`` log that
``equipment flir video`` writes. A streaming camera can drop frames, so the
nominal frame rate in the file is not exact; with the log the frames are
chosen, and given their times, from the real clock.
"""
from .paths import input_root, output_root
import json
from pathlib import Path

import numpy as np

from .detect import DetectionConfig
from .image import analyse_image
from .logs import find_frames_log, read_frames_log, resolve_media
from .utils import utc_timestamp, write_csv


def _pick_frames(total, fps, interval, frame_times=None):
    """[(frame_index, time_s)] one every ``interval`` seconds, first at t = 0."""
    if frame_times:
        times = np.asarray(frame_times[:total], dtype=float)
        times = times - times[0]
        out, seen = [], set()
        for t in np.arange(0.0, times[-1] + 1e-9, interval):
            i = int(np.searchsorted(times, t))
            if i > 0 and (i == len(times) or t - times[i - 1] <= times[i] - t):
                i -= 1
            if i not in seen:
                seen.add(i)
                out.append((i, float(times[i])))
        return out
    out, seen = [], set()
    for t in np.arange(0.0, total / fps, interval):
        i = min(int(round(t * fps)), total - 1)
        if i not in seen:                      # interval shorter than one frame
            seen.add(i)
            out.append((i, i / fps))
    return out


def split_video(video_path, frames_dir, interval=1.0, frame_times=None):
    """Save one frame every ``interval`` seconds as frame_<index>.png.

    ``frame_times``: real time (s) of every frame, e.g. from a FLIR frame log.
    Returns a list of (frame_index, time_s, path), in order.
    """
    import cv2

    video_path, frames_dir = Path(video_path), Path(frames_dir)
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if interval <= 0:
        raise ValueError("interval must be > 0 seconds")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or total <= 0:
            raise ValueError("Could not read frame rate / frame count from the video.")
        frames_dir.mkdir(parents=True, exist_ok=True)
        pad = max(5, len(str(total)))
        saved = []
        for idx, t in _pick_frames(total, fps, interval, frame_times):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            path = frames_dir / f"frame_{idx:0{pad}d}.png"
            if not cv2.imwrite(str(path), frame):
                raise OSError(f"Could not write {path}")
            saved.append((idx, t, path))
        return saved
    finally:
        cap.release()


def process_video(video_path, output_dir=None, interval=1.0, config=None,
                  frames_log="auto", input_dir=None, verbose=True):
    """Split a video every ``interval`` seconds and analyse every frame.

    ``video_path`` may also be just the file name (mysample_0003.mp4), which is
    looked up in <input_dir>/folder/mysample/. ``frames_log``: "auto" finds the
    FLIR frame log through the capture logs in <output_dir>/camera/, a path uses
    that file, None uses the nominal frame rate.

    Layout (name = video file name without extension):
        <output_dir>/video/frames/<name>/frame_XXXXX.png        raw frames
        <output_dir>/video/<name>/frame_XXXXX_marked.png        marked frames
        <output_dir>/video/<name>/lines.csv                     time, frame, lines

    The first line of lines.csv is ``time_stamp,<UTC>``: the start of the
    recording when a frame log is used, otherwise the start of the analysis.
    Returns a list of dicts with time, frame and lines.
    """
    output_dir = output_root(output_dir)
    input_dir = input_root(input_dir)
    config = config or DetectionConfig()
    video_path = resolve_media(video_path, input_dir)
    time_stamp, frame_times = utc_timestamp(), None
    if frames_log == "auto":
        frames_log = find_frames_log(video_path, output_dir)
    if frames_log:
        t0, frame_times = read_frames_log(frames_log)
        if t0 is not None:
            time_stamp = t0.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if verbose:
            print(f"Frame times from {frames_log}")

    name = video_path.stem
    root = Path(output_dir) / "video"
    frames_dir, out_dir = root / "frames" / name, root / name
    if verbose:
        print(f"Splitting {video_path.name} every {interval:g} s into {frames_dir}/ ...")
    frames = split_video(video_path, frames_dir, interval, frame_times)
    if not frames:
        raise ValueError("No frames could be read from the video.")
    if verbose:
        print(f"Saved {len(frames)} frames. Analysing ...")

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, (idx, t, path) in enumerate(frames, start=1):
        res = analyse_image(path, out_dir, config, write_csv=False)
        rows.append({"time": round(t, 3), "frame": idx,
                     "lines": [round(x, 1) for x in res["lines"]]})
        if verbose:
            print(f"  [{n}/{len(frames)}] t = {t:.2f} s, frame {idx}: "
                  f"{len(res['lines'])} lines")
    csv_path = write_csv(out_dir / "lines.csv", ["time", "frame", "lines"],
                         [(r["time"], r["frame"], json.dumps(r["lines"])) for r in rows],
                         time_stamp)
    if verbose:
        print(f"Data: {csv_path}")
    return rows
