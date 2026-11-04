"""Analyse a frame every 5 s of a video and plot the spacing against time.

A FLIR video's frame log (output/camera/flir_<UTC>_frames.csv) is found
automatically, so the times are the real ones even when frames were dropped.

Run:  python 02_video.py mysample_0002.mp4
"""
import sys
from pathlib import Path

from line_analysis import analyse_spacing, process_video

video = sys.argv[1] if len(sys.argv) > 1 else "mysample_0002.mp4"
process_video(video, interval=5.0)
out = analyse_spacing(Path(video).stem)
print(out["plot_path"])
