"""Measurement control for the FLIR Blackfly S: manual photos, time-lapse, video.

Same files and logs as the Canon commands (canon/capture.py):

    <input_dir>/folder/<name>/<name>_XXXX.jpg      (.png / .tif with save_format)
    <input_dir>/folder/<name>/<name>_XXXX.mp4      video, written on the computer
    <output_dir>/camera/flir_<UTC time>.csv        time_s, index, file, utc

Numbering continues after the files already in the folder. A video also gets
``<log name>_frames.csv`` with the time of every frame, because a streaming
camera can drop frames and then the video's nominal frame rate is not exact.
"""
import csv
import threading
import time

import cv2

from ..capture import CaptureLog, _report, capture_folder, next_index, numbered_path
from ..utils import read_cfg as _read_cfg
from ..utils import utc_timestamp
from .camera import FlirCamera, list_cameras, to_bgr

SETTING_KEYS = ("shutter", "gain", "whitebalance", "wb_red", "wb_blue", "gamma",
                "black_level", "pixel_format", "fps", "defaults")
CANON_ONLY = ("iso", "colortemperature", "picturestyle", "imageformat")
DEFAULT_VIDEO_FPS = 10.0


def _connect(get, verbose=True, mode="photo"):
    """Open the camera and apply the settings from cfg; caller must close it."""
    cam = FlirCamera(serial=get("serial"), backend=get("backend") or "auto",
                     save_format=(get("save_format") or "jpg").lower(),
                     quality=get("quality") or 95)
    cam.open()
    try:
        if verbose:
            print(f"Connected to {cam.model} (serial {cam.serial}, {cam.backend}).")
        unused = [k for k in CANON_ONLY if get(k) is not None]
        if unused and verbose:
            print(f"  ignored (Canon only): {', '.join(unused)}")
        settings = {k: get(k) for k in SETTING_KEYS}
        if any(v not in (None, False) for v in settings.values()) and verbose:
            print("Settings:")
        cam.apply_settings(**{k: v for k, v in settings.items() if k != "defaults"},
                           defaults=bool(settings["defaults"]), verbose=verbose)
        if mode == "photo":
            cam.start_photo_mode()
        elif mode == "video":
            cam.start_video_mode()
    except BaseException:
        cam.close()
        raise
    return cam


def _shoot(cam, folder, name, log, verbose=True):
    index = next_index(folder, name)
    dest = numbered_path(folder, name, index, cam.photo_suffix)
    t, utc = time.monotonic(), utc_timestamp()
    cam.capture_photo(dest)
    log.add(index, dest, t, utc)
    if verbose:
        print(f"  saved {dest}")
    return dest


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def main_flir_list(cfg=None):
    """Print every connected camera (backend, model, serial)."""
    get = _read_cfg(cfg or {})
    cams = list_cameras(get("backend") or "auto")
    if not cams:
        print("No camera found (or neither Spinnaker/PySpin nor Aravis is installed).")
    for backend, vendor, model, serial in cams:
        print(f"{model:<32} serial {serial:<12} {vendor}  [{backend}]")
    return cams


def main_flir_info(cfg=None):
    """Print the current camera settings with their allowed values / ranges."""
    get = _read_cfg(cfg or {})
    with _connect(get, mode=None) as cam:
        for label, (value, extra) in cam.summary().items():
            v = f"{value:.4g}" if isinstance(value, float) else value
            print(f"{label:<19} {v}")
            if isinstance(extra, (list, tuple)) and extra and isinstance(extra[0], str):
                print(f"{'':<19} choices: {', '.join(extra)}")
            elif isinstance(extra, tuple) and len(extra) == 2:
                print(f"{'':<19} range: {extra[0]:.4g} .. {extra[1]:.4g}")


def main_flir_photo(cfg):
    """Manual photo(s).

    cfg: name; optional input_dir ('input'), output_csv (log path), interactive
    (Enter takes a photo, q + Enter quits), serial, backend, save_format
    (jpg/png/tiff), quality, and the settings shutter, gain, whitebalance,
    wb_red, wb_blue, gamma, black_level, pixel_format, defaults.
    Returns the list of saved files.
    """
    get = _read_cfg(cfg)
    folder = capture_folder(get("name"), get("input_dir") or "input")
    saved, log = [], CaptureLog(get("output_csv"))
    try:
        with _connect(get) as cam:
            if not get("interactive"):
                saved.append(_shoot(cam, folder, get("name"), log))
            else:
                print("Enter = take a photo, q + Enter = quit.")
                while True:
                    try:
                        answer = input("> ").strip().lower()
                    except EOFError:
                        break
                    if answer in ("q", "quit", "exit"):
                        break
                    saved.append(_shoot(cam, folder, get("name"), log))
    finally:
        _report(saved, folder, log)
        log.close()
    return saved


def main_flir_timelapse(cfg):
    """A photo every ``interval`` seconds (count / duration as for the Canon)."""
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
                while time.monotonic() < deadline:
                    time.sleep(min(0.5, deadline - time.monotonic()))
                print(f"[{k + 1}{'/' + str(count) if count else ''}] "
                      f"t = {time.monotonic() - t0:.1f} s")
                saved.append(_shoot(cam, folder, get("name"), log))
                k += 1
    finally:
        _report(saved, folder, log)
        log.close()
    return saved


def main_flir_video(cfg):
    """Record a video straight from the camera stream to <name>_XXXX.mp4.

    cfg: name; optional duration (s; without it recording stops on Enter), fps
    (frame rate; default 10), codec (FourCC, default
    mp4v), input_dir, output_csv and the camera settings. Ctrl+C stops early
    and keeps the video. The video is written with the frame rate the camera
    reported; the real time of every frame is in <log>_frames.csv.
    """
    get0 = _read_cfg(cfg)
    # without a frame rate the camera would run as fast as it can (~95 fps at full size)
    get = lambda k: (get0(k) or DEFAULT_VIDEO_FPS) if k == "fps" else get0(k)
    duration = get("duration")
    if duration is not None and float(duration) <= 0:
        raise ValueError("duration must be > 0 s")
    folder = capture_folder(get("name"), get("input_dir") or "input")
    codec = (get("codec") or "mp4v")[:4]

    saved, log = [], CaptureLog(get("output_csv"))
    frames_path = (log.path.with_name(log.path.stem + "_frames.csv") if log.path else None)
    writer = frames_f = None
    try:
        with _connect(get, mode=None) as cam:
            fps = float(get("fps"))
            resulting = cam.get("AcquisitionResultingFrameRate")
            if resulting and resulting < fps - 1e-3:
                print(f"  note: the exposure limits the frame rate to {resulting:.3g} fps")
                fps = float(resulting)
            index = next_index(folder, get("name"))
            dest = numbered_path(folder, get("name"), index, ".mp4")
            dest.parent.mkdir(parents=True, exist_ok=True)

            stop = threading.Event()
            if not duration:
                threading.Thread(target=lambda: (_wait_enter(), stop.set()),
                                 daemon=True).start()
            cam.start_video_mode()
            log.start()
            t_start, utc_start = log.t0, log.time_stamp
            end = t_start + float(duration) if duration else None
            print(f"Recording at {fps:.3g} fps",
                  f"for {float(duration):g} s ..." if duration else "... press Enter to stop.")
            n, first_ts = 0, None
            try:
                while not stop.is_set() and (end is None or time.monotonic() < end):
                    frame = cam.grab(timeout_s=cam.exposure_s() + 2.0 + 1.0 / fps)
                    t = time.monotonic()
                    img = to_bgr(frame)
                    if img.dtype != "uint8":
                        img = (img >> 8).astype("uint8")
                    if img.ndim == 2:
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    if writer is None:
                        h, w = img.shape[:2]
                        writer = cv2.VideoWriter(str(dest), cv2.VideoWriter_fourcc(*codec),
                                                 fps, (w, h))
                        if not writer.isOpened():
                            raise RuntimeError(f"OpenCV cannot write {codec} video; try "
                                               "--codec MJPG with a .avi, or mp4v")
                    writer.write(img)
                    first_ts = frame.timestamp_ns if first_ts is None else first_ts
                    if frames_path:
                        if frames_f is None:
                            frames_path.parent.mkdir(parents=True, exist_ok=True)
                            frames_f = open(frames_path, "w", newline="", encoding="utf-8")
                            fw = csv.writer(frames_f)
                            fw.writerow(["time_stamp", utc_start])
                            fw.writerow(["frame", "time_s", "camera_time_s", "frame_id"])
                        fw.writerow([n, round(t - t_start, 4),
                                     round((frame.timestamp_ns - first_ts) / 1e9, 6),
                                     frame.frame_id])
                    n += 1
            except KeyboardInterrupt:
                print("\nCtrl+C: stopping early, the video is kept.")
            finally:
                cam.stop()
                if writer is not None:
                    writer.release()
            elapsed = time.monotonic() - t_start
            print(f"Stopped after {elapsed:.1f} s, {n} frames "
                  f"({n / elapsed if elapsed > 0 else 0:.3g} fps measured).")
            if n and elapsed > 2 and n < 0.95 * elapsed * fps:
                print(f"  warning: about {elapsed * fps - n:.0f} frames were dropped "
                      "(the computer could not keep up); use a lower --fps, or see "
                      "the frame times in the _frames.csv log.")
            if n:
                log.add(index, dest, t_start, utc_start)
                saved.append(dest)
                print(f"  saved {dest}")
    finally:
        if frames_f is not None:
            frames_f.close()
            print(f"Frame times: {frames_path}")
        _report(saved, folder, log)
        log.close()
    return saved


def _wait_enter():
    try:
        input()
    except EOFError:
        pass
