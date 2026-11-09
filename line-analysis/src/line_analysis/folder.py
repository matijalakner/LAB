"""Analysis of a folder of photos, e.g. the photos of a ramp or a time-lapse.

Photo times come, in this order, from
  1. the capture logs written by ``equipment`` (<output_dir>/camera/*.csv and
     <output_dir>/ramp/*_photos.csv): the computer time when the capture started;
  2. the EXIF capture time (camera clock, taken as the computer's local time;
     the FLIR camera writes the computer time with milliseconds);
  3. the file time.
The ``time_source`` column of results.csv says which one was used.
"""
from .paths import input_root, output_root
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

from .detect import DetectionConfig, check_config
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


def photo_times(photos, output_dir=None, logged=None):
    """{photo: (UTC time text, source)} with source "log", "exif" or "file"."""
    output_dir = output_root(output_dir)
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


def get_sorted_photos(folder, output_dir=None, times=None):
    """(photos sorted by capture time, {photo: (utc, source)})."""
    output_dir = output_root(output_dir)
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
                      show=True, ask=input, middle=None):
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
    img = load_image(first_photo, middle)
    cands = tune_candidates(img, base, extended=False)   # other strip heights only if asked for
    extended = False
    if not interactive:
        return cands[0]["config"], cands[0]

    tuning_dir = out_dir / "tuning"
    index, config, info, label = 0, cands[0]["config"], cands[0], f"suggestion 1 of {len(cands)}"
    attempt = 0
    while True:
        attempt += 1
        res = analyse_image(first_photo, tuning_dir, config, write_csv=False, middle=middle)
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
                return config, dict(info, approved_lines=list(res["lines"]))
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


TRACKING_HEADER = ["photo", "file", "status", "n_lines", "widened", "lowered",
                   "min_contrast_factor", "missing_x", "left_x", "reference_x"]


def _mark_tracked(img, lines, missing, half_width):
    """Marked photo: found lines red, expected but missing lines yellow."""
    from .detect import mark_image
    marked = mark_image(img, lines, half_width)
    for x in missing:
        x = int(round(x))
        marked[::4, max(0, x - half_width):x + half_width + 1] = (255, 220, 0)  # dotted
    return marked


def track_folder(photos, out_dir, config, tracking=None, reference=None, workers=None,
                 middle=None):
    """Analyse photos in order, each searched around the lines of the previous one.

    The first photo is detected normally (or ``reference`` is used as its
    lines); see track.py for the search rules. Writes <photo>_marked.png
    (missing lines dotted yellow) and returns one dict per photo with lines,
    warning and the tracking details. Photos are read ahead and saved in
    threads; the tracking itself runs in order.
    """
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    from .detect import compute_signal, threshold_from
    from .track import TrackingConfig, check_tracking, track_lines

    tracking = tracking or TrackingConfig()
    check_tracking(tracking)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def load(photo):
        img = load_image(photo, middle)
        sig, _, min_dist, x_tol = compute_signal(img, config)
        return img, sig, x_tol, min_dist

    def save(img, photo, lines, missing):
        Image.fromarray(_mark_tracked(img, lines, missing, config.half_width)).save(
            out_dir / f"{photo.stem}_marked.png", compress_level=1)

    workers = workers or max(1, min(4, os.cpu_count() or 1, len(photos)))
    ahead = 2 * workers
    results, ref = [], None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        loads, saves = deque(), deque()
        queue = iter(photos)
        for p in queue:
            loads.append((p, pool.submit(load, p)))
            if len(loads) >= ahead:
                break
        n = 0
        while loads:
            photo, fut = loads.popleft()
            nxt = next(queue, None)
            if nxt is not None:
                loads.append((nxt, pool.submit(load, nxt)))
            n += 1
            rec = {"photo": photo, "lines": [], "warning": "", "status": "", "missing": [],
                   "left": [], "widened": 0, "lowered": 0, "min_factor": "", "reference": []}
            try:
                img, sig, x_tol, min_dist = fut.result()
                thr = threshold_from(sig, config)
                if ref is None:                                   # first photo: reference
                    if reference is None:
                        from .detect import select_lines
                        lines = select_lines(sig, thr, config, min_dist, x_tol)
                    else:
                        lines = sorted(float(x) for x in reference)
                    if not lines:
                        raise ValueError("no lines on the first photo, nothing to track")
                    ref = list(lines)
                    rec.update(lines=lines, status="reference", reference=ref)
                else:
                    t = track_lines(sig, ref, thr, config, x_tol, tracking)
                    rec.update(lines=t["lines"], missing=t["missing"], left=t["left"],
                               widened=t["widened"], lowered=t["lowered"],
                               min_factor=t["min_factor"], reference=t["reference"],
                               status="reported" if t["reported"] else "ok")
                    if t["reported"]:
                        rec["warning"] = ("tracking: no line near x=" +
                                          ", ".join(f"{x:.0f}" for x in t["missing"]))
                    ref = t["reference"]
                saves.append(pool.submit(save, img, photo, rec["lines"], rec["missing"]))
                del img
                while len(saves) > ahead:
                    saves.popleft().result()
            except Exception as e:
                rec["warning"], rec["status"] = f"failed: {e}", "failed"
                if ref is None:
                    raise
            results.append(rec)
            extra = (f", {rec['widened']} widened" if rec["widened"] else "") + \
                    (f", {rec['lowered']} at lower contrast" if rec["lowered"] else "") + \
                    (f", {len(rec['left'])} left the picture" if rec["left"] else "")
            print(f"[{n}/{len(photos)}] {photo.name}: {len(rec['lines'])} lines "
                  f"({rec['status']}{extra}) {rec['warning']}")
        for s in saves:
            s.result()
    return results


STRIP_PARTS = 5        # strips of the first photo and the last photo of each of 5 equal parts
STRIP_HEIGHT = 100     # rows around the middle of the photo
MIDDLE_HEIGHT = 300    # rows of every photo analysed by main_folder (unless middle_strips=False)


def strip_positions(n_photos, parts=STRIP_PARTS):
    """Photo numbers (from 1) that get a strip: 100 photos give 1, 20, 40, 60, 80, 100."""
    return sorted({max(1, (2 * k * n_photos + parts) // (2 * parts)) for k in range(parts + 1)})


def save_strips(photos, out_dir, parts=STRIP_PARTS, height=STRIP_HEIGHT, workers=None):
    """Save the middle rows of evenly spread photos as <out_dir>/strips/<photo>_strip.png.

    The photos are the ones of strip_positions, in capture order. The strips
    are cut from the originals (full width, no marks). A photo lower than
    ``height`` is saved whole. A photo that cannot be read is reported and skipped. Returns
    the written paths.
    """
    strips_dir = Path(out_dir) / "strips"
    strips_dir.mkdir(parents=True, exist_ok=True)

    def save(photo):
        img = load_image(photo)
        r0 = max(0, (img.shape[0] - height) // 2)
        path = strips_dir / f"{photo.stem}_strip.png"
        Image.fromarray(img[r0:r0 + height]).save(path, compress_level=1)
        return path

    photos = list(photos)
    chosen = [photos[n - 1] for n in strip_positions(len(photos), parts)]
    workers = workers or max(1, min(4, os.cpu_count() or 1, len(chosen)))
    written = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for photo, fut in [(p, pool.submit(save, p)) for p in chosen]:
            try:
                written.append(fut.result())
            except Exception as e:
                print(f"No strip for {photo.name}: {e}")
    print(f"Strips ({height} px): {len(written)} in {strips_dir}")
    return written


def main_folder(path, output_dir=None, input_dir=None, window=7, z_max=3.5,
                interactive=True, show=True, ask=input, config=None, tracking=None,
                middle_strips=True):
    """Analyse every photo of a folder and write <output_dir>/folder/<name>/results.csv.

    ``path`` is a folder or a measurement name (<input_dir>/folder/<name>). The
    first photo (oldest) tunes the detection settings (see choose_parameters):
    its marked result is shown and you confirm it with y, or answer n to try
    other settings. ``config`` skips the tuning and uses those settings. Every
    photo is then analysed with the confirmed settings (saved to
    parameters.json). Unusual photos get a text in ``warning`` (flag_unusual).
    interactive=False uses the first suggestion without asking.

    ``tracking`` (a TrackingConfig, or True for the defaults) switches to line
    tracking (track.py): the lines of the confirmed first photo are saved as
    the reference, and every next photo is searched only around the lines of
    the previous one. Photos where a line is missing are reported (warning)
    and the next photo is searched around the last good positions. The
    details go to tracking.csv.

    By default the middle 300 rows are cut out of every photo and only those,
    all 300 of them, are analysed; the marked pictures are 300 rows high and a
    photo with fewer rows gets a "failed" warning. ``middle_strips=False``
    analyses the whole photos with config.strip_height instead, writes to
    <output_dir>/folder/<name>/full_image/, and saves the middle 100 rows of
    6 evenly spread photos to strips/ there (save_strips).

    Returns the result rows, or [] if you quit.
    """
    output_dir = output_root(output_dir)
    input_dir = input_root(input_dir)
    folder = resolve_folder(path, input_dir)
    photos, times = get_sorted_photos(folder, output_dir)
    out_dir = Path(output_dir) / "folder" / folder.name
    middle, base = None, None
    if middle_strips:
        middle, base = MIDDLE_HEIGHT, DetectionConfig(strip_height=0)
        if config is not None:
            config = dataclasses.replace(config, strip_height=0)
    else:
        out_dir = out_dir / "full_image"

    if config is not None:
        check_config(config)
        tuning = {"status": "given"}
    else:
        try:
            chosen = choose_parameters(photos[0], out_dir, base, interactive=interactive,
                                       show=show, ask=ask, middle=middle)
        except EOFError:
            print("\nNo input available (is stdin closed?). Use --yes to run without asking.")
            return []
        if chosen is None:
            print("Cancelled, nothing was analysed.")
            return []
        config, tuning = chosen
    out_dir.mkdir(parents=True, exist_ok=True)
    params = dataclasses.asdict(config)
    if tracking:
        from .track import TrackingConfig, check_tracking
        tracking = TrackingConfig() if tracking is True else tracking
        check_tracking(tracking)
        params["tracking"] = dataclasses.asdict(tracking)
    (out_dir / "parameters.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
    sources = sorted({times[p][1] for p in photos})
    print(f"\nAnalysing {len(photos)} photos with: {_describe(config)}")
    print(f"Photo times from: {', '.join(sources)}")
    if middle is None:
        save_strips(photos, out_dir)
    if tracking:
        return _finish_tracked(photos, times, out_dir, config, tracking,
                               tuning.get("approved_lines"), window, z_max,
                               tuning["status"] == "fallback", middle)

    def work(photo):
        res = analyse_image(photo, out_dir, config, write_csv=False, middle=middle)
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


def _finish_tracked(photos, times, out_dir, config, tracking, reference, window, z_max,
                    tuning_failed, middle=None):
    """main_folder with line tracking: results.csv, tracking.csv and warnings."""
    if reference:
        tol = (f"{tracking.x_tolerance:g} px" if tracking.x_tolerance
               else "20 % of the spacing")
        print(f"Tracking {len(reference)} lines: search +-{tol}, then "
              f"+-half the spacing; contrast steps {list(tracking.contrast_steps)}")
    recs = track_folder(photos, out_dir, config, tracking, reference, middle=middle)
    rows, track_rows = [], []
    fmt = lambda xs: " ".join(f"{x:.1f}" for x in xs)
    for n, rec in enumerate(recs, start=1):
        photo, lines, warning = rec["photo"], rec["lines"], rec["warning"]
        stats = spacing_stats(lines)
        mean, std = "", ""
        if stats is None:
            warning = "; ".join(w for w in (warning, "fewer than 2 lines") if w)
        else:
            mean = round(stats[0], 3)
            std = "" if np.isnan(stats[1]) else round(stats[1], 3)
        rows.append((times[photo][0], n, photo.name, mean, len(lines), std, warning,
                     times[photo][1]))
        track_rows.append((n, photo.name, rec["status"], len(lines), rec["widened"],
                           rec["lowered"], rec["min_factor"], fmt(rec["missing"]),
                           fmt(rec["left"]), fmt(rec["reference"])))

    rows = flag_unusual(rows, window=window, z_max=z_max, tuning_failed=tuning_failed)
    reported = [r for r in track_rows if r[2] == "reported"]
    flagged = [r for r in rows if r[6]]
    print(f"{len(reported)} of {len(rows)} photos reported by the tracking, "
          f"{len(flagged)} have a warning")
    for r in flagged:
        print(f"  photo {r[1]} ({r[2]}): {r[6]}")
    write_csv(out_dir / "tracking.csv", TRACKING_HEADER, track_rows)
    csv_path = write_csv(out_dir / "results.csv", RESULTS_HEADER, rows)
    print(f"Data: {csv_path}")
    print(f"Tracking: {out_dir / 'tracking.csv'}")
    return rows
