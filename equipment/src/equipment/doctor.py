"""`equipment doctor`: is this computer ready for every instrument?

Checks the libraries, drivers and permissions each instrument needs on this
system (Fedora, Ubuntu, other Linux, macOS, Windows) and prints, for anything
missing, how to fix it. Nothing is changed and no instrument is switched on: connected
devices are only listed.

    OK    ready
    WARN  works, but something may cause trouble (e.g. a small USB buffer)
    FAIL  this instrument cannot be used until it is fixed
    --    not used on this system (e.g. the Canon on Windows)
"""
import importlib
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL, NA = "OK", "WARN", "FAIL", "--"

UNIX_INSTALL = "run ./install.sh in LAB"           # Fedora, Ubuntu, macOS
WINDOWS_INSTALL = "run install.bat in LAB"
LINUX = ("fedora", "ubuntu", "linux")

# how to install a system library, per system
LIBUSB_FIX = {"fedora": "sudo dnf install libusb1",
              "ubuntu": "sudo apt install libusb-1.0-0",
              "macos": "brew install libusb, and work in a terminal after 'source setup.sh' "
                       "(it lets Python find Homebrew's libusb)",
              "linux": "install libusb 1.0 with your package manager"}


@dataclass
class Check:
    group: str
    status: str
    text: str
    fix: str = ""


def _os_release():
    """/etc/os-release as a dict (empty if missing)."""
    out = {}
    try:
        lines = Path("/etc/os-release").read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"')
    return out


def system_name():
    """'fedora', 'ubuntu' (also Debian and derivatives), 'linux', 'macos' or 'windows'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        info = _os_release()
        ids = {info.get("ID", "")} | set(info.get("ID_LIKE", "").split())
        if "fedora" in ids:
            return "fedora"
        if ids & {"ubuntu", "debian"}:
            return "ubuntu"
        return "linux"
    return sys.platform


def _module(name):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _version(mod):
    return getattr(mod, "__version__", "") if mod else ""


def _install_hint(system):
    return WINDOWS_INSTALL if system == "windows" else UNIX_INSTALL


def _process_running(name):
    import subprocess
    try:
        return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0
    except OSError:
        return False


def _udev_has(*ids):
    """True if a udev rule mentions every id (e.g. '1313', or '0483', 'a080')."""
    for folder in ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d"):
        try:
            files = list(Path(folder).glob("*.rules"))
        except OSError:
            continue
        for f in files:
            try:
                text = f.read_text(errors="ignore").lower()
            except OSError:
                continue
            if all(i.lower() in text for i in ids):
                return True
    return False


def _in_group(name):
    try:
        import grp
        gid = grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return False
    return gid in os.getgroups()


# ---------------------------------------------------------------------------
# per instrument
# ---------------------------------------------------------------------------
def check_python(system):
    v = sys.version_info
    ok = v >= (3, 10)
    venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    out = [Check("Python", OK if ok else FAIL,
                 f"Python {platform.python_version()} ({sys.executable})",
                 "" if ok else "Python 3.10 or newer is needed")]
    if not venv:
        out.append(Check("Python", WARN, "not running in a virtual environment",
                         _install_hint(system) + ", then activate the environment"))
    return out


def check_thorlabs(system):
    out = []
    pyvisa = _module("pyvisa")
    if pyvisa is None:
        return [Check("Thorlabs DC2200/PM400", FAIL, "pyvisa is not installed",
                      'pip install -e ".[thorlabs]"')]
    from .thorlabs.visa import resource_manager, visa_backend
    backend = visa_backend()
    label = backend or "system VISA library"
    try:
        rm = resource_manager()
        try:
            lib = str(getattr(rm, "visalib", "")).splitlines()[0][:70]
        except Exception:
            lib = ""
        out.append(Check("Thorlabs DC2200/PM400", OK,
                         f"pyvisa {_version(pyvisa)}, backend {label} {lib}".strip()))
        try:
            rm.close()
        except Exception:
            pass
    except Exception as e:
        out.append(Check("Thorlabs DC2200/PM400", FAIL, f"VISA backend {label}: {e}",
                         "install the Thorlabs software for the DC2200 / PM400 (it brings "
                         "NI-VISA), or NI-VISA from ni.com" if system == "windows"
                         else 'pip install -e ".[thorlabs]" (pyvisa-py)'))
    if system != "windows":
        from .thorlabs.visa import ensure_libusb_findable
        ensure_libusb_findable()
        usb = _module("usb.core")
        if usb is None:
            out.append(Check("Thorlabs DC2200/PM400", FAIL, "pyusb is not installed",
                             'pip install -e ".[thorlabs]"'))
        else:
            backend_mod = _module("usb.backend.libusb1")
            ok = backend_mod is not None and backend_mod.get_backend() is not None
            out.append(Check("Thorlabs DC2200/PM400", OK if ok else FAIL,
                             "libusb found" if ok else "libusb 1.0 not found",
                             "" if ok else LIBUSB_FIX.get(system, LIBUSB_FIX["linux"])))
    if system in LINUX:
        if _udev_has("1313"):
            out.append(Check("Thorlabs DC2200/PM400", OK, "udev rule for vendor 1313"))
        else:
            out.append(Check("Thorlabs DC2200/PM400", WARN,
                             "no udev rule for Thorlabs (vendor 1313): only root can open "
                             "the instruments", UNIX_INSTALL))
    from .thorlabs.dc2200 import dc2200_driver
    try:
        out.append(Check("Thorlabs DC2200/PM400", OK, f"DC2200 driver: {dc2200_driver()}"))
    except ValueError as e:
        out.append(Check("Thorlabs DC2200/PM400", FAIL, str(e)))
    return out


def check_pe300(system):
    serial = _module("serial")
    if serial is None:
        return [Check("CoolLED pE-300", FAIL, "pyserial is not installed",
                      'pip install -e ".[coolled]"')]
    out = [Check("CoolLED pE-300", OK, f"pyserial {_version(serial)}")]
    if system in LINUX:
        if _udev_has("0483", "a080"):
            out.append(Check("CoolLED pE-300", OK, "udev rule for the pE-300 (0483:a080)"))
        elif _in_group("dialout"):
            out.append(Check("CoolLED pE-300", OK, "user is in the dialout group"))
        else:
            out.append(Check("CoolLED pE-300", WARN,
                             "no udev rule for 0483:a080 and not in group dialout: "
                             "'permission denied' on /dev/ttyACM*", UNIX_INSTALL))
    return out


def check_flir(system):
    out = []
    np_, cv2 = _module("numpy"), _module("cv2")
    if np_ is None or cv2 is None:
        missing = ", ".join(n for n, m in (("numpy", np_), ("opencv", cv2)) if m is None)
        return [Check("FLIR Blackfly S", FAIL, f"{missing} not installed",
                      'pip install -e ".[flir]"')]
    import re
    m = re.search(r"^\s*GUI:\s*(\S+)", cv2.getBuildInformation(), re.M)
    gui = bool(m) and m.group(1).upper() != "NONE"
    out.append(Check("FLIR Blackfly S", OK if gui else WARN,
                     f"opencv {_version(cv2)}" + ("" if gui else " without window support "
                                                  "('flir live' cannot open a window)"),
                     "" if gui else "pip uninstall -y opencv-python-headless && "
                                    "pip install opencv-python"))
    spin = _module("PySpin")
    aravis = None
    if system != "windows":
        try:
            import gi
            gi.require_version("Aravis", "0.8")
            from gi.repository import Aravis
            aravis = Aravis
        except Exception:
            aravis = None
    if spin is not None:
        out.append(Check("FLIR Blackfly S", OK, "Spinnaker (PySpin) installed"))
    if aravis is not None:
        out.append(Check("FLIR Blackfly S", OK,
                         f"Aravis {aravis.MAJOR_VERSION}.{aravis.MINOR_VERSION}."
                         f"{aravis.MICRO_VERSION} installed"))
    if spin is None and aravis is None:
        fix = {"windows": "install the Spinnaker SDK from teledynevisionsolutions.com, then "
                          + WINDOWS_INSTALL + " (it installs the PySpin wheel)",
               "macos": UNIX_INSTALL + " (brew install aravis pygobject3)",
               "ubuntu": UNIX_INSTALL + " (apt install gir1.2-aravis-0.8)",
               }.get(system, UNIX_INSTALL + " (builds Aravis 0.8)")
        out.append(Check("FLIR Blackfly S", FAIL,
                         "no camera library (Spinnaker or Aravis) found", fix))
    if system in LINUX:
        try:
            mb = int(Path("/sys/module/usbcore/parameters/usbfs_memory_mb").read_text())
        except (OSError, ValueError):
            mb = None
        if mb is not None and mb < 1000:
            out.append(Check("FLIR Blackfly S", WARN,
                             f"USB buffer usbfs_memory_mb = {mb} (full-speed video needs "
                             "1000)", UNIX_INSTALL))
        if aravis is not None and not _udev_has("1e10"):
            out.append(Check("FLIR Blackfly S", WARN,
                             "no udev rule for FLIR (vendor 1e10): only root can open the "
                             "camera", UNIX_INSTALL))
    return out


def check_canon(system):
    if system == "windows":
        return [Check("Canon EOS R10", NA, "not supported on Windows (libgphoto2 is "
                                           "Linux/macOS only); use it on Fedora")]
    gp = _module("gphoto2")
    if gp is None:
        return [Check("Canon EOS R10", FAIL, "python-gphoto2 is not installed",
                      UNIX_INSTALL + ' (or pip install -e ".[canon]")')]
    out = [Check("Canon EOS R10", OK, f"python-gphoto2 {_version(gp)}")]
    if system == "macos" and _process_running("ptpcamerad"):
        out.append(Check("Canon EOS R10", WARN,
                         "macOS's ptpcamerad is running and grabs cameras over USB",
                         "before a Canon command: killall -9 ptpcamerad"))
    elif system in LINUX and _process_running("gvfs-gphoto2-volume-monitor"):
        out.append(Check("Canon EOS R10", WARN,
                         "GNOME's gvfs-gphoto2-volume-monitor is running and may grab the "
                         "camera", "./install.sh --mask-gvfs in LAB"))
    return out


def check_data():
    from .paths import data_dir
    d = data_dir().resolve()
    exists = (d / "input").is_dir() or (d / "output").is_dir()
    return [Check("Data", OK if exists else WARN, f"data folder {d}",
                  "" if exists else "it is created by the first measurement")]


def run_checks(system=None, connected=True):
    system = system or system_name()
    checks = []
    for fn in (check_python, check_thorlabs, check_pe300, check_flir, check_canon):
        try:
            checks += fn(system)
        except Exception as e:                                   # a check never crashes
            checks.append(Check(fn.__name__.replace("check_", ""), FAIL, f"check failed: {e}"))
    checks += check_data()
    return system, checks


def main_doctor(cfg=None):
    """Print the checks; returns the number of FAIL lines."""
    system, checks = run_checks()
    names = {"fedora": "Fedora", "ubuntu": "Ubuntu / Debian", "linux": "Linux",
             "macos": "macOS", "windows": "Windows"}
    print(f"System: {names.get(system, system)} ({platform.platform()})\n")
    group = None
    for c in checks:
        if c.group != group:
            group = c.group
            print(group)
        print(f"  [{c.status:^4}] {c.text}")
        if c.fix and c.status in (WARN, FAIL):
            print(f"         fix: {c.fix}")
    fails = sum(c.status == FAIL for c in checks)
    print("\nConnected instruments:")
    from .devices import main_devices
    main_devices(None, configured=False, indent="  ")
    print(f"\n{'Everything is ready.' if not fails else f'{fails} problem(s) to fix (FAIL).'}")
    return fails
