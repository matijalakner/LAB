"""Terminal control of the lab equipment.

    equipment devices                                  what is connected
    equipment dc2200 {set, off, ramp}                  Thorlabs DC2200 LED driver (A)
    equipment pe300  {set, off, status, ramp}          CoolLED pE-300 (%)
    equipment pm400  measure                           Thorlabs PM400 power meter
    equipment liv    --source {dc2200, pe300}          light ramp + PM400 power log
    equipment canon  {info, photo, timelapse, video}   Canon EOS R10
    equipment flir   {list, info, live, photo, timelapse, video}
                                                       FLIR Blackfly S

Pairing: every light source's ramp can be combined with any measurement:
    equipment <dc2200|pe300> ramp ... [--photos NAME [--camera canon|flir]] [--power]

Data:   <output-dir>/<ramp|pm|liv|camera>/<kind>_<UTC time>.csv   (default output/)
Files:  <input-dir>/folder/<name>/<name>_XXXX.jpg                 (default input/)

Nothing hardware-specific is imported until a command runs, so ``--help``
works without any driver installed, and a missing library only matters for
the instrument that needs it.
"""
import argparse
import sys
from importlib import import_module

from . import __version__
from .utils import output_csv_path, utc_timestamp

CURRENT_WARNING = "Currents are in AMPERES (0 - 2 A). Check the LED head's rating first."

CANON_SETTINGS = ("shutter", "iso", "whitebalance", "colortemperature", "picturestyle",
                  "imageformat")
FLIR_SETTINGS = ("shutter", "gain", "whitebalance", "wb_red", "wb_blue", "gamma",
                 "black_level", "pixel_format", "save_format", "quality", "defaults")
FLIR_ONLY = ("gain", "wb_red", "wb_blue", "gamma", "black_level", "pixel_format",
             "save_format", "quality", "defaults", "serial", "backend")
CANON_ONLY = ("iso", "colortemperature", "picturestyle", "imageformat", "sync_clock",
              "keep_on_card")


# ===========================================================================
# helpers
# ===========================================================================
def _call(target, cfg=None):
    """Import ``package.module:function`` lazily and call it with cfg."""
    module, func = target.split(":")
    fn = getattr(import_module(f"{__package__}.{module}"), func)
    return fn(cfg) if cfg is not None else fn()


def _positive_float(text):
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
    return value


def _non_negative_float(text):
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {text}")
    return value


def _positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {text}")
    return value


def _subparsers(parser, dest, title="commands"):
    return parser.add_subparsers(dest=dest, required=True, title=title, metavar="COMMAND")


def _cmd(subparsers, name, help_text, **kwargs):
    return subparsers.add_parser(name, help=help_text,
                                 description=help_text.replace("%%", "%"),
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 **kwargs)


def add_output_options(parser, kind, prefix=None):
    g = parser.add_argument_group("output")
    g.add_argument("--output-dir", default="output", metavar="DIR",
                   help=f"root output folder; data goes to DIR/{kind}/ (default: output)")
    g.add_argument("--output-csv", default=None, metavar="FILE",
                   help=f"CSV name (default: {prefix or kind}_<UTC time>.csv). A plain "
                        f"name is saved in DIR/{kind}/, a path is used as given.")


def add_dc2200_serial(parser):
    parser.add_argument("--dc2200-serial", default=None, metavar="SN",
                        help="DC2200 serial number (default: $EQUIPMENT_DC2200_SERIAL or "
                             "the one in thorlabs/common.py)")


def add_pm400_serial(parser):
    parser.add_argument("--pm400-serial", default=None, metavar="SN",
                        help="PM400 serial number (default: $EQUIPMENT_PM400_SERIAL or "
                             "the one in thorlabs/common.py)")


def add_name_options(parser):
    parser.add_argument("name", help="measurement name: files are saved as "
                                     "<input-dir>/folder/<name>/<name>_XXXX.<ext>")
    parser.add_argument("--input-dir", default="input", metavar="DIR",
                        help="root folder for the captured files (default: input)")


def add_canon_settings(parser, shared=True):
    """Canon EOS options. shared=False leaves out --shutter/--wb (added elsewhere)."""
    g = parser.add_argument_group(
        "Canon settings (not given = keep the camera's value; see 'equipment canon info')")
    if shared:
        g.add_argument("--shutter", default=None,
                       help="shutter speed, e.g. 1/250, 0.5, 2 (mode dial on M or Tv)")
        g.add_argument("--wb", dest="whitebalance", default=None,
                       help="white balance, e.g. Auto, Daylight, Tungsten")
    g.add_argument("--iso", default=None, help="ISO, e.g. 100, 400, Auto")
    g.add_argument("--color-temp", dest="colortemperature", default=None, metavar="K",
                   help="colour temperature in K, e.g. 5200 (sets the white balance to "
                        "colour temperature)")
    g.add_argument("--picture-style", dest="picturestyle", default=None,
                   help="picture style, e.g. Standard, Neutral, Faithful")
    g.add_argument("--image-format", dest="imageformat", default=None,
                   help='image quality, e.g. "Large Fine JPEG" (must include a JPEG)')
    g.add_argument("--sync-clock", action="store_true",
                   help="set the camera clock to the computer clock first")
    return g


def add_flir_selection(parser):
    g = parser.add_argument_group("FLIR camera selection")
    g.add_argument("--serial", default=None,
                   help="camera serial number (default: the first one found; "
                        "see 'equipment flir list')")
    g.add_argument("--backend", choices=("auto", "spinnaker", "aravis"), default=None,
                   help="camera library (default: auto = Spinnaker if installed, "
                        "otherwise Aravis)")


def add_flir_settings(parser, shared=True):
    """FLIR Blackfly S options. shared=False leaves out --shutter/--wb (added elsewhere)."""
    add_flir_selection(parser)
    g = parser.add_argument_group(
        "FLIR settings (not given = keep the camera's value; see 'equipment flir info')")
    if shared:
        g.add_argument("--shutter", "--exposure", dest="shutter", default=None,
                       help="exposure: 1/250 or 0.004 (s), 4ms, 250us, or auto")
        g.add_argument("--wb", dest="whitebalance", default=None,
                       choices=("off", "once", "auto"), type=str.lower,
                       help="automatic white balance")
    g.add_argument("--gain", default=None, help="gain in dB (0 - 48), or auto")
    g.add_argument("--wb-red", type=float, default=None, metavar="RATIO",
                   help="white balance red ratio (green = 1); switches the auto off")
    g.add_argument("--wb-blue", type=float, default=None, metavar="RATIO",
                   help="white balance blue ratio (green = 1); switches the auto off")
    g.add_argument("--gamma", default=None, help="gamma, e.g. 1.0, or off")
    g.add_argument("--black-level", type=float, default=None, metavar="PCT",
                   help="black level in %%")
    g.add_argument("--pixel-format", default=None,
                   help="BGR8 (default), BayerRG8, BayerRG16, Mono8, Mono16 "
                        "(16-bit needs --save-format png or tiff)")
    g.add_argument("--save-format", choices=("jpg", "png", "tiff"), default=None,
                   help="photo file type (default: jpg; png/tiff are lossless)")
    g.add_argument("--quality", type=int, default=None, help="JPEG quality (default: 95)")
    g.add_argument("--defaults", action="store_true",
                   help="load the factory default settings first")
    return g


def add_pe300_options(parser, channels=True):
    g = parser.add_argument_group("pE-300")
    if channels:
        g.add_argument("--channels", default=None, metavar="ABC",
                       help="channels to light, any of A B C, e.g. ABC (white, default), "
                            "B or AC; the others are switched off")
    g.add_argument("--port", default=None,
                   help="serial port, e.g. /dev/ttyACM0 or COM3 (default: "
                        "$EQUIPMENT_PE300_PORT, else found automatically)")
    return g


SOURCE_INFO = {
    # key: (name, unit metavar, max level, level word, examples)
    "dc2200": ("DC2200", "A", 2.0, "current",
               ["equipment dc2200 ramp --min 0 --max 0.5 --step 0.05 --step-time 2",
                "equipment dc2200 ramp --min 0.05 --max 1 --step 0.05 --step-time 100 \\\n"
                "      --photos mysample --shutter 1/250 --iso 100 --wb Daylight",
                "equipment dc2200 ramp --min 0 --max 1 --step 0.1 --step-time 10 \\\n"
                "      --photos mysample --camera flir --gain 0 --wb off --power"]),
    "pe300": ("pE-300", "PCT", 100, "intensity",
              ["equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 2",
               "equipment pe300 ramp --min 0 --max 100 --step 5 --step-time 10 \\\n"
               "      --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off",
               "equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 5 --power "
               "--wavelength 470",
               "equipment pe300 ramp --min 0 --max 50 --step 5 --step-time 60 --channels B "
               "\\\n      --photos s1 --power"]),
}


def add_power_options(parser):
    g = parser.add_argument_group("power readings during the ramp (optional, PM400)")
    g.add_argument("--power", action="store_true",
                   help="read the optical power with the PM400; log: <ramp>_power.csv")
    timing = g.add_mutually_exclusive_group()
    timing.add_argument("--power-delay", type=_non_negative_float, default=None, metavar="S",
                        help="one reading per step, S seconds after it starts "
                             "(default: half the step time)")
    timing.add_argument("--power-interval", type=_positive_float, default=None, metavar="S",
                        help="instead: a reading every S seconds from the ramp start")
    g.add_argument("--wavelength", type=_positive_float, default=None, metavar="NM",
                   help="PM400 wavelength in nm (default: 450)")
    g.add_argument("--averaging-count", type=_positive_int, default=None, metavar="N",
                   help="PM400 averaging (default: 10)")
    add_pm400_serial(g)
    return g


def add_photo_options(parser):
    ph = parser.add_argument_group("photos during the ramp (optional, Canon or FLIR)")
    ph.add_argument("--photos", metavar="NAME", default=None,
                    help="take photos, saved as <input-dir>/folder/NAME/NAME_XXXX.jpg; "
                         "log: <ramp>_photos.csv")
    ph.add_argument("--camera", choices=("canon", "flir"), default="canon",
                    help="which camera (default: canon)")
    timing = ph.add_mutually_exclusive_group()
    timing.add_argument("--photo-delay", type=_non_negative_float, default=None, metavar="S",
                        help="one photo per step, S seconds after it starts "
                             "(default: half the step time)")
    timing.add_argument("--photo-interval", type=_positive_float, default=None, metavar="S",
                        help="instead: a photo every S seconds from the ramp start")
    ph.add_argument("--input-dir", default="input", metavar="DIR",
                    help="root folder for the photos (default: input)")
    ph.add_argument("--keep-on-card", action="store_true",
                    help="Canon: also keep the photos on the memory card")
    ph.add_argument("--shutter", "--exposure", dest="shutter", default=None,
                    help="shutter / exposure time, e.g. 1/250")
    ph.add_argument("--wb", dest="whitebalance", default=None,
                    help="white balance (Canon: Daylight, Auto, ...; FLIR: off, once, auto)")
    add_canon_settings(parser, shared=False)
    add_flir_settings(parser, shared=False)


def add_ramp_command(subparsers, key):
    """`<source> ramp`: the same stepped ramp and pairing options for every light source."""
    name, metavar, max_level, word, examples = SOURCE_INFO[key]
    unit = "A" if metavar == "A" else "%%"          # escaped for argparse help
    rp = _cmd(subparsers, "ramp",
              f"Step the {name} {word} min -> max -> min, holding every step for "
              "--step-time seconds. The light is switched off at the end, on any error "
              "and on Ctrl+C.\n"
              "Pair it with photos (--photos NAME, Canon or FLIR) and/or power readings "
              "(--power, PM400): each measures in its own thread, by default once in "
              "the middle of every step.",
              epilog="examples:\n  " + "\n  ".join(examples))
    g = rp.add_argument_group("ramp")
    g.add_argument("--min", dest="i_min", type=_non_negative_float, required=True,
                   metavar=metavar, help=f"{word} to start from ({unit})")
    g.add_argument("--max", dest="i_max", type=_non_negative_float, required=True,
                   metavar=metavar, help=f"{word} to step up to (at most {max_level:g} {unit})")
    g.add_argument("--step", type=_positive_float, required=True, metavar=metavar,
                   help=f"{word} change per step ({unit})"
                        + (", whole percent" if key == "pe300" else ""))
    g.add_argument("--step-time", type=_positive_float, required=True, metavar="S",
                   help="how long every step is held")
    g.add_argument("--cycles", type=_positive_int, default=1,
                   help="min -> max -> min cycles (default: 1)")
    if key == "dc2200":
        add_dc2200_serial(g)
    else:
        add_pe300_options(rp)
    add_output_options(rp, "ramp")
    add_photo_options(rp)
    add_power_options(rp)
    return rp



def add_run_length(parser, what="photo"):
    parser.add_argument("-n", "--interval", type=_positive_float, required=True,
                        metavar="S", help=f"seconds between {what}s (first one at t = 0)")
    parser.add_argument("--count", type=_positive_int, default=None,
                        help=f"number of {what}s")
    parser.add_argument("--duration", type=_positive_float, default=None, metavar="S",
                        help="total time in seconds (with neither: until Ctrl+C)")


def _pick(args, keys):
    return {k: getattr(args, k, None) for k in keys}


# ===========================================================================
# parser
# ===========================================================================
def build_parser():
    parser = argparse.ArgumentParser(
        prog="equipment",
        description="Control the lab equipment from the terminal: Thorlabs DC2200 LED "
                    "driver and PM400 power meter, CoolLED pE-300, Canon EOS R10 and "
                    "FLIR Blackfly S. Light-source ramps can be paired with photos "
                    "and/or power readings.",
        epilog="Run 'equipment <device> -h' for the commands of a device.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true",
                        help="show the full traceback on errors")
    devices = _subparsers(parser, "device", "instruments")

    # -- devices -------------------------------------------------------------
    _cmd(devices, "devices", "List the connected instruments (Thorlabs USB, pE-300, Canon, "
                             "FLIR).")

    # -- DC2200 --------------------------------------------------------------
    dc = _cmd(devices, "dc2200", "Thorlabs DC2200 LED driver. " + CURRENT_WARNING)
    dcc = _subparsers(dc, "action")

    st = _cmd(dcc, "set", "Set a constant current and LEAVE THE LED ON (0 = off). The "
                          "user current limit is set to the same value.")
    st.add_argument("current", type=_non_negative_float, help="LED current in A (0 - 2)")
    add_dc2200_serial(st)

    off = _cmd(dcc, "off", "Switch the LED output off.")
    add_dc2200_serial(off)

    add_ramp_command(dcc, "dc2200")

    # -- pE-300 --------------------------------------------------------------
    pe = _cmd(devices, "pe300", "CoolLED pE-300 LED illumination (USB serial). Levels are "
                                "intensities in %% (0 - 100) of the chosen channels.",
              aliases=["pe"])
    pec = _subparsers(pe, "action")
    ps = _cmd(pec, "set", "Set the intensity of the channels and LEAVE THE LIGHT ON "
                          "(0 = off). Other channels are switched off.")
    ps.add_argument("intensity", type=_non_negative_float, help="intensity in %% (0 - 100)")
    add_pe300_options(ps)
    po = _cmd(pec, "off", "Switch all channels off.")
    add_pe300_options(po, channels=False)
    pst = _cmd(pec, "status", "Show port, firmware, wavelengths and the state of every "
                              "channel.")
    add_pe300_options(pst, channels=False)
    add_ramp_command(pec, "pe300")

    # -- PM400 ---------------------------------------------------------------
    pm = _cmd(devices, "pm400", "Thorlabs PM400 power meter.", aliases=["pm"])
    pmc = _subparsers(pm, "action")
    ms = _cmd(pmc, "measure", "Log the optical power for a while.")
    ms.add_argument("--wavelength", type=_positive_float, default=450.0, metavar="NM",
                    help="detection wavelength in nm (default: 450)")
    ms.add_argument("--averaging-count", type=_positive_int, default=10, metavar="N",
                    help="samples averaged by the meter (default: 10)")
    ms.add_argument("--duration", "--sample-duration", dest="sample_duration",
                    type=_positive_float, default=5.0, metavar="S",
                    help="total logging time in s (default: 5)")
    ms.add_argument("--rate", "--sample-rate", dest="sample_rate", type=_positive_float,
                    default=10.0, metavar="HZ", help="readings per second (default: 10)")
    add_pm400_serial(ms)
    add_output_options(ms, "pm")

    # -- LIV -----------------------------------------------------------------
    liv = _cmd(devices, "liv", "Ramp a light source linearly and log the PM400 power at "
                               "every point (light-power curve). DC2200 levels in A, "
                               "pE-300 levels in %%.")
    liv.add_argument("--source", choices=("dc2200", "pe300"), default="dc2200",
                     help="light source (default: dc2200)")
    liv.add_argument("--min", "--i-min", dest="i_min", type=_non_negative_float,
                     default=None, metavar="LEVEL", help="start level (default: 0)")
    liv.add_argument("--max", "--i-max", dest="i_max", type=_non_negative_float,
                     default=None, metavar="LEVEL",
                     help="top level (default: 0.05 A for the DC2200, 100 %% for the pE-300)")
    liv.add_argument("--ramp-duration", type=_positive_float, default=10.0, metavar="S",
                     help="time for one ramp up (and again down) (default: 10)")
    liv.add_argument("--update-rate", type=_positive_float, default=10.0, metavar="HZ",
                     help="current/power points per second (default: 10)")
    liv.add_argument("--cycles", type=_positive_int, default=1, help="(default: 1)")
    liv.add_argument("--wavelength", type=_positive_float, default=450.0, metavar="NM",
                     help="(default: 450)")
    liv.add_argument("--averaging-count", type=_positive_int, default=10, metavar="N",
                     help="(default: 10)")
    liv.add_argument("--settle-time", type=_non_negative_float, default=None, metavar="S",
                     help="wait after each current change (default: automatic; must be "
                          "shorter than 1 / update-rate)")
    add_dc2200_serial(liv)
    add_pm400_serial(liv)
    add_pe300_options(liv)
    add_output_options(liv, "liv")

    # -- Canon ---------------------------------------------------------------
    canon = _cmd(devices, "canon",
                 "Canon EOS R10 over USB (libgphoto2). Files go to "
                 "<input-dir>/folder/<name>/<name>_XXXX.jpg (.mp4 for video), a capture "
                 "log to <output-dir>/camera/.")
    cc = _subparsers(canon, "action")
    info = _cmd(cc, "info", "Show the current settings and their allowed values.")
    info.add_argument("--sync-clock", action="store_true",
                      help="set the camera clock to the computer clock first")

    cp = _cmd(cc, "photo", "Take one photo (with -i: one on every Enter, q quits).")
    add_name_options(cp)
    cp.add_argument("-i", "--interactive", action="store_true")
    cp.add_argument("--keep-on-card", action="store_true",
                    help="also keep the photos on the memory card")
    add_canon_settings(cp)
    add_output_options(cp, "camera")

    ct = _cmd(cc, "timelapse", "Take a photo every N seconds (clock based, no drift).")
    add_name_options(ct)
    add_run_length(ct)
    ct.add_argument("--keep-on-card", action="store_true",
                    help="also keep the photos on the memory card")
    add_canon_settings(ct)
    add_output_options(ct, "camera")

    cv = _cmd(cc, "video", "Record on the camera card and download the file "
                           "(switch on movie, card inserted).")
    add_name_options(cv)
    cv.add_argument("--duration", type=_positive_float, default=None, metavar="S",
                    help="recording time (default: until Enter)")
    cv.add_argument("--delete-from-card", action="store_true",
                    help="delete the video from the card after the download")
    add_canon_settings(cv)
    add_output_options(cv, "camera")

    # -- FLIR ----------------------------------------------------------------
    flir = _cmd(devices, "flir",
                "FLIR Blackfly S (BFS-U3-27S5C-C) over USB3 Vision. Files go to "
                "<input-dir>/folder/<name>/<name>_XXXX.jpg (.mp4 for video), a capture "
                "log to <output-dir>/camera/flir_<UTC>.csv.")
    fc = _subparsers(flir, "action")
    fl = _cmd(fc, "list", "List the connected FLIR / GenICam cameras.")
    fl.add_argument("--backend", choices=("auto", "spinnaker", "aravis"), default=None)
    fi = _cmd(fc, "info", "Show the current settings with their allowed values or ranges.")
    add_flir_selection(fi)

    fp = _cmd(fc, "photo", "Take one photo (with -i: one on every Enter, q quits).")
    add_name_options(fp)
    fp.add_argument("-i", "--interactive", action="store_true")
    add_flir_settings(fp)
    add_output_options(fp, "camera", prefix="flir")

    ft = _cmd(fc, "timelapse", "Take a photo every N seconds.")
    add_name_options(ft)
    add_run_length(ft)
    add_flir_settings(ft)
    add_output_options(ft, "camera", prefix="flir")

    flv = _cmd(fc, "live", "Show the live camera stream in a window: exposure, gain, "
                           "frame rate and saturation shown; keys change exposure (+/-) "
                           "and gain (]/[), mark saturated pixels (o), save snapshots (s).",
               epilog="examples:\n"
                      "  equipment flir live\n"
                      "  equipment flir live mysample --shutter 1/250 --gain 0 --wb off\n"
                      "  (keys: q quit, s snapshot, +/- exposure, ]/[ gain, o saturation, "
                      "c crosshair)")
    flv.add_argument("name", nargs="?", default="live",
                     help="prefix of the snapshots, saved as "
                          "<input-dir>/folder/<name>/<name>_XXXX.jpg (default: live)")
    flv.add_argument("--input-dir", default="input", metavar="DIR",
                     help="root folder for the snapshots (default: input)")
    flv.add_argument("--width", type=_positive_int, default=1280, metavar="PX",
                     help="window width in pixels (default: 1280; the window can be resized)")
    add_flir_settings(flv)

    fv = _cmd(fc, "video", "Record the stream to an .mp4 on the computer.")
    add_name_options(fv)
    fv.add_argument("--duration", type=_positive_float, default=None, metavar="S",
                    help="recording time (default: until Enter)")
    fv.add_argument("--fps", type=_positive_float, default=None,
                    help="frame rate (default: 10; up to ~95 at full size)")
    fv.add_argument("--codec", default="mp4v", help="FourCC of the codec (default: mp4v)")
    add_flir_settings(fv)
    add_output_options(fv, "camera", prefix="flir")

    return parser


# ===========================================================================
# commands
# ===========================================================================
def _csv(args, kind, prefix=None):
    name = args.output_csv
    if name is None and prefix:
        name = f"{prefix}_{utc_timestamp(compact=True)}.csv"
    return output_csv_path(args.output_dir, kind, name)


PHOTO_KEYS = ("photo_delay", "photo_interval", "keep_on_card")
POWER_KEYS = ("power_delay", "power_interval", "wavelength", "averaging_count",
              "pm400_serial")


def _given(args, keys):
    return [k for k in keys if getattr(args, k, None) not in (None, False)]


def _flag(key):
    return "--" + key.replace("_", "-")


def run_ramp(args, parser, key):
    name, _, max_level, word, _ = SOURCE_INFO[key]
    if args.i_max > max_level:
        parser.error(f"--max must be <= {max_level:g} for the {name}")
    if args.i_max < args.i_min:
        parser.error("--max must be >= --min")
    if key == "pe300" and args.step < 1:
        parser.error("--step must be at least 1 % (the pE-300 sets whole percent)")
    cfg = {"source": key, "min": args.i_min, "max": args.i_max, "step": args.step,
           "step_time": args.step_time, "cycles": args.cycles,
           "output_csv": _csv(args, "ramp")}
    if key == "dc2200":
        cfg["dc2200_serial"] = args.dc2200_serial
    else:
        cfg.update(port=args.port, channels=_channels(args, parser))

    # photos
    camera_opts = set(CANON_SETTINGS + FLIR_SETTINGS + FLIR_ONLY + CANON_ONLY + PHOTO_KEYS)
    if args.photos is None:
        given = _given(args, sorted(camera_opts))
        if given:
            parser.error("camera options (" + ", ".join(map(_flag, given))
                         + ") need --photos NAME")
    else:
        other = FLIR_ONLY if args.camera == "canon" else CANON_ONLY
        wrong = _given(args, other)
        if wrong:
            parser.error(f"--camera {args.camera} does not use: " + ", ".join(map(_flag, wrong)))
        if args.photo_delay is not None and args.photo_delay >= args.step_time:
            parser.error("--photo-delay must be shorter than --step-time")
        keys = CANON_SETTINGS + CANON_ONLY if args.camera == "canon" else \
            FLIR_SETTINGS + FLIR_ONLY
        cfg.update(_pick(args, keys))
        cfg.update(camera=args.photos, camera_type=args.camera, input_dir=args.input_dir,
                   photo_delay=args.photo_delay, photo_interval=args.photo_interval)

    # power
    if not args.power:
        given = _given(args, POWER_KEYS)
        if given:
            parser.error("PM400 options (" + ", ".join(map(_flag, given)) + ") need --power")
    else:
        if args.power_delay is not None and args.power_delay >= args.step_time:
            parser.error("--power-delay must be shorter than --step-time")
        cfg.update(power=True, **_pick(args, POWER_KEYS))

    if args.photos is None and not args.power:
        _call("ramp:main_source_ramp", cfg)
    else:
        _call("experiments.paired_ramp:main_paired_ramp", cfg)
    print("Ramp completed.")


def _channels(args, parser):
    if getattr(args, "channels", None) is None:
        return None
    text = args.channels.upper().replace(",", "").replace(" ", "")
    if not text or any(c not in "ABC" for c in text):
        parser.error("--channels must be letters from A, B, C, e.g. ABC or B")
    return "".join(c for c in "ABC" if c in text)


def run_dc2200(args, parser):
    if args.action == "set":
        if args.current > 2.0:
            parser.error("current must be <= 2 A")
        return _call("thorlabs.dc2200:main_set_current",
                     {"current": args.current, "dc2200_serial": args.dc2200_serial})
    if args.action == "off":
        return _call("thorlabs.dc2200:main_set_current",
                     {"current": 0.0, "dc2200_serial": args.dc2200_serial})
    return run_ramp(args, parser, "dc2200")


def run_pe300(args, parser):
    if args.action == "set":
        if args.intensity > 100:
            parser.error("intensity must be <= 100 %")
        return _call("coolled.pe300:main_pe300_set",
                     {"intensity": args.intensity, "channels": _channels(args, parser),
                      "port": args.port})
    if args.action == "off":
        return _call("coolled.pe300:main_pe300_off", {"port": args.port})
    if args.action == "status":
        return _call("coolled.pe300:main_pe300_status", {"port": args.port})
    return run_ramp(args, parser, "pe300")


def run_pm400(args, parser):
    return _call("thorlabs.pm400:main_power_measurement", {
        "wavelength": args.wavelength, "averaging_count": args.averaging_count,
        "sample_duration": args.sample_duration, "sample_rate": args.sample_rate,
        "pm400_serial": args.pm400_serial, "output_csv": _csv(args, "pm")})


def run_liv(args, parser):
    name, _, max_level, _, _ = SOURCE_INFO[args.source]
    i_min = 0.0 if args.i_min is None else args.i_min
    i_max = (0.05 if args.source == "dc2200" else 100) if args.i_max is None else args.i_max
    if i_max > max_level:
        parser.error(f"--max must be <= {max_level:g} for the {name}")
    if i_max < i_min:
        parser.error("--max must be >= --min")
    if args.settle_time is not None and args.settle_time >= 1.0 / args.update_rate:
        parser.error("--settle-time must be shorter than 1 / --update-rate")
    if args.source == "dc2200" and (args.port or args.channels):
        parser.error("--port and --channels are for --source pe300")
    if args.source == "pe300" and args.dc2200_serial:
        parser.error("--dc2200-serial is for --source dc2200")
    return _call("experiments.liv:main_liv_measurement", {
        **_pick(args, ("source", "ramp_duration", "update_rate", "cycles", "wavelength",
                       "averaging_count", "settle_time", "dc2200_serial", "pm400_serial",
                       "port")),
        "i_min": i_min, "i_max": i_max, "channels": _channels(args, parser),
        "output_csv": _csv(args, "liv")})


def run_canon(args, parser):
    if args.action == "info":
        return _call("canon.capture:main_camera_info", {"sync_clock": args.sync_clock})
    cfg = {"name": args.name, "input_dir": args.input_dir,
           "sync_clock": args.sync_clock, **_pick(args, CANON_SETTINGS),
           "output_csv": _csv(args, "camera")}
    if args.action == "photo":
        cfg.update(interactive=args.interactive, keep_on_card=args.keep_on_card)
        return _call("canon.capture:main_photo", cfg)
    if args.action == "timelapse":
        cfg.update(interval=args.interval, count=args.count, duration=args.duration,
                   keep_on_card=args.keep_on_card)
        return _call("canon.capture:main_timelapse", cfg)
    cfg.update(duration=args.duration, delete_from_card=args.delete_from_card)
    return _call("canon.capture:main_video", cfg)


def run_flir(args, parser):
    if args.action == "list":
        return _call("flir.capture:main_flir_list", {"backend": args.backend or "auto"})
    if args.action == "info":
        return _call("flir.capture:main_flir_info",
                     {"serial": args.serial, "backend": args.backend or "auto"})
    cfg = {"name": args.name, "input_dir": args.input_dir,
           **_pick(args, FLIR_SETTINGS + ("serial", "backend")),
           "output_csv": _csv(args, "camera", prefix="flir") if args.action != "live" else None}
    cfg["backend"] = cfg["backend"] or "auto"
    cfg["save_format"] = cfg["save_format"] or "jpg"
    cfg["quality"] = cfg["quality"] or 95
    if args.action == "live":
        cfg.pop("output_csv", None)
        cfg["width"] = args.width
        return _call("flir.capture:main_flir_live", cfg)
    if args.action == "photo":
        cfg["interactive"] = args.interactive
        return _call("flir.capture:main_flir_photo", cfg)
    if args.action == "timelapse":
        cfg.update(interval=args.interval, count=args.count, duration=args.duration)
        return _call("flir.capture:main_flir_timelapse", cfg)
    cfg.update(duration=args.duration, fps=args.fps, codec=args.codec)
    return _call("flir.capture:main_flir_video", cfg)


def run_devices(args, parser):
    return _call("devices:main_devices")


HANDLERS = {"devices": run_devices, "dc2200": run_dc2200, "pe300": run_pe300,
            "pe": run_pe300, "pm400": run_pm400,
            "pm": run_pm400, "liv": run_liv, "canon": run_canon, "flir": run_flir}


def _interrupted_message(args):
    if args.device in ("dc2200", "pe300", "pe", "liv") and \
            getattr(args, "action", None) not in ("set", "status"):
        extra = "; data taken so far is kept" if args.device == "liv" or \
            getattr(args, "photos", None) or getattr(args, "power", False) else ""
        return "Interrupted; the light was switched off" + extra + "."
    if args.device in ("canon", "flir"):
        return "Interrupted; files captured so far are kept."
    return "Interrupted."


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        HANDLERS[args.device](args, parser)
    except KeyboardInterrupt:
        sys.exit(_interrupted_message(args))
    except Exception as e:
        if args.debug:
            raise
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
