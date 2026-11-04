"""Detect, mark and save the lines of one photo.

Run:  python 01_single_image.py input/folder/mysample/mysample_0000.jpg
"""
import sys
from pathlib import Path

from line_analysis import DetectionConfig, analyse_image

path = Path(sys.argv[1] if len(sys.argv) > 1 else "input/folder/mysample/mysample_0000.jpg")
res = analyse_image(path, Path("output/image") / path.stem, DetectionConfig(), plot=True)
print(f"{len(res['lines'])} lines at x = {[round(x) for x in res['lines']]}")
