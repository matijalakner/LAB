"""The ``analysis`` command.

    analysis image IMAGE               lines of one photo
    analysis video VIDEO -n N          lines in a frame every N seconds
    analysis spacing NAME              mean spacing against time of an analysed video
    analysis folder NAME               every photo of a folder (tuned on the first)
    analysis report NAME               folder results against the light-source ramp
"""
import argparse
import dataclasses
import sys

from .calibration import COEFF, PX_TO_UM, THETA
from .detect import DetectionConfig

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
    parser.add_argument("--output-dir", default="output",
                        help="root of the results and of the equipment logs (default: output)")
    if inputs:
        parser.add_argument("--input-dir", default="input",
                            help="root of the photos and videos (default: input)")


def build_parser():
    p = argparse.ArgumentParser(
        prog="analysis",
        description="Find thin vertical lines in the photos and videos taken with "
                    "'equipment' and relate their spacing to the light-source ramp.")
    p.add_argument("--debug", action="store_true", help="show the full traceback on errors")
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
    add_dirs(fol)
    add_detection_options(fol)

    rep = sub.add_parser("report", help="Relate the folder results to the light-source ramp.")
    rep.add_argument("name", help="photo folder analysed with 'analysis folder'")
    rep.add_argument("--ramp", default=None,
                     help="ramp CSV (default: the ramp whose photo log lists these photos)")
    rep.add_argument("--results", default=None, help="results CSV instead of the one of NAME")
    rep.add_argument("--liv", default=None,
                     help="LIV CSV (equipment liv) for the power axis, if the ramp had no --power")
    rep.add_argument("--objective", choices=sorted(COEFF), default="20x",
                     help="DC2200 only: intensity per ampere, used without measured power "
                          "(default 20x)")
    rep.add_argument("--sample", choices=sorted(THETA), default="0.8wt",
                     help="angle for the pitch (default 0.8wt)")
    rep.add_argument("--px-um", type=float, default=PX_TO_UM,
                     help=f"micrometers per pixel (default {PX_TO_UM})")
    rep.add_argument("--camera-offset", type=float, default=0.0,
                     help="seconds added to the photo times (only for matching by time)")
    add_dirs(rep, inputs=False)
    return p


def run(args):
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
        main_folder(args.path, args.output_dir, args.input_dir, window=args.window,
                    interactive=not args.yes, show=not args.no_show,
                    config=config_from_args(args))
    elif args.command == "report":
        from .report import main_report
        out = main_report(args.name, args.ramp, args.results, args.output_dir,
                          args.objective, args.sample, args.px_um, args.camera_offset,
                          args.liv)
        print(f"Ramp: {out['ramp_path']} ({out['level']})")
        print(f"{out['photos']} photos matched by {out['matched_by']}, "
              f"{out['plotted']} plotted (the others have a warning)")
        if out["power_source"]:
            print(f"Power from {out['power_source']}")
        for key in ("csv_path", "plot_path", "timeline_path"):
            print(f"  {out[key]}")


def main(argv=None):
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
