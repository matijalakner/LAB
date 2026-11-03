"""Pure logic that runs without any instrument."""
from pathlib import Path

import pytest

from equipment.capture import CaptureLog, capture_folder, next_index, numbered_path
from equipment.experiments.ramp_camera import photo_times
from equipment.thorlabs import common
from equipment.ramp import ramp_levels, ramp_sequence
from equipment.thorlabs.dc2200 import _read_cfg
from equipment.utils import match_choice, output_csv_path, read_cfg


def test_ramp_levels_end_exactly_on_max():
    assert ramp_levels(0, 0.5, 0.1) == [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    assert ramp_levels(0, 0.25, 0.1) == [0, 0.1, 0.2, 0.25]


def test_ramp_sequence_does_not_repeat_max_or_cycle_start():
    seq = ramp_sequence([0, 0.1, 0.2], cycles=2)
    assert [i for _, _, i in seq] == [0, 0.1, 0.2, 0.1, 0, 0.1, 0.2, 0.1, 0]
    assert seq[2] == (1, "up", 0.2) and seq[3] == (1, "down", 0.1)


def test_ramp_cfg_limits():
    with pytest.raises(ValueError):
        _read_cfg({"i_min": 0, "i_max": 2.5, "step": 0.1, "step_time": 1})
    p = _read_cfg({"i_min": 0, "i_max": 1, "step": 0.1, "step_time": 1,
                   "dc2200_serial": "M42"})
    assert p["resource"].endswith("::M42::0::INSTR")


def test_photo_times():
    assert photo_times(3, 10) == [5, 15, 25]
    assert photo_times(3, 10, photo_delay=1) == [1, 11, 21]
    assert photo_times(2, 10, photo_interval=6) == [0, 6, 12, 18]
    with pytest.raises(ValueError):
        photo_times(3, 10, photo_delay=10)


def test_resource_serial_precedence(monkeypatch):
    monkeypatch.delenv("EQUIPMENT_DC2200_SERIAL", raising=False)
    assert common.dc2200_resource() == common.DC2200_RESOURCE
    monkeypatch.setenv("EQUIPMENT_DC2200_SERIAL", "ENV1")
    assert "::ENV1::" in common.dc2200_resource()
    assert "::ARG1::" in common.dc2200_resource("ARG1")
    monkeypatch.setenv("EQUIPMENT_PM400_SERIAL", "PENV")
    assert common.pm_resource().startswith("USB0::4883::32885::PENV")


def test_numbering_continues(tmp_path):
    folder = capture_folder("run1", tmp_path)
    assert folder == tmp_path / "folder" / "run1"
    folder.mkdir(parents=True)
    assert next_index(folder, "run1") == 0
    for i in (0, 1, 7):
        numbered_path(folder, "run1", i, ".jpg").touch()
    (folder / "run10_0099.jpg").touch()          # another name: ignored
    assert next_index(folder, "run1") == 8


def test_unsafe_names_are_refused():
    for bad in ("../x", "a/b", "", " x"):
        with pytest.raises(ValueError):
            capture_folder(bad)


def test_capture_log(tmp_path):
    log = CaptureLog(tmp_path / "log.csv")
    log.add(0, "a/run_0000.jpg", log.t0 + 1.5, "2026-01-01T00:00:00.000Z")
    log.close()
    lines = (tmp_path / "log.csv").read_text().splitlines()
    assert lines[0].startswith("time_stamp,") and lines[1] == "time_s,index,file,utc"
    assert lines[2] == "1.5,0,run_0000.jpg,2026-01-01T00:00:00.000Z"


def test_match_choice():
    shutter = ["1/500", "1/250", "1/125", "0.5", "2"]
    assert match_choice("1/250", shutter) == "1/250"
    assert match_choice("0.004", shutter) == "1/250"
    assert match_choice("1/250s", shutter) == "1/250"
    assert match_choice("day", ["Auto", "Daylight", "Shade"]) == "Daylight"
    with pytest.raises(ValueError):
        match_choice("1/1000", shutter)


def test_output_csv_path():
    assert output_csv_path("out", "pm", "a.csv") == Path("out/pm/a.csv")
    assert output_csv_path("out", "pm", "x/a.csv") == Path("x/a.csv")
    assert output_csv_path("out", "pm").name.startswith("pm_")


def test_read_cfg():
    from types import SimpleNamespace
    assert read_cfg({"a": 1})("a") == 1 and read_cfg({"a": 1})("b") is None
    assert read_cfg(SimpleNamespace(a=2))("a") == 2 and read_cfg(None)("a") is None


def test_flir_exposure_parsing():
    pytest.importorskip("cv2")
    from equipment.flir.camera import parse_exposure_us
    assert parse_exposure_us("1/250") == pytest.approx(4000)
    assert parse_exposure_us("4ms") == pytest.approx(4000)
    assert parse_exposure_us("250us") == pytest.approx(250)
    assert parse_exposure_us("auto") == "Continuous"
