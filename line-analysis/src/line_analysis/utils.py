"""Small helpers: UTC time stamps and CSV files with a time stamp line.

The CSV convention is the one of the ``equipment`` package: the first line may be
``time_stamp,<UTC time at t = 0>``, the column header follows on the next line.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path


def utc_timestamp(compact=False):
    """Current UTC time, e.g. 2026-10-30T12:34:56.789Z (compact: 20261030T123456Z)."""
    now = datetime.now(timezone.utc)
    if compact:
        return now.strftime("%Y%m%dT%H%M%SZ")
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_csv(path, header, rows, time_stamp=None):
    """Write a CSV file (folder created if needed), optionally with a time stamp line."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if time_stamp is not None:
            w.writerow(["time_stamp", time_stamp])
        w.writerow(header)
        w.writerows(rows)
    return path


def read_time_stamp(path):
    """The UTC time on the ``time_stamp`` first line of a CSV, or None."""
    with open(path, newline="", encoding="utf-8") as f:
        row = next(csv.reader(f), [])
    return row[1] if len(row) > 1 and row[0] == "time_stamp" else None
