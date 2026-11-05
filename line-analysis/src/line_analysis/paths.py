"""Where the data is: the ``input/`` and ``output/`` folders of equipment.

The expected lab layout is

    LAB/
    ├── equipment/          the equipment repository
    ├── line-analysis/      this repository
    └── data/
        ├── input/          photos and videos  (input/folder/<name>/...)
        └── output/         equipment logs, and the results of this package

The data folder is the first of:
  1. ``--data-dir`` on the CLI, or the ``LINE_ANALYSIS_DATA`` environment
     variable, or ``EQUIPMENT_DATA`` (the one equipment uses, so one setting
     serves both);
  2. ``data/`` next to this repository (LAB/data when the package is installed
     with ``pip install -e`` from LAB/line-analysis);
  3. ``data/`` in the current folder.
So photos are always read from .../data/input and results written to
.../data/output. These are the same rules as equipment's paths.py.
``--input-dir`` / ``--output-dir`` (or the function arguments) still override it.
"""
import os
from pathlib import Path

ENV_VAR = "LINE_ANALYSIS_DATA"
SHARED_ENV_VAR = "EQUIPMENT_DATA"
_REPO = Path(__file__).resolve().parents[2]       # src/line_analysis/paths.py -> repo


def data_dir():
    for var in (ENV_VAR, SHARED_ENV_VAR):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    lab = _REPO.parent / "data"
    if (lab / "input").is_dir() or (lab / "output").is_dir():
        return lab
    return Path("data")


def input_root(input_dir=None):
    """``input_dir`` if given, else <data>/input."""
    return Path(input_dir) if input_dir else data_dir() / "input"


def output_root(output_dir=None):
    """``output_dir`` if given, else <data>/output."""
    return Path(output_dir) if output_dir else data_dir() / "output"
