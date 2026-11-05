"""The ``analysis`` command.

    analysis image IMAGE               lines of one photo
    analysis video VIDEO -n N          lines in a frame every N seconds
    analysis spacing NAME              mean spacing against time of an analysed video
    analysis folder NAME               every photo of a folder (tuned on the first)
    analysis report NAME               folder results against the light-source ramp
"""
import argparse
import dataclasses
import os
import sys

from .calibration import CAMERA_PIXEL_UM, OBJECTIVES, PE300_W_PER_PCT, THETA
from .detect import DetectionConfig
from .fits import FIT_CHOICES
from .paths import ENV_VAR, input_root, output_root

_DETECTION_HELP = {
    "n_blocks": "horizontal bands that must agree (default 8)",
    "k": "noise floor in sigmas (default 3)",
    "rel": "threshold floor as a fraction of the strong responses (default 0.25)",
    "min_fraction": "fraction of bands a line must be visible in (default 0.6)",
    "band_rel": "per-band visibility, fraction of the threshold (default 0.5)",
    "bg_window": "background filter width in px (default: from the width)",
    "min_dist": "minimum distance between lines in px (default: from the width)",
    "x_tol": "allowed x shift between bands in px (default: from the width)",
    "smooth": "smoothing width in px (default 5)",
    "half_width": "painted half-width of a line in px (default 1)",
    "strip_height": "rows around the middle that are analysed; 0 = all (default 200)",
    "min_threshold": "absolute threshold floor in 0-255 levels (default 2)",
}
_TYPES = {f.name: (int if f.name in ("n_blocks", "bg_window", "min_dist", "x_tol",
                                     "smooth", "half_width", "strip_height") else float)
          for f in dataclasses.fields(DetectionConfig)}


def add_detection_options(parser):
    group = parser.add_argument_group("detection options")
    for name, help_text in _DETECTION_HELP.items():
        group.add_argument("--" + name.replace("_", "-"), dest=name, type=_TYPES[name],
                           default=None, help=help_text)


def config_from_args(args):
    """DetectionConfig from the given options, or None if none was given."""
    given = {n: getattr(args, n) for n in _DETECTION_HELP if getattr(args, n, None) is not None}
    return DetectionConfig(**given) if given else None


def add_dirs(parser, inputs=True):
    parser.add_argument("--output-dir", default=None,
                        help="equipment logs and the results (default: <data>/output)")
    if inputs:
        parser.add_argument("--input-dir", default=None,
                            help="photos and videos (default: <data>/input)")


def build_parser():
    p = argparse.ArgumentParser(
        prog="analysis",
        description="Find thin vertical lines in the photos and videos taken with "
                    "'equipment' and relate their spacing to the light-source ramp.")
    p.add_argument("--debug", action="store_true", help="show the full traceback on errors")
    p.add_argument("--data-dir", default=None,
                   help="folder with equipment's input/ and output/ (default: $LINE_ANALYSIS_DATA "
                        "or $EQUIPMENT_DATA, else LAB/data next to the line-analysis "
                        "folder, else ./data)")
    sub = p.add_subparsers(dest="command", required=True)

    img = sub.add_parser("image", help="Detect the lines in one photo.")
    img.add_argument("image", help="image file, or a name like mysample_0003.jpg")
    img.add_argument("--plot", action="store_true", help="also save the line-strength plot")
    add_dirs(img)
    add_detection_options(img)

    vid = sub.add_parser("video", help="Detect the lines in a frame every N seconds of a video.")
    vid.add_argument("video", help="video file, or a name like mysample_0003.mp4")
    vid.add_argument("-n", "--interval", type=float, default=1.0,
                     help="seconds between analysed frames (default 1)")
    frames = vid.add_mutually_exclusive_group()
    frames.add_argument("--frames-log", default="auto",
                        help="FLIR frame-time log (default: found from the capture logs)")
    frames.add_argument("--nominal-fps", action="store_true",
                        help="ignore any frame log, use the frame rate of the file")
    vid.add_argument("--quiet", action="store_true", help="do not print progress")
    add_dirs(vid)
    add_detection_options(vid)

    for cmd, aliases in (("spacing", ["analyse"]),):
        sp = sub.add_parser(cmd, aliases=aliases,
                            help="Mean line spacing (± std) against time of an analysed video.")
        sp.add_argument("name", help="video name (folder under <output-dir>/video/)")
        add_dirs(sp, inputs=False)

    fol = sub.add_parser("folder", help="Analyse every photo of a folder (tuned on the first).")
    fol.add_argument("path", help="measurement name (<input-dir>/folder/NAME) or a folder")
    fol.add_argument("--yes", action="store_true",
                     help="use the first suggested settings without asking")
    fol.add_argument("--no-show", action="store_true", help="do not open the image viewer")
    fol.add_argument("--window", type=int, default=7,
                     help="neighbouring photos compared for the warnings (default 7)")
    trk = fol.add_argument_group("line tracking")
    trk.add_argument("--track", action="store_true",
                     help="search every photo only around the lines of the previous one "
                          "(the confirmed first photo is the reference)")
    trk.add_argument("--x-tolerance", type=float, default=None,
                     help="first search range +- px around each line "
                          "(default: 20 %% of the line spacing)")
    trk.add_argument("--contrast-steps", default=None,
                     help="threshold factors tried in order when a line is missing "
                          "(default 1,0.7,0.5,0.35)")
    add_dirs(fol)
    add_detection_options(fol)

    rep = sub.add_parser("report", help="Relate the folder results to the light-source ramp.")
    rep.add_argument("name", help="photo folder analysed with 'analysis folder'")
    rep.add_argument("--ramp", default=None,
                     help="ramp CSV (default: the ramp whose photo log lists these photos)")
    rep.add_argument("--results", default=None, help="results CSV instead of the one of NAME")
    rep.add_argument("--liv", default=None,
                     help="LIV CSV (equipment liv) for the power axis, if the ramp had no --power")
    rep.add_argument("--objective", choices=OBJECTIVES, default=None,
                     help="microscope objective: sets micrometers per pixel (with --camera), "
                          "and for the DC2200 the intensity per ampere (default: 20x)")
    rep.add_argument("--camera", choices=("auto",) + tuple(CAMERA_PIXEL_UM), default="auto",
                     help="camera that took the photos, for micrometers per pixel "
                          "(default: auto = from the photos' EXIF)")
    rep.add_argument("--color", choices=sorted(PE300_W_PER_PCT), default=None,
                     help="pE-300 only: colour of the ramped channel; gives the power on "
                          "the sample from the calibration when no power was measured")
    rep.add_argument("--sample", choices=sorted(THETA), default="0.8wt",
                     help="angle for the pitch (default 0.8wt)")
    rep.add_argument("--px-um", type=float, default=None,
                     help="micrometers per pixel; overrides --camera/--objective (default: "
                          "from calibration.py for the camera and objective)")
    rep.add_argument("--fit", choices=FIT_CHOICES, default="auto",
                     help="function fitted to each ramp branch on the level and power "
                          "axes: linear, quadratic, cubic, saturating (A(1-exp(-x/k))+c), "
                          "power (a x^n + c), mm (A x/(K+x) + c), auto = the best by "
                          "AICc of linear/quadratic/saturating/power/mm, or none "
                          "(default auto)")
    rep.add_argument("--camera-offset", type=float, default=0.0,
                     help="seconds added to the photo times (only for matching by time)")
    add_dirs(rep)
    return p


def run(args):
    if args.data_dir:
        os.environ[ENV_VAR] = args.data_dir
    args.output_dir = str(output_root(args.output_dir))
    if hasattr(args, "input_dir"):
        args.input_dir = str(input_root(args.input_dir))
    if args.command == "image":
        from .image import analyse_image
        from .logs import resolve_media
        from pathlib import Path
        path = resolve_media(args.image, args.input_dir)
        res = analyse_image(path, Path(args.output_dir) / "image" / path.stem,
                            config_from_args(args), plot=args.plot)
        print(f"{len(res['lines'])} lines in {path.name}")
        for key in ("marked_path", "csv_path", "plot_path"):
            if key in res:
                print(f"  {res[key]}")
    elif args.command == "video":
        from .video import process_video
        process_video(args.video, args.output_dir, args.interval, config_from_args(args),
                      frames_log=None if args.nominal_fps else args.frames_log,
                      input_dir=args.input_dir, verbose=not args.quiet)
    elif args.command in ("spacing", "analyse"):
        from .spacing import analyse_spacing
        out = analyse_spacing(args.name, args.output_dir)
        print(f"{out['frames']} frames -> {out['plot_path']}, {out['csv_path']}")
    elif args.command == "folder":
        from .folder import main_folder
        tracking = None
        if args.track or args.x_tolerance is not None or args.contrast_steps:
            from .track import CONTRAST_STEPS, TrackingConfig
            steps = CONTRAST_STEPS
            if args.contrast_steps:
                try:
                    steps = tuple(float(v) for v in args.contrast_steps.replace(" ", "").split(",") if v)
                except ValueError:
                    raise ValueError("--contrast-steps must be numbers like 1,0.7,0.5") from None
            tracking = TrackingConfig(x_tolerance=args.x_tolerance, contrast_steps=steps)
        main_folder(args.path, args.output_dir, args.input_dir, window=args.window,
                    interactive=not args.yes, show=not args.no_show,
                    config=config_from_args(args), tracking=tracking)
    elif args.command == "report":
        from .report import main_report
        out = main_report(args.name, args.ramp, args.results, args.output_dir,
                          args.objective, args.sample, args.px_um,
                          args.camera_offset, args.liv, args.color, camera=args.camera,
                          input_dir=args.input_dir, fit=args.fit)
        print(f"Micrometers per pixel: {out['px_um']:.4g} ({out['px_source']})")
        print(f"Ramp: {out['ramp_path']} ({out['level']})")
        print(f"{out['photos']} photos matched by {out['matched_by']}, "
              f"{out['plotted']} plotted (the others have a warning)")
        if out["power_source"]:
            print(f"Power from {out['power_source']}")
        print(f"Fit: {out['fit']}")
        for key in ("csv_path", "plot_path", "fits_path", "timeline_path"):
            print(f"  {out[key]}")


def _safe_console():
    """Windows: a character the console code page lacks is replaced, not an error."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _safe_console()
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except Exception as e:
        if args.debug:
            raise
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
