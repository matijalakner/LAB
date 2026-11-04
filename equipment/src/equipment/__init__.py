"""Drivers and terminal control for the lab equipment.

    equipment.sources       one interface for every light source (DC2200, pE-300)
    equipment.ramp          stepped ramp of any light source
    equipment.thorlabs      DC2200 LED driver, PM400 power meter
    equipment.coolled       CoolLED pE-300 LED illumination
    equipment.canon         Canon EOS R10 over USB (libgphoto2)
    equipment.flir          FLIR Blackfly S over USB3 Vision (Spinnaker or Aravis)
    equipment.experiments   pairings: ramp + photos/power (paired_ramp), LIV (liv)

The names below are imported lazily: ``from equipment import main_ramp`` does
not load OpenCV, gphoto2 or the camera SDKs, and a missing hardware library
only gives an error when that instrument is actually used.
"""
from importlib import import_module

__version__ = "1.1.0"

_EXPORTS = {
    # Thorlabs
    "main_ramp": "thorlabs.dc2200",
    "main_set_current": "thorlabs.dc2200",
    "ramp_levels": "ramp",
    "ramp_sequence": "ramp",
    "main_power_measurement": "thorlabs.pm400",
    "PM400": "thorlabs.pm400",
    "main_liv_measurement": "experiments.liv",
    "DC2200Source": "thorlabs.dc2200",
    "open_pm400": "thorlabs.pm400",
    # CoolLED
    "PE300": "coolled.pe300",
    "PE300Source": "coolled.pe300",
    "main_pe300_set": "coolled.pe300",
    "main_pe300_off": "coolled.pe300",
    "main_pe300_status": "coolled.pe300",
    # any light source
    "LightSource": "sources",
    "make_source": "sources",
    "run_ramp": "ramp",
    "main_source_ramp": "ramp",
    "main_paired_ramp": "experiments.paired_ramp",
    "ThorlabsUSBDriver": "thorlabs.usb_driver",
    # Canon
    "CanonCamera": "canon.camera",
    "main_camera_info": "canon.capture",
    "main_photo": "canon.capture",
    "main_timelapse": "canon.capture",
    "main_video": "canon.capture",
    # FLIR
    "FlirCamera": "flir.camera",
    "main_flir_list": "flir.capture",
    "main_flir_info": "flir.capture",
    "main_flir_photo": "flir.capture",
    "main_flir_timelapse": "flir.capture",
    "main_flir_video": "flir.capture",
    "main_flir_live": "flir.capture",
    # combined
    "main_ramp_camera": "experiments.ramp_camera",
    "photo_times": "experiments.ramp_camera",
    # shared
    "next_index": "capture",
    "capture_folder": "capture",
    "output_csv_path": "utils",
    "utc_timestamp": "utils",
}

__all__ = sorted(_EXPORTS) + ["__version__"]


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'equipment' has no attribute '{name}'")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return __all__
