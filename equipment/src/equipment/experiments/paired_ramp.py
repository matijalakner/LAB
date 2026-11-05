"""Stepped ramp of ANY light source, paired with any number of recorders that
measure at the same time: photos (Canon or FLIR) and/or optical power (PM400).

    equipment dc2200 ramp ... --photos mysample                 DC2200 + Canon
    equipment pe300  ramp ... --photos mysample --camera flir   pE-300 + FLIR
    equipment pe300  ramp ... --power                           pE-300 + PM400
    equipment dc2200 ramp ... --photos s1 --camera flir --power DC2200 + FLIR + PM400

Every recorder runs in its own thread on its own schedule, so a slow capture
never delays a step. By default each one measures once per step, in the middle
of the step (``*_delay`` seconds after the step starts, default step_time / 2);
with ``*_interval`` it measures every N seconds from the ramp start instead.

All recorders are connected BEFORE the light: if one is missing, the light is
never switched on. If one fails during the run, the ramp stops and the light
is switched off. Ctrl+C also stops everything; data taken so far is kept.

Files, all with the same t = 0 and time_stamp line as the ramp CSV:
    <ramp>.csv           time_s, cycle, direction, <level column>
    <ramp>_photos.csv    time_s, index, file, utc, step, cycle, direction, <level column>
    <ramp>_power.csv     time_s, power_W, utc, step, cycle, direction, <level column>
    <input_dir>/folder/<name>/<name>_XXXX.jpg     the photos (numbering continues)

``<level column>`` is current_A (DC2200) or intensity_pct (pE-300): the level
that was set when the measurement was taken, independent of any device clock.
"""
import csv
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from ..capture import capture_folder, next_index, numbered_path
from ..ramp import ramp_plan, read_ramp_cfg, run_ramp
from ..sources import make_source, source_class
from ..utils import read_cfg, utc_timestamp


def schedule_times(n_steps, step_time, delay=None, interval=None):
    """Measurement times in seconds from the ramp start."""
    total = n_steps * step_time
    if interval is not None:
        if interval <= 0:
            raise ValueError("interval must be > 0 s")
        n = int(total / interval - 1e-9) + 1
        return [round(i * interval, 6) for i in range(n)]
    delay = step_time / 2 if delay is None else float(delay)
    if not 0 <= delay < step_time:
        raise ValueError("delay must be >= 0 and shorter than the step time")
    return [round(k * step_time + delay, 6) for k in range(n_steps)]


def log_path(ramp_csv, suffix):
    if not ramp_csv:
        return None
    p = Path(ramp_csv)
    return p.with_name(f"{p.stem}_{suffix}.csv")


# ---------------------------------------------------------------------------
# recorders
# ---------------------------------------------------------------------------
class Recorder(threading.Thread):
    """Measures at fixed times after the ramp start, in its own thread.

    Subclasses set ``label`` and ``fields`` and implement ``measure(i)``, which
    returns the values for ``fields`` and a short text for the console.
    """

    label = "recorder"
    fields = ()

    def __init__(self, times, log_path=None):
        super().__init__(daemon=True, name=self.label)
        self.times, self.log_path = times, log_path
        self.stop_event = threading.Event()
        self.error = None
        self.rows = []
        self.t0 = self.time_stamp = None
        self.sequence = self.step_time = self.source = None

    def attach(self, source, sequence, step_time):
        self.source, self.sequence, self.step_time = source, sequence, step_time

    def begin(self, t0, time_stamp):
        self.t0, self.time_stamp = t0, time_stamp
        self.start()

    def idle(self, seconds):
        self.stop_event.wait(seconds)

    def _wait_until(self, deadline):
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self.idle(min(1.0, remaining))
        return False

    def measure(self, i):
        raise NotImplementedError

    def run(self):
        f = w = None
        try:
            for i, t in enumerate(self.times):
                if not self._wait_until(self.t0 + t):
                    break
                start = time.monotonic()
                late = start - (self.t0 + t)
                if late > 0.5:
                    print(f"  {self.label}: measurement {i + 1} is {late:.1f} s late (the "
                          "previous one took longer than the time between them)")
                k = min(int((start - self.t0) / self.step_time), len(self.sequence) - 1)
                cycle, direction, level = self.sequence[k]
                values, text = self.measure(i)
                row = [round(start - self.t0, 3), *values, k + 1, cycle, direction, level]
                self.rows.append(row)
                if self.log_path:
                    if f is None:
                        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
                        f = open(self.log_path, "w", newline="", encoding="utf-8")
                        w = csv.writer(f)
                        w.writerow(["time_stamp", self.time_stamp])
                        w.writerow(["time_s", *self.fields, "step", "cycle", "direction",
                                    self.source.column])
                    w.writerow(row)
                    f.flush()
                print(f"  {self.label}: [{i + 1}/{len(self.times)}] {text} at "
                      f"{self.source.fmt(level)}")
        except Exception as e:          # handed to the ramp thread, which stops the ramp
            self.error = e
        finally:
            if f:
                f.close()

    def check(self):
        if self.error is not None:
            raise RuntimeError(f"{self.label} failed, ramp stopped: {self.error}") \
                from self.error

    def finish(self, timeout=30):
        """Wait for the last measurement; stop the thread if it is still busy."""
        if self.is_alive():
            self.join(timeout=timeout)
        if self.is_alive():
            self.stop_event.set()
            self.join(timeout=timeout)


class PhotoRecorder(Recorder):
    label = "camera"
    fields = ("index", "file", "utc")

    def __init__(self, cam, folder, name, times, log_path=None, keep_on_card=False):
        super().__init__(times, log_path)
        self.cam, self.folder, self.name = cam, folder, name
        self.keep_on_card = keep_on_card
        self.saved = []

    def idle(self, seconds):                  # keep reading camera events (USB link)
        if self.stop_event.is_set():
            return
        self.cam.drain_events(seconds)

    def measure(self, i):
        utc = utc_timestamp()
        index = next_index(self.folder, self.name)
        dest = numbered_path(self.folder, self.name, index,
                             getattr(self.cam, "photo_suffix", ".jpg"))
        self.cam.capture_photo(dest, keep_on_card=self.keep_on_card)
        self.saved.append(dest)
        return [index, dest.name, utc], dest.name


class PowerRecorder(Recorder):
    label = "PM400"
    fields = ("power_W", "utc")

    def __init__(self, meter, times, log_path=None):
        super().__init__(times, log_path)
        self.meter = meter

    def measure(self, i):
        utc = utc_timestamp()
        power = self.meter.read_power()
        return [power, utc], f"{power * 1e3:.4f} mW"


# ---------------------------------------------------------------------------
# connecting the paired instruments
# ---------------------------------------------------------------------------
def _connect_canon(get):
    from ..canon.capture import _connect
    return _connect(get)


def _connect_flir(get):
    from ..flir.capture import _connect
    return _connect(get)


def _open_power_meter(get):
    from ..thorlabs.pm400 import open_pm400
    return open_pm400(get("pm400_serial"), get("wavelength") or 450.0,
                      get("averaging_count") or 10)


def connect_camera(get, stack):
    """Open the camera named by camera_type (canon/flir); closed by ``stack``."""
    camera_type = (get("camera_type") or "canon").lower()
    if camera_type == "canon":
        cam = _connect_canon(get)
    elif camera_type == "flir":
        cam = _connect_flir(get)
    else:
        raise ValueError("camera_type must be canon or flir")
    stack.callback(cam.close)
    cam.set_capture_target(card=bool(get("keep_on_card")))
    cam.drain_events(0.5)
    return cam


def main_paired_ramp(cfg):
    """Ramp a light source with photos and/or power readings at the same time.

    cfg:
      source         'dc2200' (default) or 'pe300', with its settings
                     (dc2200_serial; port, channels)
      ramp           min/max (or i_min/i_max), step, step_time, cycles, output_csv
      photos         camera = measurement name (photo folder), camera_type
                     ('canon' or 'flir'), photo_delay or photo_interval,
                     input_dir, keep_on_card and the camera settings (see
                     canon/capture.py and flir/capture.py)
      power          power = True, power_delay or power_interval, wavelength,
                     averaging_count, pm400_serial

    Returns {'rows': ramp rows, 'photos': [saved files], 'power': [power rows]}.
    """
    get = read_cfg(cfg)
    key = get("source") or "dc2200"
    p = read_ramp_cfg(cfg, source_class(key))
    source = make_source(key, cfg)                 # not connected yet
    sequence = ramp_plan(p, source)
    n, st = len(sequence), p["step_time"]
    want_photos, want_power = bool(get("camera")), bool(get("power"))
    if not (want_photos or want_power):
        raise ValueError("nothing to pair: give camera (photos) and/or power")
    photo_times = schedule_times(n, st, get("photo_delay"), get("photo_interval")) \
        if want_photos else []
    power_times = schedule_times(n, st, get("power_delay"), get("power_interval")) \
        if want_power else []
    folder = capture_folder(get("camera"), get("input_dir")) if want_photos \
        else None

    recorders, photos, power = [], None, None
    rows = []
    with ExitStack() as stack:
        # 1. the paired instruments first: if one is missing the light stays off
        if want_photos:
            cam = connect_camera(get, stack)
            photos = PhotoRecorder(cam, folder, get("camera"), photo_times,
                                   log_path(p["output_csv"], "photos"),
                                   keep_on_card=bool(get("keep_on_card")))
            recorders.append(photos)
            print(f"Camera: {len(photo_times)} photos -> '{folder}/'")
        if want_power:
            meter = stack.enter_context(_open_power_meter(get))
            power = PowerRecorder(meter, power_times, log_path(p["output_csv"], "power"))
            recorders.append(power)
            print(f"PM400: {len(power_times)} readings")
        # 2. on leaving: first signal the recorders to stop, then wait for them, then
        #    close the instruments (ExitStack runs callbacks last-in, first-out)
        stack.callback(lambda: [r.join(timeout=30) for r in recorders if r.is_alive()])
        stack.callback(lambda: [r.stop_event.set() for r in recorders])
        for r in recorders:
            r.attach(source, sequence, st)

        def on_start(t0, stamp, seq):
            for r in recorders:
                r.begin(t0, stamp)

        def on_step(*args):
            for r in recorders:
                r.check()

        # 3. the light, switched off when this block is left
        with source:
            rows = run_ramp(source, cfg, on_start=on_start, on_step=on_step)
        for r in recorders:
            r.finish()
            r.check()

    if photos is not None:
        print(f"{len(photos.saved)} photos in '{folder}/'.")
        if photos.saved and photos.log_path:
            print(f"Photo log: {photos.log_path}")
    if power is not None and power.rows and power.log_path:
        print(f"Power log: {power.log_path}")
    return {"rows": rows, "photos": photos.saved if photos else [],
            "power": power.rows if power else []}
