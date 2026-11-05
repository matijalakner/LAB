"""Small helpers shared by all instrument modules."""
import csv
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_timestamp(compact=False):
    """Current UTC time, e.g. 2026-10-30T12:34:56.789Z (compact: 20261030T123456Z)."""
    now = datetime.now(timezone.utc)
    if compact:
        return now.strftime("%Y%m%dT%H%M%SZ")
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_csv(path, header, rows, time_stamp=None):
    """Write a CSV file, creating the folder if needed.

    With ``time_stamp`` the first line of the file is ``time_stamp,<UTC time>``;
    the column header follows on line 2.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if time_stamp is not None:
            w.writerow(["time_stamp", time_stamp])
        w.writerow(header)
        w.writerows(rows)
    return path


def output_csv_path(output_dir, kind, output_csv=None):
    """Where a measurement CSV goes: <output_dir>/<kind>/<kind>_<UTC time>.csv.

    ``output_dir`` None means <data>/output (see paths.py).

    ``output_csv`` overrides the name. A plain file name is placed in
    <output_dir>/<kind>/; a name that already contains a folder is used as given.
    """
    from .paths import output_root
    output_dir = output_root(output_dir)
    if output_csv is None:
        return Path(output_dir) / kind / f"{kind}_{utc_timestamp(compact=True)}.csv"
    p = Path(output_csv)
    if p.parent == Path("."):
        return Path(output_dir) / kind / p.name
    return p


def read_cfg(cfg):
    """getter for a dict or an object (e.g. argparse.Namespace); missing keys give None."""
    if cfg is None:
        return lambda k: None
    if isinstance(cfg, dict):
        return cfg.get
    return lambda k: getattr(cfg, k, None)


# ---------------------------------------------------------------------------
# value matching
# ---------------------------------------------------------------------------
def _as_number(text):
    """'1/250' -> 0.004, '0.5' -> 0.5, '2"' -> 2, '100' -> 100; None if not a number."""
    s = str(text).strip().lower().rstrip('s"').strip()
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            return float(a) / float(b)
        return float(s)
    except (ValueError, ZeroDivisionError):
        return None


def match_choice(value, choices):
    """Find the camera choice that the user meant by ``value``.

    Exact text (case-insensitive) first, then the same number (so '1/250',
    '0.004' and '1/250s' all find '1/250'), then a unique partial text match
    ('daylight' finds 'Daylight', 'temp' finds 'Color Temperature').
    """
    choices = list(choices)
    want = str(value).strip()
    for c in choices:
        if c.lower() == want.lower():
            return c
    num = _as_number(want)
    if num is not None:
        for c in choices:
            cn = _as_number(c)
            if cn is not None and abs(cn - num) <= 1e-3 * max(abs(num), 1e-9):
                return c
    partial = [c for c in choices if want.lower() in c.lower()]
    if len(partial) == 1:
        return partial[0]
    raise ValueError(f"'{value}' is not offered by the camera; choose one of: "
                     + ", ".join(choices))


def sleep_until(deadline):
    """Sleep until a time.monotonic() deadline (no accumulated drift)."""
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def close_quietly(obj):
    close = getattr(obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
