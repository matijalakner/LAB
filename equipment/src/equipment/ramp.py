"""Stepped ramp min -> max -> min for any light source (sources.py).

    with make_source("pe300") as light:
        rows = run_ramp(light, {"min": 0, "max": 50, "step": 5, "step_time": 2})

Every level is held for ``step_time`` seconds; the steps are timed from a clock,
so they do not drift. The maximum is not repeated and the ramp always ends
exactly on ``max`` (the last step up is shorter if needed). With
``final_hold`` the last level (back at ``min``) is held that many seconds longer
before the light is switched off; it stays one step in the CSV.

CSV (first line: time_stamp,<UTC time at the start of the ramp>):
    time_s, cycle, direction, <source column>      e.g. current_A or intensity_pct
"""
import math
import time

from .sources import make_source, source_class
from .utils import read_cfg, sleep_until, utc_timestamp, write_csv

MAX_STEPS = 100_000


def ramp_levels(i_min, i_max, step):
    """Levels of one upward ramp: i_min, i_min + step, ... , i_max.

    The last level is always exactly i_max; if (i_max - i_min) is not a
    multiple of step, the last step is simply shorter.
    """
    if step <= 0:
        raise ValueError("step must be > 0")
    if i_max < i_min:
        raise ValueError("max must be >= min")
    n = int(math.floor((i_max - i_min) / step + 1e-9))
    if n + 1 > MAX_STEPS:
        raise ValueError(f"too many steps ({n + 1}); use a larger step")
    levels = [round(min(i_min + i * step, i_max), 9) for i in range(n + 1)]
    if levels[-1] < i_max - 1e-9:
        levels.append(round(i_max, 9))
    return levels


def ramp_sequence(levels, cycles=1):
    """Ordered (cycle, direction, level) list: up to the maximum, then back down.

    The maximum is not repeated. Cycle 2 and later skip their first up level,
    because the previous cycle already ended on it.
    """
    seq = []
    for cycle in range(1, cycles + 1):
        up = levels if cycle == 1 else levels[1:]
        seq += [(cycle, "up", i) for i in up]
        seq += [(cycle, "down", i) for i in levels[-2::-1]]
    return seq


def read_ramp_cfg(cfg, source_cls=None):
    """Ramp settings from a dict or object.

    min/max/step may also be given as i_min/i_max/step (the DC2200 names).
    ``source_cls`` (a LightSource class) checks the levels against its range.
    """
    get = read_cfg(cfg)

    def value(*keys, default=None):
        for k in keys:
            if get(k) is not None:
                return get(k)
        if default is None:
            raise ValueError(f"ramp setting '{keys[0]}' is missing")
        return default

    p = {"min": float(value("min", "i_min")), "max": float(value("max", "i_max")),
         "step": float(value("step")), "step_time": float(value("step_time")),
         "cycles": int(value("cycles", default=1)), "output_csv": get("output_csv"),
         "final_hold": float(get("final_hold") or 0)}
    if p["min"] < 0:
        raise ValueError("min must be >= 0")
    if p["max"] < p["min"]:
        raise ValueError("max must be >= min")
    if source_cls is not None and p["max"] > source_cls.max_level:
        raise ValueError(f"max must be <= {source_cls.max_level:g} {source_cls.unit} "
                         f"for the {source_cls.name}")
    if p["step"] <= 0 or p["step_time"] <= 0:
        raise ValueError("step and step_time must be > 0")
    if p["cycles"] < 1:
        raise ValueError("cycles must be >= 1")
    if p["final_hold"] < 0:
        raise ValueError("final_hold must be >= 0 s")
    return p


def ramp_duration(p, n_steps):
    """Seconds from the first step until the light is switched off."""
    return n_steps * p["step_time"] + p["final_hold"]


def ramp_plan(p, source):
    """The (cycle, direction, level) sequence, with levels the source can set."""
    levels = []
    for x in ramp_levels(p["min"], p["max"], p["step"]):
        q = source.quantize(x)
        if not levels or q != levels[-1]:
            levels.append(q)
    return ramp_sequence(levels, p["cycles"])


def run_ramp(source, cfg, on_start=None, on_step=None):
    """Run the ramp on an OPEN source; the output is switched off at the end.

    Hooks: ``on_start(t0, time_stamp, sequence)`` right before the first step
    (t0 = time.monotonic() of the ramp start); ``on_step(k, cycle, direction,
    level)`` right after every level change. An exception in a hook stops the
    ramp (and the light). Returns rows (time_s, cycle, direction, level); with
    output_csv they are written there, also when the run is interrupted.
    """
    p = read_ramp_cfg(cfg, type(source))
    sequence = ramp_plan(p, source)
    header = ["time_s", "cycle", "direction", source.column]
    rows, time_stamp = [], None
    try:
        try:
            source.prepare(limit=p["max"])
            source.set_level(sequence[0][2])
            source.switch_on()
            hold = f" + {p['final_hold']:g} s at the end" if p["final_hold"] else ""
            print(f"{source.name}: {len(sequence)} steps x {p['step_time']:g} s{hold} = "
                  f"{ramp_duration(p, len(sequence)):g} s")
            time_stamp = utc_timestamp()
            t0 = time.monotonic()
            if on_start:
                on_start(t0, time_stamp, sequence)
            for k, (cycle, direction, level) in enumerate(sequence):
                sleep_until(t0 + k * p["step_time"])         # clock based, no drift
                source.set_level(level)
                rows.append((round(time.monotonic() - t0, 4), cycle, direction, level))
                if on_step:
                    on_step(k, cycle, direction, level)
                print(f"[{k + 1}/{len(sequence)}] cycle {cycle} {direction}: "
                      f"{source.fmt(level)}")
            sleep_until(t0 + len(sequence) * p["step_time"])   # hold the last step
            if p["final_hold"]:
                print(f"holding {source.fmt(sequence[-1][2])} for {p['final_hold']:g} s more")
                sleep_until(t0 + ramp_duration(p, len(sequence)))
        finally:
            source.switch_off()
    finally:
        if p["output_csv"] and rows:
            write_csv(p["output_csv"], header, rows, time_stamp)
            print(f"Data saved to {p['output_csv']}")
    return rows


def main_source_ramp(cfg, on_start=None, on_step=None):
    """Connect the source named by cfg['source'] (default dc2200) and run the ramp."""
    key = read_cfg(cfg)("source") or "dc2200"
    read_ramp_cfg(cfg, source_class(key))          # fail before connecting
    with make_source(key, cfg) as source:
        return run_ramp(source, cfg, on_start, on_step)
