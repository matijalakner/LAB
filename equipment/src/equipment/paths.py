"""Where the data goes: <data>/input (photos, videos) and <data>/output (logs).

The lab layout is

    LAB/
    ├── equipment/          this package
    ├── line-analysis/      reads what this package writes
    └── data/
        ├── input/          photos and videos  (input/folder/<name>/...)
        └── output/         logs (output/ramp/, output/pm/, output/liv/, output/camera/)

The data folder is the first of:
  1. ``--data-dir`` on the CLI, or the ``EQUIPMENT_DATA`` environment variable,
     or ``LINE_ANALYSIS_DATA`` (the one line-analysis uses, so one setting
     serves both);
  2. ``data/`` next to this package's folder (LAB/data when the package is
     installed with ``pip install -e`` from LAB/equipment);
  3. ``data/`` in the current folder.
``--input-dir`` / ``--output-dir`` (or the function arguments) still override it.
These are the same rules as line-analysis's paths.py, so both always agree.
"""
import os
from pathlib import Path

ENV_VAR = "EQUIPMENT_DATA"
SHARED_ENV_VAR = "LINE_ANALYSIS_DATA"
_PACKAGE_DIR = Path(__file__).resolve().parents[2]    # src/equipment/paths.py -> LAB/equipment


def data_dir():
    for var in (ENV_VAR, SHARED_ENV_VAR):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    lab = _PACKAGE_DIR.parent / "data"
    if (lab / "input").is_dir() or (lab / "output").is_dir():
        return lab
    return Path("data")


def input_root(input_dir=None):
    """``input_dir`` if given, else <data>/input."""
    return Path(input_dir).expanduser() if input_dir else data_dir() / "input"


def output_root(output_dir=None):
    """``output_dir`` if given, else <data>/output."""
    return Path(output_dir).expanduser() if output_dir else data_dir() / "output"
