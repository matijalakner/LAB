"""End to end: the real ``equipment`` CLI runs a ramp with photos and power (fake
hardware that photographs synthetic lines whose spacing follows the light level),
then ``analysis`` reads what equipment wrote. Skipped if equipment is not installed."""
import contextlib

import numpy as np
import pytest

equipment = pytest.importorskip("equipment")
from equipment import cli as equipment_cli                         # noqa: E402
from equipment.experiments import paired_ramp                       # noqa: E402
from equipment.sources import LightSource                           # noqa: E402

from line_analysis import cli                                        # noqa: E402
from line_analysis.report import main_report                         # noqa: E402
from conftest import save_photo                                      # noqa: E402


def fake_source_class(column, unit, max_level):
    class FakeSource(LightSource):
        key, name = "fake", "fake light"
        level, on = 0.0, False

        def open(self):
            pass

        def close(self):
            pass

        def set_level(self, level):
            type(self).level = level

        def switch_on(self):
            type(self).on = True

        def switch_off(self):
            type(self).on = False

        @classmethod
        def from_cfg(cls, cfg):
            return cls()

    FakeSource.column, FakeSource.unit, FakeSource.max_level = column, unit, max_level
    return FakeSource


class LineCamera:
    """Photographs lines 40 + scale * level px apart."""
    photo_suffix = ".png"

    def __init__(self, source, scale):
        self.source, self.scale, self.n = source, scale, 0

    def set_capture_target(self, card):
        pass

    def drain_events(self, seconds=0.0, until_complete=False):
        import time
        time.sleep(min(seconds, 0.002))

    def capture_photo(self, dest, keep_on_card=False):
        save_photo(dest, 40 + self.scale * self.source.level, seed=self.n)
        self.n += 1

    def close(self):
        pass


class Meter:
    def __init__(self, source):
        self.source = source

    def read_power(self):
        return 1e-4 * self.source.level


@pytest.fixture
def rig(monkeypatch):
    def install(column, unit, max_level, scale):
        src = fake_source_class(column, unit, max_level)
        monkeypatch.setattr(paired_ramp, "source_class", lambda key: src)
        monkeypatch.setattr(paired_ramp, "make_source", lambda key, cfg=None: src())
        cam = LineCamera(src, scale)
        monkeypatch.setattr(paired_ramp, "_connect_flir", lambda get: cam)
        monkeypatch.setattr(paired_ramp, "_connect_canon", lambda get: cam)
        monkeypatch.setattr(paired_ramp, "_open_power_meter",
                            lambda get: contextlib.nullcontext(Meter(src)))
        return src
    return install


@pytest.mark.parametrize("source, column, label, mx, step, scale", [
    ("pe300", "intensity_pct", "intensity[%]", 30, 10, 1.0),
    ("dc2200", "current_A", "current[A]", 0.3, 0.1, 100.0),
])
def test_ramp_with_photos_and_power_then_analysis(rig, tmp_path, source, column, label,
                                                   mx, step, scale):
    src = rig(column, "%" if source == "pe300" else "A", 100 if source == "pe300" else 2,
              scale)
    inp, out = tmp_path / "input", tmp_path / "output"
    equipment_cli.main([source, "ramp", "--min", "0", "--max", str(mx), "--step", str(step),
                        "--step-time", "0.15", "--photos", "run", "--camera", "flir",
                        "--power", "--input-dir", str(inp), "--output-dir", str(out)])
    assert not src.on
    photos = sorted((inp / "folder" / "run").glob("*.png"))
    assert len(photos) == 7                                    # 0 1 2 3 2 1 0

    cli.main(["folder", "run", "--yes", "--no-show", "--input-dir", str(inp),
              "--output-dir", str(out)])
    rep = main_report("run", output_dir=out)
    t = rep["table"]
    assert rep["matched_by"] == "photo log" and rep["level"] == column
    assert len(t) == 7 and (t["warning"] == "").all()
    assert np.allclose(t["mean_spacing_px"], 40 + scale * t[label], atol=0.5)
    assert np.allclose(t["power[W]"], 1e-4 * t[label])
    assert list(t["direction"]) == ["up"] * 4 + ["down"] * 3
