"""Measurement control for the Canon EOS R10: manual photos, time-lapse, video.

Photos and videos go to  <input_dir>/folder/<name>/<name>_XXXX.jpg  (and .mp4),
numbered from 0000. Numbering continues after the files already in the folder,
so nothing is ever overwritten and a run can be continued with the same name.
That folder can be analysed directly with LineTracker's  measurement analysis folder.

Every run also writes a log  <output_dir>/camera/camera_<UTC time>.csv  with the
computer time of every capture (first line: time_stamp,<UTC time at the start>):

    time_s, index, file, utc
"""
import time
from pathlib import Path

from ..capture import (CaptureLog, _report, capture_folder, next_index,  # noqa: F401
                       numbered_path)
from ..utils import read_cfg as _read_cfg
from ..utils import utc_timestamp
from .camera import VIDEO_SUFFIXES, CanonCamera

SETTING_KEYS = ("shutter", "iso", "whitebalance", "colortemperature", "picturestyle",
                "imageformat")


def _connect(get, verbose=True):
    """Open the camera and apply the settings from cfg; caller must close it."""
    cam = CanonCamera().open()
    try:
        model = cam.get("model")
        if verbose:
            print(f"Connected to {model or 'camera'}.")
        if get("sync_clock"):
            cam.sync_clock()
            if verbose:
                print("  camera clock set to the computer clock")
        settings = {k: get(k) for k in SETTING_KEYS}
        if any(v is not None for v in settings.values()) and verbose:
            print("Settings:")
        cam.apply_settings(**settings, verbose=verbose)
    except BaseException:
        cam.close()
        raise
    return cam


def _shoot(cam, folder, name, log, keep_on_card=False, verbose=True):
    index = next_index(folder, name)
    dest = numbered_path(folder, name, index, ".jpg")
    t, utc = time.monotonic(), utc_timestamp()
    cam.capture_photo(dest, keep_on_card=keep_on_card)
    log.add(index, dest, t, utc)
    if verbose:
        print(f"  saved {dest}")
    return dest


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def main_camera_info(cfg=None):
    """Print the current camera settings and the values each one accepts."""
    get = _read_cfg(cfg or {})
    with _connect(get) as cam:
        for key, (value, choices) in cam.summary().items():
            print(f"{key:<17} {value}")
            if choices and key not in ("model", "battery"):
                print(f"{'':<17} choices: {', '.join(c for c in choices if c.strip())}")


def main_photo(cfg):
    """Manual photo(s).

    cfg: name; optional input_dir ('input'), output_csv (log path), interactive
    (Enter takes a photo, q + Enter quits), keep_on_card, sync_clock and the
    camera settings shutter, iso, whitebalance, colortemperature, picturestyle,
    imageformat. Returns the list of saved files.
    """
    get = _read_cfg(cfg)
    folder = capture_folder(get("name"), get("input_dir") or "input")
    saved, log = [], CaptureLog(get("output_csv"))
    try:
        with _connect(get) as cam:
            cam.set_capture_target(card=bool(get("keep_on_card")))
            if not get("interactive"):
                saved.append(_shoot(cam, folder, get("name"), log, get("keep_on_card")))
            else:
                print("Enter = take a photo, q + Enter = quit.")
                while True:
                    try:
                        answer = input("> ").strip().lower()
                    except EOFError:
                        break
                    if answer in ("q", "quit", "exit"):
                        break
                    saved.append(_shoot(cam, folder, get("name"), log, get("keep_on_card")))
    finally:
        _report(saved, folder, log)
        log.close()
    return saved


def main_timelapse(cfg):
    """A photo every ``interval`` seconds.

    cfg: name, interval (s); optional count (number of photos) or duration (s);
    with neither it runs until Ctrl+C. Other options as in main_photo. The
    first photo is taken at t = 0; the times come from a clock, so they do not
    drift. If one capture takes longer than the interval, the next photo is
    taken right away and a warning is printed.
    """
    get = _read_cfg(cfg)
    interval = float(get("interval"))
    count, duration = get("count"), get("duration")
    if interval <= 0:
        raise ValueError("interval must be > 0 s")
    if count is not None and int(count) < 1:
        raise ValueError("count must be >= 1")
    if duration is not None:
        n_dur = int(float(duration) // interval) + 1
        count = n_dur if count is None else min(int(count), n_dur)
    folder = capture_folder(get("name"), get("input_dir") or "input")

    saved, log = [], CaptureLog(get("output_csv"))
    try:
        with _connect(get) as cam:
            cam.set_capture_target(card=bool(get("keep_on_card")))
            total = f"{count} photos" if count else "until Ctrl+C"
            print(f"Time-lapse: one photo every {interval:g} s, {total}.")
            log.start()
            t0 = log.t0
            k = 0
            while count is None or k < int(count):
                deadline = t0 + k * interval
                late = time.monotonic() - deadline
                if late > 0.5 and k > 0:
                    print(f"  warning: {late:.1f} s late, the capture takes longer "
                          f"than the {interval:g} s interval")
                while time.monotonic() < deadline:          # keep the USB link alive
                    cam.drain_events(min(1.0, deadline - time.monotonic()))
                print(f"[{k + 1}{'/' + str(count) if count else ''}] "
                      f"t = {time.monotonic() - t0:.1f} s")
                saved.append(_shoot(cam, folder, get("name"), log, get("keep_on_card")))
                k += 1
    finally:
        _report(saved, folder, log)
        log.close()
    return saved


def main_video(cfg):
    """Record a video on the camera's memory card and download it.

    cfg: name; optional duration (s; without it recording stops on Enter),
    delete_from_card (default keep it), input_dir, output_csv, sync_clock and
    the camera settings. The camera's photo/movie switch must be on movie.
    Saved as <name>_XXXX.mp4. Ctrl+C during the recording stops it early and
    the video is still downloaded; recording is also stopped on any error.
    """
    get = _read_cfg(cfg)
    duration = get("duration")
    if duration is not None and float(duration) <= 0:
        raise ValueError("duration must be > 0 s")
    folder = capture_folder(get("name"), get("input_dir") or "input")

    saved, log = [], CaptureLog(get("output_csv"))
    try:
        with _connect(get) as cam:
            before = set(cam.list_files())
            log.start()
            t_start, utc_start = log.t0, log.time_stamp
            cam.start_movie()
            added = []
            print("Recording", f"for {float(duration):g} s ..." if duration
                  else "... press Enter to stop.")
            try:
                if duration:
                    end = t_start + float(duration)
                    while time.monotonic() < end:
                        added += cam.drain_events(min(1.0, end - time.monotonic()))
                else:
                    input()
            except KeyboardInterrupt:
                print("\nCtrl+C: stopping early, the video is still downloaded.")
            finally:
                cam.stop_movie()
                print(f"Stopped after {time.monotonic() - t_start:.1f} s.")
            # the camera needs a moment to close the file
            added += cam.drain_events(5.0)
            videos = [f for f in added if Path(f[1]).suffix.lower() in VIDEO_SUFFIXES]
            if not videos:
                time.sleep(2.0)
                videos = [f for f in set(cam.list_files()) - before
                          if Path(f[1]).suffix.lower() in VIDEO_SUFFIXES]
            if not videos:
                raise RuntimeError("the camera reported no new video file; check its card")
            for cam_folder, cam_name in sorted(videos):
                index = next_index(folder, get("name"))
                dest = numbered_path(folder, get("name"), index, Path(cam_name).suffix.lower())
                print(f"Downloading {cam_name} ...")
                cam.download(cam_folder, cam_name, dest)
                log.add(index, dest, t_start, utc_start)
                saved.append(dest)
                print(f"  saved {dest}")
                if get("delete_from_card"):
                    cam.delete(cam_folder, cam_name)
    finally:
        _report(saved, folder, log)
        log.close()
    return saved
