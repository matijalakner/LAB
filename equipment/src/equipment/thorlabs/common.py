"""Shared constants and helpers for the Thorlabs modules.

One place for the USB identifiers, so the resource string and the product ID
used for the kernel-driver detach can never disagree again.
"""
import os
import time

from .usb_driver import THORLABS_VENDOR_ID


def make_resource(product_id, serial):
    return f"USB0::{THORLABS_VENDOR_ID}::{product_id}::{serial}::0::INSTR"


DC2200_PRODUCT_ID = 0x80C8   # 32968
PM_PRODUCT_ID = 0x8075       # 33016  (was 0x8078 in PM40.py - did not match the resource string)

# Default serial numbers of the lab's instruments. Override them without editing
# the code with the environment variables EQUIPMENT_DC2200_SERIAL /
# EQUIPMENT_PM400_SERIAL, or per command with --dc2200-serial / --pm400-serial.
DC2200_SERIAL = "M00937194"
PM_SERIAL = "P5003335"

DC2200_RESOURCE = make_resource(DC2200_PRODUCT_ID, DC2200_SERIAL)
PM_RESOURCE = make_resource(PM_PRODUCT_ID, PM_SERIAL)


def dc2200_resource(serial=None):
    """VISA resource of the DC2200: serial argument > $EQUIPMENT_DC2200_SERIAL > default."""
    return make_resource(DC2200_PRODUCT_ID,
                         serial or os.environ.get("EQUIPMENT_DC2200_SERIAL") or DC2200_SERIAL)


def pm_resource(serial=None):
    """VISA resource of the PM400: serial argument > $EQUIPMENT_PM400_SERIAL > default."""
    return make_resource(PM_PRODUCT_ID,
                         serial or os.environ.get("EQUIPMENT_PM400_SERIAL") or PM_SERIAL)


def sleep_until(deadline):
    """Sleep until a time.monotonic() deadline (no accumulated drift)."""
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def close_quietly(obj):
    close = getattr(obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
