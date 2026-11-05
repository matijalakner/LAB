"""Shared by every camera: file numbering and the capture log.

Photos and videos go to  <input_dir>/folder/<name>/<name>_XXXX.<ext>,
numbered from 0000; numbering continues after the files already in the folder,
so nothing is ever overwritten. Every run writes a capture log

    time_stamp,<UTC time at the start>
    time_s, index, file, utc
"""
import csv
import re
import time
from pathlib import Path

from .paths import input_root
from .utils import utc_timestamp

LOG_HEADER = ["time_s", "index", "file", "utc"]
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# file names
# ---------------------------------------------------------------------------
def capture_folder(name, input_dir=None):
    if not _SAFE_NAME.match(str(name)):
        raise ValueError(f"name '{name}' may only contain letters, digits, '.', '_' and '-'")
    return input_root(input_dir) / "folder" / name


def next_index(folder, name):
    """First free number XXXX for <name>_XXXX.* in ``folder`` (0 for an empty folder)."""
    pattern = re.compile(rf"^{re.escape(name)}_(\d{{4,}})\.[A-Za-z0-9]+$")
    used = [int(m.group(1)) for p in Path(folder).glob(f"{name}_*")
            if (m := pattern.match(p.name))]
    return max(used) + 1 if used else 0


def numbered_path(folder, name, index, suffix):
    return Path(folder) / f"{name}_{index:04d}{suffix}"


# ---------------------------------------------------------------------------
# capture log
# ---------------------------------------------------------------------------
class CaptureLog:
    """Capture log written row by row, so an interrupted run keeps its data.

    ``time_s`` counts from start() (the time stamp line); ``utc`` is the
    computer time at the moment the capture was started.
    """

    def __init__(self, path):
        self.path = Path(path) if path else None
        self._f = None
        self.start()

    def start(self):
        self.t0, self.time_stamp = time.monotonic(), utc_timestamp()

    def add(self, index, file, t, utc):
        if not self.path:
            return
        if self._f is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._f = open(self.path, "w", newline="", encoding="utf-8")
            self._w = csv.writer(self._f)
            self._w.writerow(["time_stamp", self.time_stamp])
            self._w.writerow(LOG_HEADER)
        self._w.writerow([round(t - self.t0, 3), index, Path(file).name, utc])
        self._f.flush()

    def close(self):
        if self._f:
            self._f.close()
            self._f = None


def _report(saved, folder, log):
    if saved:
        print(f"{len(saved)} file(s) in '{folder}/'.")
    if log.path and log._f is not None:
        print(f"Capture log: {log.path}")
