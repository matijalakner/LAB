"""Teledyne FLIR Blackfly S (BFS-U3-27S5C-C, Sony IMX429, colour) over USB3 Vision.

The camera is a machine-vision camera, not a photo camera: it has no memory
card, no clock and no JPEG engine. It streams raw frames and is controlled by
GenICam features (ExposureTime in us, Gain in dB, ...). This class gives it
the same shape as CanonCamera:

    >>> with FlirCamera() as cam:
    ...     cam.apply_settings(shutter="1/250", gain=0, whitebalance="off")
    ...     cam.capture_photo("input/folder/run1/run1_0000.jpg")

* Photos are taken with a software trigger, so every photo is a fresh
  exposure started at the moment of the capture (no old frame from a buffer).
* The computer clock is written into the EXIF (DateTimeOriginal + ms, and the
  exposure time), so ``analysis folder`` orders the photos like Canon photos.
* Colour: BGR8 (debayered in the camera) is used if the camera offers it,
  otherwise Bayer frames are debayered with OpenCV.

The backend (Spinnaker/PySpin or Aravis) is chosen in backends.py.
"""
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..utils import match_choice
from .backends import _bytes_per_pixel, list_cameras, open_backend

PHOTO_SUFFIXES = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".tif": "tiff",
                  ".tiff": "tiff"}
# preferred pixel formats when none is given (first one the camera offers)
DEFAULT_FORMATS = ("BGR8", "RGB8", "RGB8Packed", "BayerRG8", "Mono8")

# (label, GenICam feature) shown by `flir info`
INFO_FEATURES = (
    ("model", "DeviceModelName"), ("serial", "DeviceSerialNumber"),
    ("firmware", "DeviceFirmwareVersion"), ("temperature (C)", "DeviceTemperature"),
    ("link speed", "DeviceLinkSpeed"), ("width", "Width"), ("height", "Height"),
    ("pixel format", "PixelFormat"), ("exposure auto", "ExposureAuto"),
    ("exposure (us)", "ExposureTime"), ("gain auto", "GainAuto"), ("gain (dB)", "Gain"),
    ("white balance", "BalanceWhiteAuto"), ("gamma enable", "GammaEnable"),
    ("gamma", "Gamma"), ("black level", "BlackLevel"),
    ("frame rate enable", "AcquisitionFrameRateEnable"),
    ("frame rate (fps)", "AcquisitionFrameRate"),
    ("resulting fps", "AcquisitionResultingFrameRate"),
)


# ---------------------------------------------------------------------------
# value parsing
# ---------------------------------------------------------------------------
AUTO_WORDS = {"auto": "Continuous", "continuous": "Continuous", "once": "Once",
              "off": "Off", "manual": "Off"}


def _num(text):
    s = str(text).strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return float(a) / float(b)
    return float(s)


def parse_exposure_us(value):
    """'1/250' or '0.004' or '4ms' or '4000us' -> 4000.0 (us); 'auto' -> 'Continuous'.

    A plain number or fraction is seconds, as for the Canon --shutter.
    """
    s = str(value).strip().lower().replace("µ", "u").rstrip('"').strip()
    if s in AUTO_WORDS and s not in ("off", "manual"):
        return AUTO_WORDS[s]
    try:
        for suffix, factor in (("us", 1.0), ("ms", 1e3), ("s", 1e6)):
            if s.endswith(suffix):
                return _num(s[:-len(suffix)]) * factor
        return _num(s) * 1e6
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"exposure '{value}' not understood; use e.g. 1/250, 0.004, "
                         "4ms, 4000us or auto") from None


def _auto_or_number(value, what):
    s = str(value).strip().lower()
    if s in AUTO_WORDS:
        return AUTO_WORDS[s]
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"{what} '{value}' not understood; use a number, auto, "
                         "once or off") from None


# ---------------------------------------------------------------------------
# image conversion
# ---------------------------------------------------------------------------
def _bayer_code(pattern, depth16=False):
    # OpenCV names the Bayer codes after a different pixel than GenICam does;
    # the *RGGB* style aliases (OpenCV >= 4.5) name them like GenICam.
    alias = {"RG": "RGGB", "GR": "GRBG", "GB": "GBRG", "BG": "BGGR"}[pattern]
    legacy = {"RG": "BG", "GR": "GB", "GB": "GR", "BG": "RG"}[pattern]
    return getattr(cv2, f"COLOR_Bayer{alias}2BGR", None) or \
        getattr(cv2, f"COLOR_Bayer{legacy}2BGR")


def to_bgr(frame):
    """Frame from the camera -> OpenCV image (BGR, or 2-D for mono)."""
    pf, data = frame.pixel_format, frame.data
    low = pf.lower()
    if low.startswith("bgr"):
        return data
    if low.startswith("rgb"):
        return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
    if low.startswith("bayer"):
        return cv2.cvtColor(data, _bayer_code(pf[5:7].upper()))
    if low.startswith("mono"):
        return data
    raise RuntimeError(f"pixel format {pf} cannot be converted")


def save_image(img, dest, exif=None, quality=95):
    """Save ``img`` (BGR or mono, uint8 or uint16) as JPEG/PNG/TIFF by suffix.

    8-bit images are written with Pillow so the EXIF (capture time) goes in;
    16-bit images go through OpenCV (PNG/TIFF only), without EXIF.
    """
    from PIL import Image

    dest = Path(dest)
    fmt = PHOTO_SUFFIXES.get(dest.suffix.lower())
    if fmt is None:
        raise ValueError(f"cannot save '{dest.suffix}'; use .jpg, .png or .tif")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part" + dest.suffix)   # no half file on Ctrl+C
    try:
        if img.dtype != np.uint8:
            if fmt == "jpg":
                raise ValueError("a 16-bit pixel format cannot be saved as JPEG; use "
                                 "--save-format png or tiff, or an 8-bit pixel format")
            if not cv2.imwrite(str(part), img):
                raise RuntimeError(f"could not write {dest}")
        else:
            pil = Image.fromarray(img[:, :, ::-1] if img.ndim == 3 else img)
            kwargs = {"exif": exif} if exif is not None else {}
            if fmt == "jpg":
                kwargs.update(quality=int(quality), subsampling=0)
            pil.save(part, format={"jpg": "JPEG", "png": "PNG", "tiff": "TIFF"}[fmt],
                     **kwargs)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


def make_exif(when, model="", serial="", exposure_us=None, gain_db=None, description=""):
    from PIL import Image, TiffImagePlugin

    exif = Image.Exif()
    stamp = when.strftime("%Y:%m:%d %H:%M:%S")
    exif[0x010F] = "Teledyne FLIR"                          # Make
    exif[0x0110] = model or "Blackfly S"                    # Model
    exif[0x0132] = stamp                                    # DateTime
    if description:
        exif[0x010E] = description                          # ImageDescription
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = stamp                                     # DateTimeOriginal
    sub[0x9291] = f"{when.microsecond // 1000:03d}"         # SubSecTimeOriginal
    off = when.strftime("%z")
    if off:
        sub[0x9011] = f"{off[:3]}:{off[3:]}"                # OffsetTimeOriginal
    if serial:
        sub[0xA431] = str(serial)                           # BodySerialNumber
    if exposure_us:
        sub[0x829A] = TiffImagePlugin.IFDRational(int(round(exposure_us)), 1_000_000)
    return exif


# ---------------------------------------------------------------------------
# camera
# ---------------------------------------------------------------------------
class FlirCamera:
    """Context manager around one Blackfly S (or any USB3 Vision / GenICam camera)."""

    def __init__(self, serial=None, backend="auto", save_format="jpg", quality=95):
        self.serial_wanted = serial
        self.backend_name = backend
        self.dev = None
        self.mode = None            # None, "photo" or "video"
        self.save_format = save_format
        self.quality = quality

    # -- connection ------------------------------------------------------------
    def open(self):
        self.dev = open_backend(self.backend_name, self.serial_wanted)
        return self

    def close(self):
        if self.dev is not None:
            try:
                self.stop()
            finally:
                self.dev.close()
                self.dev = None

    def __enter__(self):
        return self if self.dev is not None else self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    @property
    def model(self):
        return self.dev.model

    @property
    def serial(self):
        return self.dev.serial

    @property
    def backend(self):
        return self.dev.name

    @property
    def photo_suffix(self):
        return {"jpg": ".jpg", "png": ".png", "tiff": ".tif"}[self.save_format]

    # -- features --------------------------------------------------------------
    def has(self, name):
        return self.dev.kind(name) is not None

    def get(self, name):
        return self.dev.get(name)

    def choices(self, name):
        return self.dev.choices(name)

    def set(self, name, value):
        """Set one GenICam feature, checked against what the camera allows.

        Enumerations accept any unique part of the name, case-insensitive
        ('off' -> 'Off', 'bayerrg8' -> 'BayerRG8'). Numbers are checked against
        the current range. Returns the value the camera now reports.
        """
        kind = self.dev.kind(name)
        if kind is None:
            raise RuntimeError(f"this camera has no '{name}' setting")
        if not self.dev.writable(name):
            raise RuntimeError(f"'{name}' cannot be changed now" + _lock_hint(name))
        if kind == "enum":
            value = match_choice(value, self.dev.choices(name))
        elif kind in ("float", "int"):
            value = float(value) if kind == "float" else int(round(float(value)))
            b = self.dev.bounds(name)
            if b and not b[0] - 1e-9 <= value <= b[1] + 1e-9:
                raise ValueError(f"{name} = {value:g} is outside the allowed range "
                                 f"{b[0]:g} .. {b[1]:g}" + _range_hint(name))
        elif kind == "bool":
            value = value if isinstance(value, bool) else \
                str(value).strip().lower() in ("1", "true", "on", "yes")
        self.dev.set(name, value)
        return self.dev.get(name)

    def _try_set(self, name, value):
        """Set a feature if the camera has it and it can be changed; never raises."""
        if self.has(name) and self.dev.writable(name):
            try:
                self.dev.set(name, value)
                return True
            except (RuntimeError, ValueError):
                pass
        return False

    def load_defaults(self):
        """Load the factory default user set (all settings back to the defaults)."""
        self.stop()
        self.set("UserSetSelector", "Default")
        self.dev.execute("UserSetLoad")

    def apply_settings(self, shutter=None, gain=None, whitebalance=None, wb_red=None,
                       wb_blue=None, gamma=None, black_level=None, pixel_format=None,
                       fps=None, defaults=False, verbose=True):
        """Apply the given settings (None = leave as set on the camera).

        shutter: exposure, '1/250' / 0.004 (s), '4ms', '4000us' or 'auto'/'once'
        gain: dB, or 'auto'/'once'
        whitebalance: 'auto' (continuous), 'once' or 'off'; wb_red / wb_blue set
            the red and blue ratios (green = 1) and switch the automatic off
        gamma: a number, or 'off'
        black_level: in % on the Blackfly S
        pixel_format: e.g. BGR8, BayerRG8, BayerRG16, Mono8. Without it the
            first of BGR8 / RGB8 / BayerRG8 / Mono8 the camera offers is used
            if the current format cannot be saved.
        fps: frame rate for video; without it the frame-rate limit is switched
            off so long exposures work.
        """
        self.stop()                                 # most settings are locked while streaming
        applied = {}

        def note(key, value):
            applied[key] = value
            if verbose:
                print(f"  {key:<17} = {value:g}" if isinstance(value, float)
                      else f"  {key:<17} = {value}")

        if defaults:
            self.load_defaults()
            note("defaults", "factory defaults loaded")

        # trigger off while changing the format / exposure
        self._try_set("TriggerMode", "Off")

        if pixel_format is not None:
            note("pixel_format", self.set("PixelFormat", pixel_format))
        elif not _usable_format(self.get("PixelFormat")):
            offered = self.choices("PixelFormat")
            for pf in DEFAULT_FORMATS:
                if pf in offered:
                    note("pixel_format", self.set("PixelFormat", pf))
                    break

        if fps is None:
            self._try_set("AcquisitionFrameRateEnable", False)   # long exposures possible

        if shutter is not None:
            us = parse_exposure_us(shutter)
            if isinstance(us, str):
                note("exposure_auto", self.set("ExposureAuto", us))
            else:
                self._try_set("ExposureAuto", "Off")
                note("exposure_us", self.set("ExposureTime", us))

        if gain is not None:
            g = _auto_or_number(gain, "gain")
            if isinstance(g, str):
                note("gain_auto", self.set("GainAuto", g))
            else:
                self._try_set("GainAuto", "Off")
                note("gain_db", self.set("Gain", g))

        if wb_red is not None or wb_blue is not None:
            self._try_set("BalanceWhiteAuto", "Off")
            for sel, val in (("Red", wb_red), ("Blue", wb_blue)):
                if val is not None:
                    self.set("BalanceRatioSelector", sel)
                    note(f"wb_{sel.lower()}", self.set("BalanceRatio", float(val)))
        if whitebalance is not None:
            wb = AUTO_WORDS.get(str(whitebalance).strip().lower(), whitebalance)
            note("whitebalance", self.set("BalanceWhiteAuto", wb))

        if gamma is not None:
            if str(gamma).strip().lower() in ("off", "none", "0"):
                note("gamma", "off" if self._try_set("GammaEnable", False) else "n/a")
            else:
                self._try_set("GammaEnable", True)
                note("gamma", self.set("Gamma", float(gamma)))

        if black_level is not None:
            note("black_level", self.set("BlackLevel", float(black_level)))

        if fps is not None:
            self._try_set("AcquisitionFrameRateEnable", True)
            note("fps", self.set("AcquisitionFrameRate", float(fps)))
        return applied

    def summary(self):
        """{label: (value, choices or (min, max) or None)} for `flir info`."""
        out = {}
        for label, name in INFO_FEATURES:
            kind = self.dev.kind(name)
            if kind is None:
                continue
            extra = self.dev.choices(name) if kind == "enum" else \
                self.dev.bounds(name) if kind in ("float", "int") else None
            out[label] = (self.get(name), extra)
        if self.has("BalanceRatioSelector"):
            for sel in ("Red", "Blue"):
                if self._try_set("BalanceRatioSelector", sel):
                    out[f"wb ratio {sel.lower()}"] = (self.get("BalanceRatio"),
                                                      self.dev.bounds("BalanceRatio"))
        return out

    # -- acquisition -----------------------------------------------------------
    def exposure_s(self):
        us = self.get("ExposureTime")
        return (us or 0) / 1e6

    def start_photo_mode(self):
        """Software-triggered acquisition: one fresh exposure per capture_photo()."""
        if self.mode == "photo":
            return
        self.stop()
        self._try_set("AcquisitionMode", "Continuous")
        self._try_set("TriggerMode", "Off")              # source can only change while off
        self._try_set("TriggerSelector", "FrameStart")
        if not self._try_set("TriggerSource", "Software"):
            raise RuntimeError("the camera does not offer a software trigger")
        self._try_set("TriggerActivation", "RisingEdge")
        self._try_set("TriggerOverlap", "Off")
        self.set("TriggerMode", "On")
        self.dev.start(buffers=5, newest_only=True)
        self.mode = "photo"

    def start_video_mode(self, buffers=60):
        """Free-running acquisition at the set frame rate, every frame kept."""
        if self.mode == "video":
            return
        self.stop()
        self._try_set("AcquisitionMode", "Continuous")
        self._try_set("TriggerMode", "Off")
        self.dev.start(buffers=buffers, newest_only=False)
        self.mode = "video"

    def start_live_mode(self, buffers=4):
        """Free-running acquisition that always hands out the NEWEST frame (preview)."""
        if self.mode == "live":
            return
        self.stop()
        self._try_set("AcquisitionMode", "Continuous")
        self._try_set("TriggerMode", "Off")
        self.dev.start(buffers=buffers, newest_only=True)
        self.mode = "live"

    def set_live(self, name, value):
        """Change a feature while streaming (ExposureTime and Gain can be); if the
        camera refuses, restart the stream around the change. Returns the value read back."""
        try:
            self.set(name, value)
        except (RuntimeError, ValueError):
            mode = self.mode
            self.stop()
            self.set(name, value)
            if mode == "live":
                self.start_live_mode()
        return self.get(name)

    def stop(self):
        if self.dev is not None and self.mode is not None:
            self.dev.stop()
        self.mode = None

    def grab(self, timeout_s=None):
        """Next frame of the running acquisition (see start_*_mode)."""
        if timeout_s is None:
            timeout_s = self.exposure_s() + 5.0
        return self.dev.grab(timeout_s)

    def trigger_frame(self):
        """Take one fresh frame with the software trigger; returns (Frame, local time)."""
        self.start_photo_mode()
        self.dev.flush()
        when = datetime.now().astimezone()
        self.dev.execute("TriggerSoftware")
        return self.grab(), when

    def capture_photo(self, dest, keep_on_card=False):
        """Take one photo and save it as ``dest`` (.jpg, .png or .tif by suffix).

        ``keep_on_card`` is accepted for the same call as CanonCamera and ignored
        (the camera has no card). Returns the saved file name.
        """
        frame, when = self.trigger_frame()
        img = to_bgr(frame)
        exp, gain = self.get("ExposureTime"), self.get("Gain")
        desc = (f"{self.model} SN {self.serial}; exposure {exp:.0f} us; gain {gain:.2f} dB; "
                f"{frame.pixel_format}" if exp is not None and gain is not None else "")
        exif = make_exif(when, self.model, self.serial, exp, gain, desc)
        save_image(img, dest, exif=exif, quality=self.quality)
        return Path(dest).name

    # -- same calls as CanonCamera, so the ramp/timelapse code can use either -----
    def drain_events(self, seconds=0.0, until_complete=False):
        """The FLIR camera has no events to read; just waits ``seconds``."""
        if seconds > 0:
            time.sleep(seconds)
        return []

    def set_capture_target(self, card):
        return None

    def sync_clock(self):
        """Nothing to do: the time stamps come from the computer clock."""
        return None


def _usable_format(pixel_format):
    try:
        _bytes_per_pixel(str(pixel_format or ""))
        return True
    except RuntimeError:
        return False


def _lock_hint(name):
    if name in ("ExposureTime",):
        return " (ExposureAuto must be Off; this is done automatically with --shutter)"
    if name in ("Gain",):
        return " (GainAuto must be Off)"
    if name in ("PixelFormat", "Width", "Height"):
        return " (not while the camera is streaming)"
    if name == "AcquisitionFrameRate":
        return " (AcquisitionFrameRateEnable must be on)"
    return ""


def _range_hint(name):
    if name == "ExposureTime":
        return " us; a long exposure also needs a low enough --fps (or no --fps)"
    if name == "AcquisitionFrameRate":
        return " fps; the maximum depends on the exposure time"
    return ""


__all__ = ["FlirCamera", "list_cameras", "parse_exposure_us", "to_bgr", "save_image"]
