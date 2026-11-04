"""Analysis of a folder of photos, e.g. the photos of a ramp or a time-lapse.

Photo times come, in this order, from
  1. the capture logs written by ``equipment`` (<output_dir>/camera/*.csv and
     <output_dir>/ramp/*_photos.csv): the computer time when the capture started;
  2. the EXIF capture time (camera clock, taken as the computer's local time;
     the FLIR camera writes the computer time with milliseconds);
  3. the file time.
The ``time_source`` column of results.csv says which one was used.
"""
import dataclasses
from concurrent.futures import ThreadPoolExecutor
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
 
import numpy as np
from PIL import Image

from .detect import check_config
from .image import analyse_image, load_image
from .logs import PHOTO_SUFFIXES, capture_times, resolve_folder
from .spacing import spacing_stats
from .tune import tune_candidates
from .utils import write_csv


def _exif_time(path):
    """Camera capture time (seconds since epoch, camera clock taken as the computer's local time) or None."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            sub = exif.get_ifd(0x8769)
            raw = sub.get(36867) or exif.get(306)   # DateTimeOriginal, else DateTime
            frac = sub.get(37521) if sub.get(36867) else None    # SubSecTimeOriginal
        if raw:
            t = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").astimezone().timestamp()
            digits = "".join(c for c in str(frac or "") if c.isdigit())
            return t + (int(digits) / 10 ** len(digits) if digits else 0.0)
    except Exception:
        pass
    return None


def _file_time(path):
    stat = os.stat(path)
    if platform.system() == 'Windows':
        return stat.st_ctime
    try:
        return stat.st_birthtime
    except AttributeError:
        return stat.st_mtime


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def photo_times(photos, output_dir="output", logged=None):
    """{photo: (UTC time text, source)} with source "log", "exif" or "file"."""
    logged = capture_times(output_dir) if logged is None else logged
    out = {}
    for p in photos:
        p = Path(p)
        if p.name in logged:
            t = logged[p.name][0]
            t = t.tz_localize("UTC") if t.tzinfo is None else t
            out[p] = (_iso(t.timestamp()), "log")
            continue
        t = _exif_time(p)
        out[p] = (_iso(t), "exif") if t is not None else (_iso(_file_time(p)), "file")
    return out


def get_sorted_photos(folder, output_dir="output", times=None):
    """(photos sorted by capture time, {photo: (utc, source)})."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    photos = [p for p in folder.iterdir()
              if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES]
    if not photos:
        raise ValueError(f"No photos in folder: {folder}")
    times = times or photo_times(photos, output_dir)
    photos.sort(key=lambda p: (times[p][0], p.name))
    return photos, times


_FIELD_TYPES = {"strip_height": int, "n_blocks": int, "bg_window": int, "k": float, "rel": float,
                "min_dist": int, "x_tol": int, "min_fraction": float,
                "band_rel": float, "smooth": int, "half_width": int,
                "min_threshold": float}


def apply_overrides(text, config):
    """New DetectionConfig from text like ``k=4 rel=0.2`` (raises ValueError)."""
    changes = {}
    for token in text.replace(",", " ").split():
        name, sep, value = token.partition("=")
        if not sep or name not in _FIELD_TYPES:
            raise ValueError(f"'{token}' is not name=value with name one of: "
                             + ", ".join(_FIELD_TYPES))
        try:
            changes[name] = _FIELD_TYPES[name](value)
        except ValueError:
            raise ValueError(f"'{value}' is not a valid number for {name}") from None
    new = dataclasses.replace(config, **changes)
    check_config(new)
    return new


def _show_image(path):
    """Open an image in the system viewer; False if no viewer could be started."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        else:
            cmd = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([cmd, str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _describe(config):
    shown = ("bg_window", "rel", "k", "min_dist", "x_tol", "min_threshold")
    return ", ".join(f"{n}={getattr(config, n):.3g}" if isinstance(getattr(config, n), float)
                     else f"{n}={getattr(config, n)}" for n in shown)


def choose_parameters(first_photo, out_dir, base=None, interactive=True,
                      show=True, ask=input):
    """Tune the detection settings on one photo and let the user confirm them.

    The photo is analysed with the best suggestion of the tuner and the marked
    result is opened in the image viewer. Then:
      y  keep these settings
      n  next suggestion (Enter), or type settings such as ``k=4 rel=0.2``,
         which change the settings that were just shown
      q  stop
    Every attempt is saved as <out_dir>/tuning/try<N>_<name>_marked.png.
    With interactive=False the first suggestion is used without asking.

    Returns (config, info) or None if the user quit; info["status"] is the
    tuner's status ("ok", "check", "base", "fallback") or "manual".
    """
    first_photo, out_dir = Path(first_photo), Path(out_dir)
    img = load_image(first_photo)
    cands = tune_candidates(img, base, extended=False)   # other strip heights only if asked for
    extended = False
    if not interactive:
        return cands[0]["config"], cands[0]

    tuning_dir = out_dir / "tuning"
    index, config, info, label = 0, cands[0]["config"], cands[0], f"suggestion 1 of {len(cands)}"
    attempt = 0
    while True:
        attempt += 1
        res = analyse_image(first_photo, tuning_dir, config, write_csv=False)
        marked = tuning_dir / f"try{attempt}_{first_photo.stem}_marked.png"
        Path(res["marked_path"]).replace(marked)
        stats = spacing_stats(res["lines"])
        spacing = (f", mean spacing {stats[0]:.1f} px" +
                   ("" if np.isnan(stats[1]) else f" (std {stats[1]:.1f})")) if stats else ""
        print(f"\nAttempt {attempt} ({label}, status {info['status']}): "
              f"{len(res['lines'])} lines{spacing}")
        print(f"  settings: {_describe(config)}")
        print(f"  marked photo: {marked}")
        if show and not _show_image(marked):
            print("  (could not open an image viewer - open the file above yourself)")

        while True:
            answer = ask("Is this okay? [y = yes, n = no, q = quit] ").strip().lower()
            if answer in ("y", "yes"):
                return config, info
            if answer in ("q", "quit"):
                return None
            if answer in ("n", "no"):
                break
            print("Please answer y, n or q.")

        while True:
            if index + 1 >= len(cands) and not extended:
                print("  (trying other strip heights ...)")
                cands = tune_candidates(img, base)
                extended = True
            more = index + 1 < len(cands)
            text = ask(("Enter = next suggestion, or type " if more else "Type ")
                       + "settings (name=value ..., e.g. k=4 rel=0.2), q = quit: ").strip()
            if text.lower() in ("q", "quit"):
                return None
            if not text:
                if not more:
                    print("No more suggestions - type settings or q.")
                    continue
                index += 1
                config, info = cands[index]["config"], cands[index]
                label = f"suggestion {index + 1} of {len(cands)}"
                break
            try:
                config = apply_overrides(text, config)
            except ValueError as e:
                print(e)
                continue
            info, label = {"status": "manual"}, "your settings"
            break


RESULTS_HEADER = [
    "time_stamp", "photo", "file", "mean_spacing_px", "n_lines", "std_spacing_px", "warning",
    "time_source",
]

def _rolling_median(values, window):
    """Median of each value's neighbourhood (centred, shorter at the ends).

    window=None uses the whole series for every value.
    """
    values = np.asarray(values, dtype=float)
    if window is None:
        return np.full(len(values), np.median(values))
    half = max(1, int(window) // 2)
    return np.array([np.median(values[max(0, i - half):i + half + 1])
                     for i in range(len(values))])


def flag_unusual(rows, window=7, z_max=3.5, min_photos=3, tuning_failed=False):
    """Add warnings to the result rows; returns new rows (same format).

    Every photo is compared with its neighbours in time (a centred window of
    ``window`` photos; None = the whole folder), so a slow drift of the spacing
    or of the line count is not flagged, only sudden jumps are.

      * line count: flagged when it differs from the neighbours' median by 1 or more.
      * std: the ratio std / mean spacing is compared with the neighbours' median.
        The difference is scaled by a robust noise estimate (MAD of all
        differences, never below 5 % of the median ratio) and flagged when
        |z| > ``z_max``.
      * ``tuning_failed``: every row gets a note that default settings were used.

    "fewer than 2 lines" and "failed: ..." come from main_folder; photos with
    those are left out of the statistics. The comparisons need at least
    ``min_photos`` usable photos.
    """
    recs = [dict(zip(RESULTS_HEADER, r)) for r in rows]

    def add(rec, text):
        rec["warning"] = "; ".join(w for w in (rec["warning"], text) if w)

    if tuning_failed:
        for rec in recs:
            add(rec, "tuning fell back to default settings")

    usable = [r for r in recs if not r["warning"].startswith("failed")]
    if len(usable) >= min_photos:
        counts = np.array([r["n_lines"] for r in usable], dtype=float)
        for rec, c, m in zip(usable, counts, _rolling_median(counts, window)):
            if abs(c - m) >= 1:
                add(rec, f"{int(c)} lines vs median {m:g}")

    valid = [r for r in usable if r["mean_spacing_px"] != "" and r["std_spacing_px"] != ""]
    if len(valid) >= min_photos:
        ratio = np.array([r["std_spacing_px"] / r["mean_spacing_px"] for r in valid])
        resid = ratio - _rolling_median(ratio, window)
        scale = max(1.4826 * np.median(np.abs(resid - np.median(resid))),
                    0.05 * np.median(ratio))
        if scale > 0:
            for rec, z in zip(valid, resid / scale):
                if abs(z) > z_max:
                    add(rec, f"std {'high' if z > 0 else 'low'} (z={z:+.1f})")
    return [tuple(r[h] for h in RESULTS_HEADER) for r in recs]


def main_folder(path, output_dir="output", input_dir="input", window=7, z_max=3.5,
                interactive=True, show=True, ask=input, config=None):
    """Analyse every photo of a folder and write <output_dir>/folder/<name>/results.csv.

    ``path`` is a folder or a measurement name (<input_dir>/folder/<name>). The
    first photo (oldest) tunes the detection settings (see choose_parameters):
    its marked result is shown and you confirm it with y, or answer n to try
    other settings. ``config`` skips the tuning and uses those settings. Every
    photo is then analysed with the confirmed settings (saved to
    parameters.json). Unusual photos get a text in ``warning`` (flag_unusual).
    interactive=False uses the first suggestion without asking.
    Returns the result rows, or [] if you quit.
    """
    folder = resolve_folder(path, input_dir)
    photos, times = get_sorted_photos(folder, output_dir)
    out_dir = Path(output_dir) / "folder" / folder.name

    if config is not None:
        check_config(config)
        tuning = {"status": "given"}
    else:
        try:
            chosen = choose_parameters(photos[0], out_dir, interactive=interactive,
                                       show=show, ask=ask)
        except EOFError:
            print("\nNo input available (is stdin closed?). Use --yes to run without asking.")
            return []
        if chosen is None:
            print("Cancelled, nothing was analysed.")
            return []
        config, tuning = chosen
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "parameters.json").write_text(
        json.dumps(dataclasses.asdict(config), indent=2), encoding="utf-8")
    sources = sorted({times[p][1] for p in photos})
    print(f"\nAnalysing {len(photos)} photos with: {_describe(config)}")
    print(f"Photo times from: {', '.join(sources)}")

    def work(photo):
        res = analyse_image(photo, out_dir, config, write_csv=False)
        return res["lines"], spacing_stats(res["lines"])

    # decoding, the median filters and the PNG encoder release the GIL, so threads help
    workers = max(1, min(4, os.cpu_count() or 1, len(photos)))
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, p) for p in photos]
        for n, (photo, fut) in enumerate(zip(photos, futures), start=1):
            warning, mean, std, n_lines = "", "", "", 0
            try:
                lines, stats = fut.result()
                n_lines = len(lines)
                if stats is None:
                    warning = "fewer than 2 lines"
                else:
                    mean = round(stats[0], 3)
                    std = "" if np.isnan(stats[1]) else round(stats[1], 3)
            except Exception as e:
                warning = f"failed: {e}"
            rows.append((times[photo][0], n, photo.name, mean, n_lines, std, warning,
                         times[photo][1]))
            print(f"[{n}/{len(photos)}] {photo.name}: {n_lines} lines {warning}")

    rows = flag_unusual(rows, window=window, z_max=z_max,
                        tuning_failed=tuning["status"] == "fallback")
    flagged = [r for r in rows if r[6]]
    print(f"{len(flagged)} of {len(rows)} photos have a warning")
    for r in flagged:
        print(f"  photo {r[1]} ({r[2]}): {r[6]}")
    csv_path = write_csv(out_dir / "results.csv", RESULTS_HEADER, rows)
    print(f"Data: {csv_path}")
    return rows
