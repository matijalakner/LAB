"""Single-image analysis: load, detect, mark, save."""
import csv
from pathlib import Path

import numpy as np
from PIL import Image

from .detect import DetectionConfig, detect_lines, mark_image, plot_line_signal


def load_image(path):
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
                  save_marked=True):
    """Detect the vertical lines in one image file and save the results.

    Writes into ``out_dir`` (created if needed):
        <name>_marked.png   the image (same size) with the lines painted red
        <name>_lines.csv    line, x_px, spacing_px      (write_csv=True)
        <name>_signal.png   line-strength plot          (plot=True)

    Returns a dict with the line positions and the written paths.
    """
    config = config or DetectionConfig()
    image_path, out_dir = Path(image_path), Path(out_dir)
    img = load_image(image_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    height, width = img.shape[:2]
    xs, sig, threshold = detect_lines(img, config)

    name = image_path.stem
    marked_path = out_dir / f"{name}_marked.png"
    result = {"name": name, "width": width, "height": height, "lines": xs,
              "threshold": threshold, "marked_path": str(marked_path)}
    if save_marked:
        # compress_level=1: ~3x faster than the default for a file only 5 % bigger
        Image.fromarray(mark_image(img, xs, config.half_width)).save(marked_path,
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
