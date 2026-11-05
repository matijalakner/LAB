"""Canon EOS R10 over USB, through libgphoto2 (python-gphoto2).

The camera is driven with PTP, the same protocol the Canon EOS Utility uses.
Only the few settings the measurement needs are wrapped here: shutter speed,
ISO, white balance / colour temperature, picture style and the image format.
Every value is checked against the list the camera itself reports, so a value
the camera does not offer gives a clear error with the allowed values.

gphoto2 is imported lazily, so the rest of the package works without it.
"""
import time
from pathlib import Path

from ..utils import match_choice

# gphoto2 config names, first existing one wins (names differ a little between
# libgphoto2 versions and Canon models).
SETTING_NAMES = {
    "shutter": ("shutterspeed", "shutterspeed2"),
    "iso": ("iso",),
    "whitebalance": ("whitebalance",),
    "colortemperature": ("colortemperature",),
    "picturestyle": ("picturestyle",),
    "imageformat": ("imageformat",),
    "capturetarget": ("capturetarget",),
    "movie": ("movie",),
    "viewfinder": ("viewfinder",),
    "syncdatetime": ("syncdatetime",),
    "mode": ("autoexposuremode", "autoexposuremodedial", "expprogram"),
    "battery": ("batterylevel",),
    "model": ("cameramodel", "model"),
}

# What `camera info` prints, in this order.
INFO_SETTINGS = ("model", "battery", "mode", "shutter", "iso", "whitebalance",
                 "colortemperature", "picturestyle", "imageformat", "capturetarget")

JPEG_SUFFIXES = {".jpg", ".jpeg"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi"}


def import_gphoto2():
    try:
        import gphoto2 as gp
    except ImportError as e:
        raise RuntimeError(
            "python-gphoto2 is required for the camera: pip install -e \".[canon]\" "
            "(or: sudo dnf install python3-gphoto2)") from e
    return gp


# ---------------------------------------------------------------------------
# camera
# ---------------------------------------------------------------------------
class CanonCamera:
    """Context manager around one USB-connected Canon EOS camera.

    >>> with CanonCamera() as cam:
    ...     cam.apply_settings(shutter="1/250", iso=200, whitebalance="Daylight")
    ...     cam.capture_photo("data/input/folder/run1/run1_0000.jpg")
    """

    def __init__(self):
        self.gp = import_gphoto2()
        self.camera = None
        self._config = None

    # -- connection ----------------------------------------------------------
    def open(self):
        gp = self.gp
        self.camera = gp.Camera()
        try:
            self.camera.init()
        except gp.GPhoto2Error as e:
            self.camera = None
            raise RuntimeError(_connect_hint(gp, e)) from e
        return self

    def close(self):
        if self.camera is not None:
            try:
                self.camera.exit()
            except Exception:
                pass
            self.camera = None

    def __enter__(self):
        return self if self.camera is not None else self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- config --------------------------------------------------------------
    def _tree(self, refresh=False):
        if self._config is None or refresh:
            self._config = self.camera.get_config()
        return self._config

    def widget(self, key, refresh=False):
        """The gphoto2 widget for a setting key (see SETTING_NAMES), or None."""
        tree = self._tree(refresh)
        for name in SETTING_NAMES.get(key, (key,)):
            try:
                return tree.get_child_by_name(name)
            except self.gp.GPhoto2Error:
                continue
        return None

    def choices(self, key):
        w = self.widget(key)
        if w is None or w.get_type() not in (self.gp.GP_WIDGET_RADIO, self.gp.GP_WIDGET_MENU):
            return []
        return [w.get_choice(i) for i in range(w.count_choices())]

    def get(self, key, refresh=False):
        w = self.widget(key, refresh)
        return None if w is None else w.get_value()

    def set(self, key, value):
        """Set one setting; returns the value the camera now uses."""
        gp = self.gp
        w = self.widget(key, refresh=True)
        if w is None:
            raise RuntimeError(f"this camera has no '{key}' setting")
        if w.get_readonly():
            raise RuntimeError(f"'{key}' cannot be changed in the current camera mode"
                               + _mode_hint(key))
        t = w.get_type()
        if t in (gp.GP_WIDGET_RADIO, gp.GP_WIDGET_MENU):
            chosen = match_choice(value, self.choices(key))
            if not chosen.strip() or chosen.lower() == "unknown value":
                raise ValueError(f"'{value}' is not a valid {key}")
        elif t == gp.GP_WIDGET_RANGE:
            lo, hi, _ = w.get_range()
            chosen = float(value)
            if not lo <= chosen <= hi:
                raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
        elif t == gp.GP_WIDGET_TOGGLE:
            chosen = int(bool(int(value)))
        else:
            chosen = str(value)
        w.set_value(chosen)
        self.camera.set_config(self._tree())
        self.drain_events(0.3)
        return chosen

    def apply_settings(self, shutter=None, iso=None, whitebalance=None,
                       colortemperature=None, picturestyle=None, imageformat=None,
                       verbose=True):
        """Apply the given settings (None = leave as set on the camera).

        A colour temperature without a white balance switches the white
        balance to the camera's colour-temperature mode first.
        """
        if colortemperature is not None and whitebalance is None:
            temp = [c for c in self.choices("whitebalance") if "temp" in c.lower()
                    or c.lower() in ("k", "kelvin")]
            if temp:
                whitebalance = temp[0]
        applied = {}
        for key, value in (("imageformat", imageformat), ("whitebalance", whitebalance),
                           ("colortemperature", colortemperature),
                           ("picturestyle", picturestyle), ("iso", iso), ("shutter", shutter)):
            if value is not None:
                applied[key] = self.set(key, value)
                if verbose:
                    print(f"  {key:<17} = {applied[key]}")
        return applied

    def summary(self):
        """{key: (current value, [choices])} of the settings that exist on the camera."""
        self._tree(refresh=True)
        out = {}
        for key in INFO_SETTINGS:
            w = self.widget(key)
            if w is not None:
                out[key] = (w.get_value(), self.choices(key))
        return out

    def sync_clock(self):
        """Set the camera clock to the computer clock (EXIF times then match the ramp)."""
        if self.widget("syncdatetime") is None:
            raise RuntimeError("this camera cannot sync its clock over USB")
        self.set("syncdatetime", 1)

    def set_capture_target(self, card):
        """Photos to the memory card (card=True) or only to the camera RAM."""
        choices = self.choices("capturetarget")
        if not choices:
            return None
        want = [c for c in choices if ("card" in c.lower()) == card]
        return self.set("capturetarget", want[0] if want else choices[int(card)])

    # -- events and files ------------------------------------------------------
    def drain_events(self, seconds=0.0, until_complete=False):
        """Read camera events for up to ``seconds``; returns the files the camera added.

        Stops early at the first timeout (no more events), or with
        ``until_complete`` at the capture-complete event.
        """
        gp = self.gp
        added = []
        deadline = time.monotonic() + seconds
        while True:
            timeout_ms = max(1, int((deadline - time.monotonic()) * 1000))
            event, data = self.camera.wait_for_event(min(timeout_ms, 1000))
            if event == gp.GP_EVENT_FILE_ADDED:
                added.append((data.folder, data.name))
            elif event == gp.GP_EVENT_CAPTURE_COMPLETE and until_complete:
                break
            elif event == gp.GP_EVENT_TIMEOUT and not until_complete:
                break
            if time.monotonic() >= deadline:
                break
        return added

    def download(self, folder, name, dest):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")     # no half-written file on Ctrl+C
        try:
            f = self.camera.file_get(folder, name, self.gp.GP_FILE_TYPE_NORMAL)
            f.save(str(part))
            part.replace(dest)
        finally:
            part.unlink(missing_ok=True)
        return dest

    def delete(self, folder, name):
        try:
            self.camera.file_delete(folder, name)
        except self.gp.GPhoto2Error:
            pass    # files in camera RAM are gone after the download anyway

    def list_files(self, folder="/"):
        """Every (folder, name) on the camera storage, recursively."""
        out = []
        for name, _ in self.camera.folder_list_files(folder):
            out.append((folder, name))
        for sub, _ in self.camera.folder_list_folders(folder):
            out += self.list_files(folder.rstrip("/") + "/" + sub)
        return out

    # -- capture -------------------------------------------------------------
    def capture_photo(self, dest, keep_on_card=False):
        """Take one photo and save its JPEG as ``dest``. Returns the camera file name.

        With RAW+JPEG only the JPEG is kept. Raises if the camera made no JPEG.
        """
        gp = self.gp
        first = self.camera.capture(gp.GP_CAPTURE_IMAGE)
        files = [(first.folder, first.name)]
        files += [f for f in self.drain_events(2.0) if f not in files]
        jpegs = [f for f in files if Path(f[1]).suffix.lower() in JPEG_SUFFIXES]
        try:
            if not jpegs:
                raise RuntimeError(
                    f"the camera saved {[n for _, n in files]} but no JPEG; set the image "
                    "quality to JPEG on the camera or pass --image-format (see "
                    "'equipment canon info')")
            self.download(*jpegs[0], dest)
        finally:
            if not keep_on_card:
                for f in files:
                    self.delete(*f)
        return jpegs[0][1]

    def start_movie(self):
        if self.widget("movie") is None:
            raise RuntimeError("this camera / libgphoto2 version cannot start a movie over USB")
        if self.widget("viewfinder") is not None:
            try:
                self.set("viewfinder", 1)
            except Exception:
                pass
        try:
            self.set("movie", 1)
        except Exception as e:
            raise RuntimeError(f"could not start recording ({e}). Put the camera's "
                               "photo/movie switch on movie and insert a memory card.") from e

    def stop_movie(self):
        self.set("movie", 0)


def _mode_hint(key):
    if key == "shutter":
        return " (put the mode dial on M or Tv)"
    if key == "iso":
        return " (put the mode dial on M, Av, Tv or P; not on the green auto mode)"
    return ""


def _connect_hint(gp, err):
    text = f"could not connect to the camera: {err}"
    claim = getattr(gp, "GP_ERROR_IO_USB_CLAIM", -53)
    not_found = getattr(gp, "GP_ERROR_MODEL_NOT_FOUND", -105)
    if err.code == claim:
        text += ("\nAnother program holds the camera. On Fedora/GNOME the file manager "
                 "grabs it: run  gio mount -s gphoto2  and  pkill -f gvfs-gphoto2-volume-monitor"
                 "  and try again.")
    elif err.code == not_found:
        text += ("\nNo camera found. Switch the camera on, connect it with a USB data cable, "
                 "and switch Wi-Fi/Bluetooth off on the camera (USB is disabled while they "
                 "are connected). Check with:  gphoto2 --auto-detect")
    return text
