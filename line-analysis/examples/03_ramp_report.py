"""Folder analysis and report for a ramp taken with equipment.

Measure first, e.g.:
    equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 30 \
        --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off --power

Run:  python 03_ramp_report.py mysample
"""
import sys

from line_analysis import main_folder, main_report

name = sys.argv[1] if len(sys.argv) > 1 else "mysample"
main_folder(name, interactive=False, show=False)      # interactive=True asks "Is this okay?"
out = main_report(name)
print(f"{out['photos']} photos matched by {out['matched_by']}; power: {out['power_source']}")
print(out["table"].head())
