"""Opening a Thorlabs USB instrument with PyVISA, the right way for each system.

Linux (Fedora)
    The pure-Python VISA backend ``@py`` (pyvisa-py + pyusb) talks to the
    instrument over libusb. The kernel's usbtmc driver is detached while the
    instrument is open and attached again afterwards (usb_driver.py). Access
    needs a udev rule for vendor 1313 (packaging/fedora/99-lab-equipment.rules).

Windows
    The VISA library installed with Thorlabs' software (NI-VISA) is used: no
    driver detaching, no libusb. If the exact resource name is not found, the
    instrument is looked up among the connected resources by its serial number.

``EQUIPMENT_VISA`` overrides the backend, e.g. ``@py``, ``@ivi`` or the path
of a VISA DLL / .so.
"""
import os
import re
import sys
from contextlib import ExitStack, contextmanager

from ..utils import close_quietly
from .usb_driver import THORLABS_VENDOR_ID, ThorlabsUSBDriver

ENV_VAR = "EQUIPMENT_VISA"


def is_windows():
    return sys.platform.startswith("win")


def visa_backend():
    """'' = the system VISA library (NI-VISA etc.), '@py' = pyvisa-py."""
    if os.environ.get(ENV_VAR) is not None:
        return os.environ[ENV_VAR]
    return "" if is_windows() else "@py"


def _import_pyvisa():
    try:
        import pyvisa
    except ImportError as e:
        raise RuntimeError("pyvisa is required for the Thorlabs instruments: "
                           "pip install -e \".[thorlabs]\"") from e
    return pyvisa


def resource_manager():
    """A PyVISA ResourceManager for this system; clear errors when VISA is missing."""
    pyvisa = _import_pyvisa()
    backend = visa_backend()
    try:
        return pyvisa.ResourceManager(backend)
    except (OSError, ValueError) as e:
        if backend == "":
            raise RuntimeError(
                "no VISA library found. On Windows install the Thorlabs software for the "
                "instrument (it brings NI-VISA) or NI-VISA from ni.com; or set "
                f"{ENV_VAR}=@py to use pyvisa-py (needs libusb and the WinUSB driver).") from e
        raise RuntimeError(f"VISA backend '{backend}' could not be loaded: {e}") from e


def _ids(resource):
    """'USB0::0x1313::0x80C8::M001::INSTR' -> (0x1313, 0x80C8, 'M001') or None."""
    parts = resource.split("::")
    if len(parts) < 4 or not parts[0].upper().startswith("USB"):
        return None
    try:
        return int(parts[1], 0), int(parts[2], 0), parts[3]
    except ValueError:
        return None


def find_resource(rm, product_id, serial):
    """The connected resource with this vendor/product (and serial, if given)."""
    try:
        found = rm.list_resources("USB?*::INSTR")
    except Exception:
        found = ()
    matches = []
    for res in found:
        ids = _ids(res)
        if ids and ids[0] == THORLABS_VENDOR_ID and ids[1] == product_id:
            if serial is None or ids[2].upper() == str(serial).upper():
                matches.append(res)
    return matches


def resource_serial(resource):
    ids = _ids(resource)
    return ids[2] if ids else None


@contextmanager
def open_instrument(resource, product_id, timeout_ms=5000):
    """Open a Thorlabs USBTMC instrument; yields the PyVISA resource.

    On Linux the kernel driver is detached for the time it is open.
    """
    with ExitStack() as stack:
        if not is_windows() and visa_backend() == "@py":
            stack.enter_context(ThorlabsUSBDriver(product_id=product_id))
        rm = resource_manager()
        stack.callback(close_quietly, rm)
        try:
            inst = rm.open_resource(resource)
        except Exception as first:
            matches = find_resource(rm, product_id, resource_serial(resource))
            if len(matches) != 1:
                serial = resource_serial(resource)
                others = find_resource(rm, product_id, None)
                hint = (f" Connected: {', '.join(others)}." if others else
                        " No such instrument is connected (USB cable, power, driver?).")
                raise RuntimeError(f"could not open {resource} (serial {serial}).{hint}"
                                   + (" Pass the right serial number with --dc2200-serial "
                                      "/ --pm400-serial." if others else "")) from first
            inst = rm.open_resource(matches[0])
        stack.callback(close_quietly, inst)
        inst.timeout = timeout_ms
        try:
            inst.read_termination = "\n"
            inst.write_termination = "\n"
        except Exception:
            pass
        yield inst


_ERROR = re.compile(r"^\s*([+-]?\d+)\s*,\s*\"?(.*?)\"?\s*$")


def scpi_errors(inst, limit=10):
    """Read the instrument's error queue -> [(code, message)], empty when none."""
    out = []
    for _ in range(limit):
        reply = inst.query("SYST:ERR?").strip()
        m = _ERROR.match(reply)
        code = int(m.group(1)) if m else -1
        if code == 0:
            break
        out.append((code, m.group(2) if m else reply))
    return out
