"""`equipment devices`: which instruments are connected right now.

The pE-300 is listed when its serial port identifies as CoolLED; if it does not,
`equipment pe300 status` still finds it by asking every USB serial port.

Every probe is independent: a missing library or a permission problem is
reported for that instrument only and never stops the others.
"""
from .thorlabs.common import DC2200_PRODUCT_ID, PM_PRODUCT_ID, dc2200_resource, pm_resource
from .thorlabs.usb_driver import THORLABS_VENDOR_ID

THORLABS_PRODUCTS = {DC2200_PRODUCT_ID: "DC2200 LED driver",
                     PM_PRODUCT_ID: "PM400 power meter"}


def probe_thorlabs():
    """[(description, detail)] of the Thorlabs USB devices; raises if pyusb is missing."""
    try:
        import usb.core
        import usb.util
    except ImportError as e:
        raise RuntimeError("pyusb is not installed (pip install -e \".[thorlabs]\")") from e
    out = []
    for dev in usb.core.find(find_all=True, idVendor=THORLABS_VENDOR_ID) or []:
        name = THORLABS_PRODUCTS.get(dev.idProduct, f"product 0x{dev.idProduct:04x}")
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) or "?"
        except Exception:
            serial = "? (no USB permission to read it)"
        out.append((f"Thorlabs {name}", f"serial {serial}"))
        usb.util.dispose_resources(dev)
    return out


def probe_canon():
    try:
        import gphoto2 as gp
    except ImportError as e:
        raise RuntimeError("python-gphoto2 is not installed (pip install -e \".[canon]\")") from e
    return [(str(name), f"port {port}") for name, port in gp.Camera.autodetect()]


def probe_pe300():
    """One line per pE-300; a unit with several serial ports is listed once."""
    from .coolled.pe300 import _coolled_ports, _port_sort_key, _usb_unit
    units = {}
    for p in sorted(_coolled_ports(), key=lambda p: _port_sort_key(p.device)):
        units.setdefault(_usb_unit(p) or p.device, []).append(p.device)
    return [("CoolLED pE-300", "ports " + ", ".join(ports) if len(ports) > 1
             else f"port {ports[0]}") for ports in units.values()]


def probe_flir():
    from .flir.backends import list_cameras
    found = list_cameras("auto")
    if not found:
        try:
            import PySpin  # noqa: F401
        except ImportError:
            try:
                import gi
                gi.require_version("Aravis", "0.8")
            except (ImportError, ValueError) as e:
                raise RuntimeError("neither Spinnaker/PySpin nor Aravis is installed "
                                   "(see the README, FLIR camera setup)") from e
    return [(f"{vendor} {model}".strip(), f"serial {serial} ({backend})")
            for backend, vendor, model, serial in found]


PROBES = (("Thorlabs (USB)", probe_thorlabs),
          ("CoolLED (USB serial)", probe_pe300),
          ("Canon (gphoto2)", probe_canon),
          ("FLIR (USB3 Vision)", probe_flir))


def main_devices(cfg=None):
    """Print every instrument found; returns {group: [(name, detail)] or error text}."""
    result = {}
    for title, probe in PROBES:
        print(f"{title}:")
        try:
            found = probe()
        except Exception as e:
            result[title] = str(e)
            print(f"  not available: {e}")
            continue
        result[title] = found
        if not found:
            print("  nothing connected")
        for name, detail in found:
            print(f"  {name:<28} {detail}")
    import os
    pe_port = os.environ.get("EQUIPMENT_PE300_PORT") or "automatic"
    print(f"\nConfigured:\n  DC2200 {dc2200_resource()}\n"
          f"  PM400  {pm_resource()}\n  pE-300 port {pe_port}")
    return result
