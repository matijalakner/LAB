"""DC2200 current ramp with photos from the Canon EOS R10 (or the FLIR
Blackfly S, camera_type="flir") at the same time.

    equipment dc2200 ramp --min 0.05 --max 1 --step 0.05 --step-time 100 --photos mysample

By default one photo is taken in the middle of every step (``photo_delay``,
seconds after the step starts, default step_time / 2), so every photo belongs
to exactly one current. With ``photo_interval`` photos are taken every N
seconds from the ramp start instead, independent of the steps.

The camera works in its own thread: a slow capture or download never delays a
current step. If the camera fails, the ramp is stopped and the LED switched off.

Files:
    input/folder/<name>/<name>_XXXX.jpg      the photos (numbering continues)
    output/ramp/ramp_<UTC>.csv               the ramp, unchanged format
    output/ramp/ramp_<UTC>_photos.csv        one row per photo, same time base:
        time_stamp,<UTC time of the ramp start>     (same line as the ramp CSV)
        time_s, index, file, utc, step, cycle, direction, current_A

``time_s`` counts from the same t = 0 as the ramp CSV, and ``current_A`` is
the current that was set when the photo was taken, so the photos can be
matched to the ramp without relying on the camera clock.
"""
import csv
import threading
import time
from pathlib import Path

from ..thorlabs.dc2200 import _read_cfg as _read_ramp_cfg
from ..thorlabs.dc2200 import main_ramp, ramp_levels, ramp_sequence
from ..utils import utc_timestamp
from ..canon.capture import _connect
from ..capture import capture_folder, next_index, numbered_path

PHOTO_HEADER = ["time_s", "index", "file", "utc", "step", "cycle", "direction", "current_A"]


def photo_log_path(ramp_csv):
    p = Path(ramp_csv)
    return p.with_name(p.stem + "_photos.csv")


def photo_times(n_steps, step_time, photo_delay=None, photo_interval=None):
    """Photo times in seconds from the ramp start."""
    total = n_steps * step_time
    if photo_interval is not None:
        if photo_interval <= 0:
            raise ValueError("photo interval must be > 0 s")
        n = int(total / photo_interval - 1e-9) + 1
        return [round(i * photo_interval, 6) for i in range(n)]
    delay = step_time / 2 if photo_delay is None else float(photo_delay)
    if not 0 <= delay < step_time:
        raise ValueError("photo delay must be >= 0 and shorter than the step time")
    return [round(k * step_time + delay, 6) for k in range(n_steps)]


class RampPhotographer(threading.Thread):
    """Takes the photos at fixed times after the ramp start, in its own thread."""

    def __init__(self, cam, folder, name, sequence, step_time, times, log_path,
                 keep_on_card=False):
        super().__init__(daemon=True, name="camera")
        self.cam, self.folder, self.name = cam, folder, name
        self.sequence, self.step_time, self.times = sequence, step_time, times
        self.log_path, self.keep_on_card = log_path, keep_on_card
        self.stop_event = threading.Event()
        self.error = None
        self.saved = []
        self.t0 = self.time_stamp = None

    def begin(self, t0, time_stamp):
        self.t0, self.time_stamp = t0, time_stamp
        self.start()

    def _wait_until(self, deadline):
        """Wait for the deadline; keep reading camera events so the USB link stays alive."""
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self.cam.drain_events(min(1.0, remaining))
        return False

    def run(self):
        f = None
        try:
            for i, t in enumerate(self.times):
                if not self._wait_until(self.t0 + t):
                    break
                start, utc = time.monotonic(), utc_timestamp()
                late = start - (self.t0 + t)
                if late > 0.5:
                    print(f"  camera: photo {i + 1} is {late:.1f} s late (the previous "
                          "capture took longer than the time between photos)")
                k = min(int((start - self.t0) / self.step_time), len(self.sequence) - 1)
                cycle, direction, current = self.sequence[k]
                index = next_index(self.folder, self.name)
                dest = numbered_path(self.folder, self.name, index,
                                      getattr(self.cam, "photo_suffix", ".jpg"))
                self.cam.capture_photo(dest, keep_on_card=self.keep_on_card)
                self.saved.append(dest)
                if self.log_path:
                    if f is None:
                        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
                        f = open(self.log_path, "w", newline="", encoding="utf-8")
                        w = csv.writer(f)
                        w.writerow(["time_stamp", self.time_stamp])
                        w.writerow(PHOTO_HEADER)
                    w.writerow([round(start - self.t0, 3), index, dest.name, utc,
                                k + 1, cycle, direction, current])
                    f.flush()
                print(f"  camera: [{i + 1}/{len(self.times)}] {dest.name} at "
                      f"{current * 1e3:.2f} mA")
        except Exception as e:          # handed to the ramp thread, which stops the ramp
            self.error = e
        finally:
            if f:
                f.close()

    def check(self):
        if self.error is not None:
            raise RuntimeError(f"camera failed, ramp stopped: {self.error}") from self.error


def main_ramp_camera(cfg):
    """Ramp the DC2200 and take photos at the same time.

    cfg: the ramp settings of main_ramp (i_min, i_max, step, step_time,
    cycles, output_csv) plus camera (the measurement name); optional
    photo_delay or photo_interval, input_dir, keep_on_card, sync_clock and the
    camera settings shutter, iso, whitebalance, colortemperature,
    picturestyle, imageformat. With camera_type 'flir' the FLIR Blackfly S is
    used instead (settings as in flir/capture.py: shutter, gain, whitebalance,
    wb_red, wb_blue, gamma, black_level, pixel_format, serial, backend,
    save_format).

    Returns (ramp rows, list of saved photos).
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k, None))
    p = _read_ramp_cfg(cfg)
    sequence = ramp_sequence(ramp_levels(p["i_min"], p["i_max"], p["step"]), p["cycles"])
    times = photo_times(len(sequence), p["step_time"], get("photo_delay"),
                        get("photo_interval"))
    name = get("camera")
    folder = capture_folder(name, get("input_dir") or "input")
    log_path = photo_log_path(p["output_csv"]) if p["output_csv"] else None

    # Connect the camera first: if it is not there, the LED is never switched on.
    camera_type = (get("camera_type") or "canon").lower()
    if camera_type == "flir":
        from ..flir.capture import _connect as connect_flir
        cam = connect_flir(get)
    elif camera_type == "canon":
        cam = _connect(get)
    else:
        raise ValueError("camera_type must be canon or flir")
    rows, photographer = [], None
    try:
        cam.set_capture_target(card=bool(get("keep_on_card")))
        cam.drain_events(0.5)
        photographer = RampPhotographer(cam, folder, name, sequence, p["step_time"], times,
                                        log_path, keep_on_card=bool(get("keep_on_card")))
        print(f"Camera: {len(times)} photos -> '{folder}/'")
        rows = main_ramp(
            cfg,
            on_start=lambda t0, stamp, seq: photographer.begin(t0, stamp),
            on_step=lambda *a: photographer.check())
        photographer.join(timeout=30)          # the last capture may still be running
        photographer.check()
    finally:
        if photographer is not None and photographer.is_alive():
            photographer.stop_event.set()
            photographer.join(timeout=30)      # let a running capture finish
        cam.close()
        if photographer is not None:
            print(f"{len(photographer.saved)} photos in '{folder}/'.")
            if log_path and Path(log_path).exists() and photographer.saved:
                print(f"Photo log: {log_path}")
    return rows, (photographer.saved if photographer else [])
