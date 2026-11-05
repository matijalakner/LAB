"""Two ways to talk to a USB3 Vision (GenICam) camera such as the Blackfly S.

* ``spinnaker``: Teledyne FLIR's own Spinnaker SDK with its Python wrapper
  PySpin (``import PySpin``). Official, best tested, needs the SDK installed.
* ``aravis``: the open-source Aravis library through GObject introspection
  (``gi.require_version("Aravis", "0.8")``). Easy on Fedora / any Linux.

Both expose the camera's GenICam features under the same names
(ExposureTime, Gain, PixelFormat, ...), so ``FlirCamera`` works on a small
common interface:

    kind(name) get(name) set(name, value) choices(name) bounds(name)
    writable(name) execute(name) start(...) stop() grab(timeout) flush() close()

Both libraries are imported lazily, so the package works without them.
"""
import sys
from dataclasses import dataclass

import numpy as np


SPINNAKER_HINT = ("Spinnaker: install the Spinnaker SDK from teledynevisionsolutions.com and "
                  "the matching PySpin wheel (pip install spinnaker_python-...whl)")
if sys.platform.startswith("win"):
    # Aravis is not available on Windows: Spinnaker is the only option there
    ARAVIS_HINT = ("Aravis is not available on Windows; use Spinnaker (install the SDK, "
                   "then run install.bat in LAB)")
elif sys.platform == "darwin":
    ARAVIS_HINT = ("Aravis: run ./install.sh in LAB (brew install aravis pygobject3, and an "
                   "environment made with Homebrew's Python and --system-site-packages)")
else:
    ARAVIS_HINT = ("Aravis: run ./install.sh in LAB (Fedora: builds Aravis 0.8; Ubuntu: "
                   "apt install gir1.2-aravis-0.8), with an environment made with "
                   "--system-site-packages")


@dataclass
class Frame:
    """One image as it came from the camera (no colour conversion yet)."""
    data: np.ndarray            # (h, w) or (h, w, channels), uint8 / uint16
    pixel_format: str           # GenICam name, e.g. BGR8, BayerRG8, Mono16
    timestamp_ns: int           # camera clock, only good for differences
    frame_id: int


def _bytes_per_pixel(pixel_format):
    pf = pixel_format.lower()
    packed = pf.endswith("p") or ("packed" in pf and not pf.startswith(("rgb8", "bgr8")))
    if packed or not pf.startswith(("mono", "bayer", "rgb", "bgr")):
        raise RuntimeError(f"pixel format {pixel_format} is not supported here; use BGR8, "
                           "RGB8, BayerRG8, BayerRG16, Mono8 or Mono16 (--pixel-format)")
    depth = 2 if "16" in pf or "12" in pf or "10" in pf else 1
    channels = 3 if pf.startswith(("rgb", "bgr")) else 1
    return depth, channels


def frame_from_bytes(buf, width, height, pixel_format, timestamp_ns=0, frame_id=0):
    depth, channels = _bytes_per_pixel(pixel_format)
    arr = np.frombuffer(buf, dtype=np.uint16 if depth == 2 else np.uint8)
    need = width * height * channels
    if arr.size < need:
        raise RuntimeError(f"incomplete image: {arr.size} of {need} values")
    arr = arr[:need].reshape((height, width, channels) if channels > 1 else (height, width))
    return Frame(arr.copy(), pixel_format, int(timestamp_ns), int(frame_id))


def open_backend(backend="auto", serial=None):
    """Open the camera (first one, or the one with ``serial``) with the chosen backend."""
    backend = (backend or "auto").lower()
    if backend not in ("auto", "spinnaker", "aravis"):
        raise ValueError("backend must be auto, spinnaker or aravis")
    errors = []
    for name, cls in (("spinnaker", SpinnakerBackend), ("aravis", AravisBackend)):
        if backend not in ("auto", name):
            continue
        try:
            cls.load()
        except ImportError as e:
            errors.append(f"{name}: not installed ({e})")
            continue
        return cls(serial)       # a real connection error is raised, not hidden
    raise RuntimeError("no library for the FLIR camera is installed:\n  "
                       + "\n  ".join(errors) + f"\nInstall one of them.\n  {SPINNAKER_HINT}"
                       f"\n  {ARAVIS_HINT}")


def list_cameras(backend="auto"):
    """[(backend, vendor, model, serial)] of every camera the installed libraries see."""
    out = []
    for name, cls in (("spinnaker", SpinnakerBackend), ("aravis", AravisBackend)):
        if backend not in ("auto", name):
            continue
        try:
            cls.load()
        except ImportError:
            continue
        out += [(name, *d) for d in cls.list()]
        if out and backend == "auto":
            break       # both see the same cameras; one list is enough
    return out


def _no_camera(serial, found, hint):
    want = f"with serial {serial}" if serial else "connected"
    text = f"no FLIR camera {want} was found"
    if found:
        text += "; found: " + ", ".join(f"{m} (serial {s})" for _, m, s in found)
    return text + "\n" + hint


USB_HINT = ("Check the USB3 cable (blue port, the camera LED is green when it is "
            "powered), the udev rule / USB permissions, and that SpinView or another "
            "program is not holding the camera.")


# ===========================================================================
# Spinnaker / PySpin
# ===========================================================================
class SpinnakerBackend:
    name = "spinnaker"
    PySpin = None

    @classmethod
    def load(cls):
        if cls.PySpin is None:
            import PySpin
            cls.PySpin = PySpin
        return cls.PySpin

    @classmethod
    def list(cls):
        ps = cls.load()
        system = ps.System.GetInstance()
        cams = system.GetCameras()
        out = []
        try:
            for i in range(cams.GetSize()):
                tl = cams.GetByIndex(i).GetTLDeviceNodeMap()
                out.append(tuple(cls._tl_value(ps, tl, n) for n in
                                 ("DeviceVendorName", "DeviceModelName", "DeviceSerialNumber")))
        finally:
            cams.Clear()
            system.ReleaseInstance()
        return out

    @staticmethod
    def _tl_value(ps, nodemap, name):
        node = nodemap.GetNode(name)
        if node is None or not ps.IsReadable(node):
            return ""
        return ps.CValuePtr(node).ToString()

    def __init__(self, serial=None):
        ps = self.load()
        self.system = ps.System.GetInstance()
        self.cam_list = self.system.GetCameras()
        self.cam = None
        self.streaming = False
        try:
            if self.cam_list.GetSize() == 0:
                raise RuntimeError(_no_camera(serial, [], USB_HINT))
            if serial:
                cam = self.cam_list.GetBySerial(str(serial))
                if cam is None or not cam.IsValid():
                    raise RuntimeError(_no_camera(serial, self.list_open(), USB_HINT))
            else:
                cam = self.cam_list.GetByIndex(0)
            cam.Init()
            self.cam = cam
            self.nodemap = cam.GetNodeMap()
            self.stream_nodemap = cam.GetTLStreamNodeMap()
            tl = cam.GetTLDeviceNodeMap()
            self.vendor = self._tl_value(ps, tl, "DeviceVendorName")
            self.model = self._tl_value(ps, tl, "DeviceModelName")
            self.serial = self._tl_value(ps, tl, "DeviceSerialNumber")
        except ps.SpinnakerException as e:
            self.close()
            raise RuntimeError(f"could not open the camera: {e}\n{USB_HINT}") from e
        except BaseException:
            self.close()
            raise

    def list_open(self):
        ps = self.PySpin
        out = []
        for i in range(self.cam_list.GetSize()):
            tl = self.cam_list.GetByIndex(i).GetTLDeviceNodeMap()
            out.append((self._tl_value(ps, tl, "DeviceVendorName"),
                        self._tl_value(ps, tl, "DeviceModelName"),
                        self._tl_value(ps, tl, "DeviceSerialNumber")))
        return out

    def close(self):
        try:
            if self.cam is not None:
                if self.streaming:
                    self.stop()
                self.cam.DeInit()
        except Exception:
            pass
        self.cam = self.nodemap = self.stream_nodemap = None    # release before the system
        if getattr(self, "cam_list", None) is not None:
            self.cam_list.Clear()
            self.cam_list = None
        if getattr(self, "system", None) is not None:
            try:
                self.system.ReleaseInstance()
            except Exception:
                pass
            self.system = None

    # -- nodes -----------------------------------------------------------------
    def _node(self, name, stream=False):
        ps = self.PySpin
        nodemap = self.stream_nodemap if stream else self.nodemap
        node = nodemap.GetNode(name) if nodemap is not None else None
        if node is None or not ps.IsAvailable(node):
            return None
        return node

    def kind(self, name, stream=False):
        ps = self.PySpin
        node = self._node(name, stream)
        if node is None:
            return None
        return {ps.intfIEnumeration: "enum", ps.intfIFloat: "float",
                ps.intfIInteger: "int", ps.intfIBoolean: "bool",
                ps.intfICommand: "command", ps.intfIString: "string"
                }.get(node.GetPrincipalInterfaceType(), "other")

    def writable(self, name, stream=False):
        node = self._node(name, stream)
        return node is not None and self.PySpin.IsWritable(node)

    def get(self, name, stream=False):
        ps = self.PySpin
        node = self._node(name, stream)
        if node is None or not ps.IsReadable(node):
            return None
        k = self.kind(name, stream)
        try:
            if k == "enum":
                return ps.CEnumerationPtr(node).GetCurrentEntry().GetSymbolic()
            if k == "float":
                return ps.CFloatPtr(node).GetValue()
            if k == "int":
                return ps.CIntegerPtr(node).GetValue()
            if k == "bool":
                return bool(ps.CBooleanPtr(node).GetValue())
            return ps.CValuePtr(node).ToString()
        except ps.SpinnakerException:
            return None

    def set(self, name, value, stream=False):
        ps = self.PySpin
        node = self._node(name, stream)
        k = self.kind(name, stream)
        try:
            if k == "enum":
                e = ps.CEnumerationPtr(node)
                entry = e.GetEntryByName(str(value))
                if entry is None or not ps.IsReadable(entry):
                    raise ValueError(f"{name} has no entry '{value}'")
                e.SetIntValue(entry.GetValue())
            elif k == "float":
                ps.CFloatPtr(node).SetValue(float(value))
            elif k == "int":
                ps.CIntegerPtr(node).SetValue(int(value))
            elif k == "bool":
                ps.CBooleanPtr(node).SetValue(bool(value))
            else:
                ps.CValuePtr(node).FromString(str(value))
        except ps.SpinnakerException as e:
            raise RuntimeError(f"could not set {name} = {value}: {e}") from e

    def choices(self, name, stream=False):
        ps = self.PySpin
        node = self._node(name, stream)
        if node is None or self.kind(name, stream) != "enum":
            return []
        out = []
        for entry in ps.CEnumerationPtr(node).GetEntries():
            if ps.IsAvailable(entry) and ps.IsReadable(entry):
                out.append(ps.CEnumEntryPtr(entry).GetSymbolic())
        return out

    def bounds(self, name, stream=False):
        ps = self.PySpin
        node = self._node(name, stream)
        k = self.kind(name, stream)
        if k == "float":
            n = ps.CFloatPtr(node)
        elif k == "int":
            n = ps.CIntegerPtr(node)
        else:
            return None
        try:
            return n.GetMin(), n.GetMax()
        except ps.SpinnakerException:
            return None

    def execute(self, name):
        ps = self.PySpin
        node = self._node(name)
        if node is None:
            raise RuntimeError(f"the camera has no '{name}' command")
        try:
            ps.CCommandPtr(node).Execute()
        except ps.SpinnakerException as e:
            raise RuntimeError(f"{name} failed: {e}") from e

    # -- acquisition -----------------------------------------------------------
    def start(self, buffers=10, newest_only=True):
        for key, value in (("StreamBufferCountMode", "Manual"),
                           ("StreamBufferCountManual", buffers),
                           ("StreamBufferHandlingMode",
                            "NewestOnly" if newest_only else "OldestFirst")):
            if self.writable(key, stream=True):
                try:
                    self.set(key, value, stream=True)
                except (RuntimeError, ValueError):
                    pass
        try:
            self.cam.BeginAcquisition()
        except self.PySpin.SpinnakerException as e:
            raise RuntimeError(f"could not start the acquisition: {e}") from e
        self.streaming = True

    def stop(self):
        if self.streaming:
            try:
                self.cam.EndAcquisition()
            except self.PySpin.SpinnakerException:
                pass
            self.streaming = False

    def grab(self, timeout_s):
        ps = self.PySpin
        try:
            img = self.cam.GetNextImage(max(1, int(timeout_s * 1000)))
        except ps.SpinnakerException as e:
            raise TimeoutError(f"no image from the camera within {timeout_s:g} s ({e})") from e
        try:
            if img.IsIncomplete():
                raise RuntimeError(f"incomplete image (status {img.GetImageStatus()})")
            w, h, pf = img.GetWidth(), img.GetHeight(), img.GetPixelFormatName()
            data = np.array(img.GetNDArray(), copy=True)
            depth, channels = _bytes_per_pixel(pf)
            data = data.reshape((h, w, channels) if channels > 1 else (h, w))
            return Frame(data, pf, int(img.GetTimeStamp()), int(img.GetFrameID()))
        finally:
            img.Release()

    def flush(self):
        """Throw away images already waiting in the buffer."""
        ps = self.PySpin
        while True:
            try:
                img = self.cam.GetNextImage(1)
            except ps.SpinnakerException:
                return
            img.Release()


# ===========================================================================
# Aravis
# ===========================================================================
class AravisBackend:
    name = "aravis"
    Aravis = None
    GLib = None

    @classmethod
    def load(cls):
        if cls.Aravis is None:
            import gi
            try:
                gi.require_version("Aravis", "0.8")
            except ValueError as e:
                raise ImportError(str(e)) from e
            from gi.repository import Aravis, GLib
            cls.Aravis, cls.GLib = Aravis, GLib
        return cls.Aravis

    @classmethod
    def list(cls):
        ar = cls.load()
        ar.update_device_list()
        return [(ar.get_device_vendor(i) or "", ar.get_device_model(i) or "",
                 ar.get_device_serial_nbr(i) or "") for i in range(ar.get_n_devices())]

    def __init__(self, serial=None):
        ar = self.load()
        ar.update_device_list()
        ids = [(ar.get_device_id(i), ar.get_device_serial_nbr(i) or "")
               for i in range(ar.get_n_devices())]
        if serial:
            ids = [d for d in ids if d[1] == str(serial)]
        if not ids:
            raise RuntimeError(_no_camera(serial, [(v, m, s) for v, m, s in self.list()],
                                          USB_HINT + " For Aravis install its udev rule "
                                          "(aravis.rules) or run once with sudo to test."))
        self.stream = None
        self.streaming = False
        try:
            self.cam = ar.Camera.new(ids[0][0])
        except self.GLib.Error as e:
            raise RuntimeError(f"could not open the camera: {e.message}\n{USB_HINT}") from e
        self.dev = self.cam.get_device()
        self.vendor = self.cam.get_vendor_name() or ""
        self.model = self.cam.get_model_name() or ""
        self.serial = self.get("DeviceSerialNumber") or ids[0][1]

    def close(self):
        self.stop()
        self.stream = None
        self.dev = None
        self.cam = None

    # -- nodes -----------------------------------------------------------------
    def _node(self, name):
        try:
            node = self.dev.get_feature(name)
        except Exception:
            return None
        if node is None:
            return None
        try:
            if not node.is_implemented() or not node.is_available():
                return None
        except Exception:
            pass
        return node

    def kind(self, name, stream=False):
        ar = self.Aravis
        node = self._node(name)
        if node is None:
            return None
        for cls, k in ((ar.GcEnumeration, "enum"), (ar.GcBoolean, "bool"),
                       (ar.GcCommand, "command"), (ar.GcFloat, "float"),
                       (ar.GcInteger, "int"), (ar.GcString, "string")):
            if isinstance(node, cls):
                return k
        return "other"

    def writable(self, name, stream=False):
        node = self._node(name)
        if node is None:
            return False
        try:
            return node.get_actual_access_mode() in (self.Aravis.GcAccessMode.RW,
                                                     self.Aravis.GcAccessMode.WO)
        except Exception:
            return True

    def get(self, name, stream=False):
        if stream:
            return None
        d, k = self.dev, self.kind(name)
        try:
            if k in ("enum", "string"):
                return d.get_string_feature_value(name)
            if k == "float":
                return d.get_float_feature_value(name)
            if k == "int":
                return d.get_integer_feature_value(name)
            if k == "bool":
                return bool(d.get_boolean_feature_value(name))
        except self.GLib.Error:
            return None
        return None

    def set(self, name, value, stream=False):
        if stream:
            return
        d, k = self.dev, self.kind(name)
        try:
            if k in ("enum", "string"):
                d.set_string_feature_value(name, str(value))
            elif k == "float":
                d.set_float_feature_value(name, float(value))
            elif k == "int":
                d.set_integer_feature_value(name, int(value))
            elif k == "bool":
                d.set_boolean_feature_value(name, bool(value))
            else:
                raise RuntimeError(f"{name} cannot be set")
        except self.GLib.Error as e:
            raise RuntimeError(f"could not set {name} = {value}: {e.message}") from e

    def choices(self, name, stream=False):
        if stream or self.kind(name) != "enum":
            return []
        for method in ("dup_available_enumeration_feature_values_as_strings",
                       "get_available_enumeration_feature_values_as_strings"):
            fn = getattr(self.dev, method, None)
            if fn is not None:
                try:
                    return list(fn(name) or [])
                except self.GLib.Error:
                    return []
        return []

    def bounds(self, name, stream=False):
        k = self.kind(name)
        try:
            if k == "float":
                return tuple(self.dev.get_float_feature_bounds(name))
            if k == "int":
                return tuple(self.dev.get_integer_feature_bounds(name))
        except self.GLib.Error:
            return None
        return None

    def execute(self, name):
        try:
            self.dev.execute_command(name)
        except self.GLib.Error as e:
            raise RuntimeError(f"{name} failed: {e.message}") from e

    # -- acquisition -----------------------------------------------------------
    def start(self, buffers=10, newest_only=True):
        ar = self.Aravis
        self.newest_only = newest_only
        self.pixel_format = self.get("PixelFormat") or ""
        try:
            self.stream = self.cam.create_stream(None, None)
            payload = self.cam.get_payload()
            for _ in range(buffers):
                self.stream.push_buffer(ar.Buffer.new_allocate(payload))
            self.cam.start_acquisition()
        except self.GLib.Error as e:
            self.stream = None
            raise RuntimeError(f"could not start the acquisition: {e.message}") from e
        self.streaming = True

    def stop(self):
        if self.streaming:
            try:
                self.cam.stop_acquisition()
            except Exception:
                pass
            self.streaming = False
        self.stream = None

    def grab(self, timeout_s):
        ar = self.Aravis
        buf = self.stream.timeout_pop_buffer(max(1, int(timeout_s * 1e6)))
        if buf is None:
            raise TimeoutError(f"no image from the camera within {timeout_s:g} s")
        if self.newest_only:          # like Spinnaker's NewestOnly: skip to the last one
            while True:
                newer = self.stream.try_pop_buffer()
                if newer is None:
                    break
                self.stream.push_buffer(buf)
                buf = newer
        try:
            if buf.get_status() != ar.BufferStatus.SUCCESS:
                raise RuntimeError(f"incomplete image (status {buf.get_status().value_nick})")
            data = buf.get_image_data() if hasattr(buf, "get_image_data") else buf.get_data()
            return frame_from_bytes(bytes(data), buf.get_image_width(),
                                    buf.get_image_height(), self.pixel_format,
                                    buf.get_timestamp(), buf.get_frame_id())
        finally:
            self.stream.push_buffer(buf)

    def flush(self):
        while self.stream is not None:
            buf = self.stream.try_pop_buffer()
            if buf is None:
                return
            self.stream.push_buffer(buf)
