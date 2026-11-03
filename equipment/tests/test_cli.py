"""The parser: every command maps to the right function with the right settings.

No hardware and no hardware library is needed: the call to the instrument code
is replaced by a recorder.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from equipment import cli


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_call", lambda target, cfg=None: seen.append((target, cfg)))
    return seen


def run(calls, *argv):
    cli.main(list(argv))
    assert len(calls) == 1
    return calls[0]


def test_help_works_without_hardware_libraries():
    out = subprocess.run([sys.executable, "-m", "equipment", "--help"],
                         capture_output=True, text=True, check=True).stdout
    for device in ("devices", "dc2200", "pm400", "liv", "canon", "flir"):
        assert device in out


def test_importing_the_cli_loads_no_hardware_library():
    code = ("import sys, equipment.cli; "
            "bad = {'cv2', 'numpy', 'gphoto2', 'usb', 'pyvisa', 'PySpin'} & set(sys.modules); "
            "print(', '.join(sorted(bad)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == "", f"loaded at import time: {out}"


@pytest.mark.parametrize("argv", [
    ["dc2200", "-h"], ["dc2200", "ramp", "-h"], ["pm400", "measure", "-h"], ["liv", "-h"],
    ["canon", "timelapse", "-h"], ["flir", "video", "-h"]])
def test_every_help_page(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 0
    assert "usage: equipment" in capsys.readouterr().out


# -- DC2200 ------------------------------------------------------------------
def test_dc2200_set(calls):
    target, cfg = run(calls, "dc2200", "set", "0.25", "--dc2200-serial", "M1")
    assert target == "thorlabs.dc2200:main_set_current"
    assert cfg == {"current": 0.25, "dc2200_serial": "M1"}


def test_dc2200_off(calls):
    _, cfg = run(calls, "dc2200", "off")
    assert cfg["current"] == 0.0


@pytest.mark.parametrize("argv", [
    ["dc2200", "set", "2.5"],
    ["dc2200", "set", "-0.1"],
    ["dc2200", "ramp", "--min", "0", "--max", "3", "--step", "0.1", "--step-time", "1"],
    ["dc2200", "ramp", "--min", "0.5", "--max", "0.1", "--step", "0.1", "--step-time", "1"],
    ["dc2200", "ramp", "--min", "0", "--max", "1", "--step", "0", "--step-time", "1"],
    ["dc2200", "ramp", "--min", "0", "--max", "1", "--step", "0.1"],
    ["liv", "--max", "2.5"],
    ["liv", "--update-rate", "10", "--settle-time", "0.2"],
])
def test_unsafe_or_invalid_values_are_refused(calls, argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
    assert calls == []


def test_dc2200_ramp(calls, tmp_path):
    target, cfg = run(calls, "dc2200", "ramp", "--min", "0", "--max", "0.5", "--step",
                      "0.05", "--step-time", "2", "--cycles", "3",
                      "--output-dir", str(tmp_path), "--output-csv", "run1.csv")
    assert target == "thorlabs.dc2200:main_ramp"
    assert cfg["i_min"] == 0 and cfg["i_max"] == 0.5 and cfg["step"] == 0.05
    assert cfg["step_time"] == 2 and cfg["cycles"] == 3
    assert Path(cfg["output_csv"]) == tmp_path / "ramp" / "run1.csv"


def test_dc2200_ramp_default_csv_name(calls):
    _, cfg = run(calls, "dc2200", "ramp", "--min", "0", "--max", "0.5", "--step", "0.1",
                 "--step-time", "1")
    p = Path(cfg["output_csv"])
    assert p.parent == Path("output/ramp") and p.name.startswith("ramp_")


def test_ramp_camera_option_without_photos_is_refused(calls):
    with pytest.raises(SystemExit):
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.5", "--step", "0.1",
                  "--step-time", "1", "--shutter", "1/250"])
    assert calls == []


def test_ramp_with_canon_photos(calls):
    target, cfg = run(calls, "dc2200", "ramp", "--min", "0.05", "--max", "1", "--step",
                      "0.05", "--step-time", "100", "--photos", "mysample",
                      "--shutter", "1/250", "--iso", "100", "--wb", "Daylight",
                      "--sync-clock", "--photo-delay", "10")
    assert target == "experiments.ramp_camera:main_ramp_camera"
    assert cfg["camera"] == "mysample" and cfg["camera_type"] == "canon"
    assert cfg["shutter"] == "1/250" and cfg["iso"] == "100"
    assert cfg["whitebalance"] == "Daylight" and cfg["sync_clock"] is True
    assert cfg["photo_delay"] == 10 and cfg["photo_interval"] is None
    assert "gain" not in cfg


def test_ramp_with_flir_photos(calls):
    _, cfg = run(calls, "dc2200", "ramp", "--min", "0.05", "--max", "1", "--step", "0.05",
                 "--step-time", "100", "--photos", "s1", "--camera", "flir",
                 "--exposure", "4ms", "--gain", "0", "--wb", "off", "--serial", "123",
                 "--photo-interval", "5")
    assert cfg["camera_type"] == "flir" and cfg["shutter"] == "4ms"
    assert cfg["gain"] == "0" and cfg["serial"] == "123" and cfg["photo_interval"] == 5
    assert "iso" not in cfg


@pytest.mark.parametrize("argv", [
    ["--camera", "canon", "--gain", "0"],
    ["--camera", "flir", "--iso", "100"],
    ["--photo-delay", "1", "--photo-interval", "2"],
    ["--photo-delay", "5"],          # not shorter than the 5 s step
])
def test_ramp_photo_option_conflicts(calls, argv):
    with pytest.raises(SystemExit):
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.5", "--step", "0.1",
                  "--step-time", "5", "--photos", "x", *argv])
    assert calls == []


# -- PM400 / LIV -------------------------------------------------------------
@pytest.mark.parametrize("device", ["pm400", "pm"])
def test_pm400_measure(calls, device):
    target, cfg = run(calls, device, "measure", "--wavelength", "633", "--duration", "2",
                      "--rate", "5", "--pm400-serial", "P1")
    assert target == "thorlabs.pm400:main_power_measurement"
    assert cfg["wavelength"] == 633 and cfg["sample_duration"] == 2
    assert cfg["sample_rate"] == 5 and cfg["pm400_serial"] == "P1"
    assert Path(cfg["output_csv"]).parent == Path("output/pm")


def test_pm400_old_option_names(calls):
    _, cfg = run(calls, "pm400", "measure", "--sample-duration", "3", "--sample-rate", "2")
    assert cfg["sample_duration"] == 3 and cfg["sample_rate"] == 2


def test_liv(calls):
    target, cfg = run(calls, "liv", "--i-max", "0.05", "--ramp-duration", "10",
                      "--output-csv", "liv_run1.csv")
    assert target == "thorlabs.liv:main_liv_measurement"
    assert cfg["i_min"] == 0 and cfg["i_max"] == 0.05
    assert Path(cfg["output_csv"]) == Path("output/liv/liv_run1.csv")


# -- Canon -------------------------------------------------------------------
def test_canon_info(calls):
    assert run(calls, "canon", "info") == ("canon.capture:main_camera_info",
                                           {"sync_clock": False})


def test_canon_photo(calls):
    target, cfg = run(calls, "canon", "photo", "sample-1", "-i", "--shutter", "1/250",
                      "--iso", "200", "--color-temp", "5200")
    assert target == "canon.capture:main_photo"
    assert cfg["name"] == "sample-1" and cfg["interactive"] is True
    assert cfg["colortemperature"] == "5200" and cfg["input_dir"] == "input"


def test_canon_timelapse(calls):
    target, cfg = run(calls, "canon", "timelapse", "s", "-n", "5", "--duration", "1200")
    assert target == "canon.capture:main_timelapse"
    assert cfg["interval"] == 5 and cfg["duration"] == 1200 and cfg["count"] is None


def test_canon_video(calls):
    target, cfg = run(calls, "canon", "video", "s", "--duration", "60", "--delete-from-card")
    assert target == "canon.capture:main_video"
    assert cfg["duration"] == 60 and cfg["delete_from_card"] is True


# -- FLIR --------------------------------------------------------------------
def test_flir_list(calls):
    assert run(calls, "flir", "list", "--backend", "aravis") == (
        "flir.capture:main_flir_list", {"backend": "aravis"})


def test_flir_photo_defaults(calls):
    target, cfg = run(calls, "flir", "photo", "s")
    assert target == "flir.capture:main_flir_photo"
    assert cfg["backend"] == "auto" and cfg["save_format"] == "jpg" and cfg["quality"] == 95
    assert Path(cfg["output_csv"]).name.startswith("flir_")


def test_flir_video(calls):
    target, cfg = run(calls, "flir", "video", "s", "--fps", "20", "--duration", "60",
                      "--pixel-format", "BayerRG16", "--save-format", "png")
    assert target == "flir.capture:main_flir_video"
    assert cfg["fps"] == 20 and cfg["pixel_format"] == "BayerRG16"


def test_flir_wb_choices(calls):
    with pytest.raises(SystemExit):
        cli.main(["flir", "photo", "s", "--wb", "daylight"])


# -- errors ------------------------------------------------------------------
def test_errors_are_short_without_debug(monkeypatch):
    def boom(target, cfg=None):
        raise RuntimeError("DC2200 not found")
    monkeypatch.setattr(cli, "_call", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["dc2200", "off"])
    assert e.value.code == "Error: DC2200 not found"
    with pytest.raises(RuntimeError):
        cli.main(["--debug", "dc2200", "off"])


def test_ctrl_c_message(monkeypatch):
    def interrupt(target, cfg=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "_call", interrupt)
    with pytest.raises(SystemExit) as e:
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.1", "--step", "0.1",
                  "--step-time", "1"])
    assert "switched off" in e.value.code
