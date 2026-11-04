"""Where the data is: the ``input/`` and ``output/`` folders of equipment.

The expected lab layout is

    LAB/
    ├── equipment/          the equipment repository
    ├── line-analysis/      this repository
    └── data/
        ├── input/          photos and videos  (input/folder/<name>/...)
        └── output/         equipment logs, and the results of this package

The data folder is the first of:
  1. the ``LINE_ANALYSIS_DATA`` environment variable (or ``--data-dir`` on the CLI);
  2. ``data/`` next to this repository (LAB/data when the package is installed
     with ``pip install -e`` from LAB/line-analysis);
  3. ``data/`` in the current folder;
  4. the current folder itself (plain ``input/`` and ``output/``).
``--input-dir`` / ``--output-dir`` (or the function arguments) still override it.
"""
import os
from pathlib import Path

ENV_VAR = "LINE_ANALYSIS_DATA"
_REPO = Path(__file__).resolve().parents[2]       # src/line_analysis/paths.py -> repo


def data_dir():
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    for cand in (_REPO.parent / "data", Path.cwd() / "data"):
        if (cand / "input").is_dir() or (cand / "output").is_dir():
            return cand
    return Path(".")


def input_root(input_dir=None):
    """``input_dir`` if given, else <data>/input."""
    return Path(input_dir) if input_dir else data_dir() / "input"


def output_root(output_dir=None):
    """``output_dir`` if given, else <data>/output."""
    return Path(output_dir) if output_dir else data_dir() / "output"
