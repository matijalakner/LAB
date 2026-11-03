"""Light sources behind one small interface, so any of them can be paired with any
measuring instrument or camera (see ramp.py, experiments/paired_ramp.py, thorlabs/liv.py).

    with make_source("pe300", {"channels": "ABC"}) as light:   # connects; off on exit
        light.prepare(limit=50)        # safety limit (DC2200: user current limit)
        light.set_level(10)            # % for the pE-300, A for the DC2200
        light.switch_on()
        ...

Every source has:
    key, name     "pe300", "pE-300 (channels ABC)"
    unit          "A" or "%"
    column        CSV column of the level: "current_A" or "intensity_pct"
    max_level     highest allowed level (2 A, 100 %)
    quantize(x)   the level the device can actually set (pE-300: whole percent)
    fmt(x)        "250.00 mA", "50 %"

The context manager always switches the output off when it is left (end of
run, error, Ctrl+C), unless ``leave_on`` was set (used by ``set``).
"""
from importlib import import_module

# key -> (module, class); imported lazily so a missing driver library only
# matters for the source that needs it.
SOURCES = {
    "dc2200": ("thorlabs.dc2200", "DC2200Source"),
    "pe300": ("coolled.pe300", "PE300Source"),
}


class LightSource:
    key = "source"
    name = "light source"
    unit = ""
    column = "level"
    max_level = float("inf")

    leave_on = False

    # -- to implement ------------------------------------------------------------
    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def set_level(self, level):
        raise NotImplementedError

    def switch_on(self):
        raise NotImplementedError

    def switch_off(self):
        raise NotImplementedError

    def prepare(self, limit=None):
        """Called once before switching on; ``limit`` is the highest level of the run."""

    # -- shared --------------------------------------------------------------------
    def quantize(self, level):
        return level

    def fmt(self, level):
        return f"{level:g} {self.unit}"

    def check_level(self, level, what="level"):
        if not 0 <= level <= self.max_level:
            raise ValueError(f"{what} must be between 0 and {self.max_level:g} {self.unit} "
                             f"for the {self.name}")
        return self.quantize(level)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        try:
            if not self.leave_on:
                self.switch_off()
        finally:
            self.close()
        return False


def source_class(key):
    try:
        module, cls = SOURCES[key]
    except KeyError:
        raise ValueError(f"unknown light source '{key}'; choose one of: "
                         + ", ".join(SOURCES)) from None
    return getattr(import_module(f"{__package__}.{module}"), cls)


def make_source(key, cfg=None):
    """Light source ``key`` configured from cfg (dict or object): dc2200_serial for
    the DC2200; port and channels for the pE-300."""
    return source_class(key).from_cfg(cfg or {})
