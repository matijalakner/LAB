"""Single-image analysis: load, detect, mark, save."""
import csv
from pathlib import Path

import numpy as np
from PIL import Image

from .detect import DetectionConfig, detect_lines, mark_grid, plot_line_signal


EDGE_CROP = 100   # px cut off the left and the right edge before the analysis


def load_image(path, middle=None, edge=0):
    """An image file as an 8-bit RGB array (H x W x 3).

    ``middle`` keeps only that many rows around the middle of the photo, and a
    photo with fewer rows raises ValueError. ``edge`` cuts that many columns off
    the left and the right side (dark, vignetted edges), so x positions in the
    result are ``edge`` px smaller than in the photo; a photo narrower than
    2 * edge + 100 px raises ValueError. See _read_image for the formats.
    """
    img = _read_image(path)
    if edge:
        width = img.shape[1]
        if width < 2 * edge + 100:
            raise ValueError(f"photo is only {width} px wide; cannot cut {edge} px "
                             "off each side (use a smaller edge crop)")
        img = img[:, edge:width - edge]
    if middle is None:
        return img
    height = img.shape[0]
    if height < middle:
        raise ValueError(f"photo has only {height} rows, {middle} needed")
    r0 = (height - middle) // 2
    return img[r0:r0 + middle]


def _read_image(path):
    """An image file as an 8-bit RGB array (H x W x 3).

    Handles what the cameras write: JPEG, 8-bit PNG/TIFF, and the 16-bit
    PNG/TIFF of the FLIR camera (BayerRG16 / Mono16), which are scaled to 8 bit
    because the detection thresholds are in 0-255 levels.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    import cv2
    arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if arr is None:                                    # a format OpenCV cannot read
        with Image.open(path) as pil:
            return np.asarray(pil.convert("RGB"))
    if arr.dtype == np.uint16:
        arr = (arr.astype(np.float32) / 257.0 + 0.5).astype(np.uint8)
    elif arr.dtype != np.uint8:
        lo, hi = float(arr.min()), float(arr.max())
        arr = ((arr - lo) / (hi - lo or 1) * 255).astype(np.uint8)
    if arr.ndim == 2:
        return np.stack([arr] * 3, axis=2)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return np.ascontiguousarray(arr[:, :, ::-1])      # BGR -> RGB


def analyse_image(image_path, out_dir, config=None, plot=False, write_csv=True,
                  save_marked=True, middle=None, edge=0):
    """Detect the vertical lines in one image file and save the results.

    Writes into ``out_dir`` (created if needed):
        <name>_marked.png   the image with the lines painted red (extra lines
                            cyan, missed ones dotted yellow, see mark_grid)
        <name>_lines.csv    line, x_px, spacing_px      (write_csv=True)
        <name>_signal.png   line-strength plot          (plot=True)

    ``middle`` analyses and writes only that many rows around the middle;
    ``edge`` cuts that many px off the left and right first (see load_image),
    so the marked image and the x positions are those of the cut image.

    Returns a dict with the line positions and the written paths.
    """
    config = config or DetectionConfig()
    image_path, out_dir = Path(image_path), Path(out_dir)
    img = load_image(image_path, middle, edge)
    out_dir.mkdir(parents=True, exist_ok=True)
    height, width = img.shape[:2]
    xs, sig, threshold = detect_lines(img, config)

    name = image_path.stem
    marked_path = out_dir / f"{name}_marked.png"
    result = {"name": name, "width": width, "height": height, "lines": xs,
              "threshold": threshold, "marked_path": str(marked_path),
              "edge_crop": edge}
    if save_marked:
        # compress_level=1: ~3x faster than the default for a file only 5 % bigger
        Image.fromarray(mark_grid(img, xs, config.half_width)).save(marked_path,
                                                                     compress_level=1)
    if write_csv:
        csv_path = out_dir / f"{name}_lines.csv"
        gaps = np.diff(xs)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["line", "x_px", "spacing_px"])
            for i, x in enumerate(xs):
                w.writerow([i + 1, round(x, 1),
                            "" if i == 0 else round(float(gaps[i - 1]), 1)])
        result["csv_path"] = str(csv_path)
    if plot:
        plot_path = out_dir / f"{name}_signal.png"
        plot_line_signal(sig, xs, threshold, plot_path)
        result["plot_path"] = str(plot_path)
    return result
