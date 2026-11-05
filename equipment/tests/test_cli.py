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
    for device in ("devices", "dc2200", "pe300", "pm400", "liv", "canon", "flir"):
        assert device in out


def test_importing_the_cli_loads_no_hardware_library():
    code = ("import sys, equipment.cli; "
            "bad = {'cv2', 'numpy', 'gphoto2', 'usb', 'pyvisa', 'PySpin', 'serial'} "
            "& set(sys.modules); "
            "print(', '.join(sorted(bad)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == "", f"loaded at import time: {out}"


@pytest.mark.parametrize("argv", [
    ["dc2200", "-h"], ["dc2200", "ramp", "-h"], ["pe300", "-h"], ["pe300", "ramp", "-h"],
    ["pe300", "set", "-h"], ["pm400", "measure", "-h"], ["liv", "-h"],
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
    assert target == "ramp:main_source_ramp"
    assert cfg["source"] == "dc2200"
    assert cfg["min"] == 0 and cfg["max"] == 0.5 and cfg["step"] == 0.05
    assert cfg["step_time"] == 2 and cfg["cycles"] == 3
    assert Path(cfg["output_csv"]) == tmp_path / "ramp" / "run1.csv"


def test_dc2200_ramp_default_csv_name(calls, data_folder):
    _, cfg = run(calls, "dc2200", "ramp", "--min", "0", "--max", "0.5", "--step", "0.1",
                 "--step-time", "1")
    p = Path(cfg["output_csv"])
    assert p.parent == data_folder / "output" / "ramp" and p.name.startswith("ramp_")


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
    assert target == "experiments.paired_ramp:main_paired_ramp"
    assert cfg["camera"] == "mysample" and cfg["camera_type"] == "canon"
    assert "power" not in cfg
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
def test_pm400_measure(calls, device, data_folder):
    target, cfg = run(calls, device, "measure", "--wavelength", "633", "--duration", "2",
                      "--rate", "5", "--pm400-serial", "P1")
    assert target == "thorlabs.pm400:main_power_measurement"
    assert cfg["wavelength"] == 633 and cfg["sample_duration"] == 2
    assert cfg["sample_rate"] == 5 and cfg["pm400_serial"] == "P1"
    assert Path(cfg["output_csv"]).parent == data_folder / "output" / "pm"


def test_pm400_old_option_names(calls):
    _, cfg = run(calls, "pm400", "measure", "--sample-duration", "3", "--sample-rate", "2")
    assert cfg["sample_duration"] == 3 and cfg["sample_rate"] == 2


def test_liv(calls, data_folder):
    target, cfg = run(calls, "liv", "--i-max", "0.05", "--ramp-duration", "10",
                      "--output-csv", "liv_run1.csv")
    assert target == "experiments.liv:main_liv_measurement"
    assert cfg["source"] == "dc2200"
    assert cfg["i_min"] == 0 and cfg["i_max"] == 0.05
    assert Path(cfg["output_csv"]) == data_folder / "output" / "liv" / "liv_run1.csv"


# -- Canon -------------------------------------------------------------------
def test_canon_info(calls):
    assert run(calls, "canon", "info") == ("canon.capture:main_camera_info",
                                           {"sync_clock": False})


def test_canon_photo(calls, data_folder):
    target, cfg = run(calls, "canon", "photo", "sample-1", "-i", "--shutter", "1/250",
                      "--iso", "200", "--color-temp", "5200")
    assert target == "canon.capture:main_photo"
    assert cfg["name"] == "sample-1" and cfg["interactive"] is True
    assert cfg["colortemperature"] == "5200"
    assert Path(cfg["input_dir"]) == data_folder / "input"


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


# -- pE-300 ------------------------------------------------------------------
def test_pe300_set(calls):
    target, cfg = run(calls, "pe300", "set", "40", "--channels", "c,a", "--port", "/dev/x")
    assert target == "coolled.pe300:main_pe300_set"
    assert cfg == {"intensity": 40, "channels": "AC", "hold": None, "port": "/dev/x"}


@pytest.mark.parametrize("argv,target", [
    (["pe300", "off"], "coolled.pe300:main_pe300_off"),
    (["pe", "status"], "coolled.pe300:main_pe300_status")])
def test_pe300_off_status(calls, argv, target):
    assert run(calls, *argv)[0] == target


def test_pe300_ramp(calls):
    target, cfg = run(calls, "pe300", "ramp", "--min", "0", "--max", "100", "--step", "10",
                      "--step-time", "2", "--channels", "B")
    assert target == "ramp:main_source_ramp"
    assert cfg["source"] == "pe300" and cfg["max"] == 100 and cfg["channels"] == "B"
    assert "dc2200_serial" not in cfg


@pytest.mark.parametrize("argv", [
    ["pe300", "set", "101"],
    ["pe300", "set", "50", "--channels", "D"],
    ["pe300", "ramp", "--min", "0", "--max", "120", "--step", "10", "--step-time", "1"],
    ["pe300", "ramp", "--min", "0", "--max", "50", "--step", "0.5", "--step-time", "1"],
    ["pe300", "ramp", "--min", "0", "--max", "50", "--step", "5", "--step-time", "1",
     "--dc2200-serial", "x"],
    ["pe300", "ramp", "--min", "0", "--max", "50", "--step", "5", "--step-time", "1",
     "--wavelength", "470"],                                   # PM400 option without --power
    ["pe300", "ramp", "--min", "0", "--max", "50", "--step", "5", "--step-time", "1",
     "--power", "--power-delay", "1"],                          # not shorter than the step
    ["liv", "--source", "pe300", "--max", "120"],
    ["liv", "--source", "dc2200", "--channels", "A"],
    ["liv", "--source", "pe300", "--dc2200-serial", "x"],
])
def test_pe300_invalid(calls, argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2 and calls == []


# -- pairing -----------------------------------------------------------------
def test_pe300_with_pm400(calls):
    target, cfg = run(calls, "pe300", "ramp", "--min", "0", "--max", "100", "--step", "10",
                      "--step-time", "5", "--power", "--wavelength", "470",
                      "--power-interval", "1")
    assert target == "experiments.paired_ramp:main_paired_ramp"
    assert cfg["power"] is True and cfg["wavelength"] == 470 and cfg["power_interval"] == 1
    assert "camera" not in cfg


def test_pe300_with_flir_and_pm400(calls):
    _, cfg = run(calls, "pe300", "ramp", "--min", "0", "--max", "100", "--step", "10",
                 "--step-time", "5", "--photos", "s1", "--camera", "flir", "--gain", "0",
                 "--power")
    assert cfg["camera"] == "s1" and cfg["camera_type"] == "flir" and cfg["gain"] == "0"
    assert cfg["power"] is True and cfg["source"] == "pe300"


def test_dc2200_with_pm400(calls):
    _, cfg = run(calls, "dc2200", "ramp", "--min", "0", "--max", "1", "--step", "0.1",
                 "--step-time", "5", "--power", "--pm400-serial", "P9")
    assert cfg["source"] == "dc2200" and cfg["power"] and cfg["pm400_serial"] == "P9"


def test_liv_with_pe300(calls):
    target, cfg = run(calls, "liv", "--source", "pe300", "--channels", "ab")
    assert target == "experiments.liv:main_liv_measurement"
    assert cfg["source"] == "pe300" and cfg["i_max"] == 100 and cfg["channels"] == "AB"


def test_pe300_ramp_with_hold(calls):
    _, cfg = run(calls, "pe300", "ramp", "--channels", "B", "--hold", "c=1", "--min", "0",
                 "--max", "100", "--step", "1", "--step-time", "5")
    assert cfg["channels"] == "B" and cfg["hold"] == "C=1"


@pytest.mark.parametrize("argv", [
    ["pe300", "ramp", "--channels", "B", "--hold", "B=1", "--min", "0", "--max", "10",
     "--step", "1", "--step-time", "1"],                       # held and ramped
    ["pe300", "ramp", "--hold", "C=1", "--min", "0", "--max", "10", "--step", "1",
     "--step-time", "1"],                                       # default channels ABC
    ["pe300", "set", "10", "--channels", "B", "--hold", "C=200"],
    ["pe300", "set", "10", "--channels", "B", "--hold", "C"],
    ["liv", "--source", "dc2200", "--hold", "C=1"],
])
def test_pe300_hold_invalid(calls, argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2 and calls == []


# -- where the data goes -------------------------------------------------------
def test_data_dir_option(calls, tmp_path, monkeypatch):
    monkeypatch.delenv("EQUIPMENT_DATA")
    _, cfg = run(calls, "--data-dir", str(tmp_path / "lab"), "pe300", "ramp", "--min", "0",
                 "--max", "10", "--step", "5", "--step-time", "1", "--photos", "s1",
                 "--camera", "flir")
    assert Path(cfg["output_csv"]).parent == tmp_path / "lab" / "output" / "ramp"
    assert Path(cfg["input_dir"]) == tmp_path / "lab" / "input"


def test_input_and_output_dir_still_override(calls, tmp_path):
    _, cfg = run(calls, "flir", "photo", "s", "--input-dir", str(tmp_path / "i"),
                 "--output-dir", str(tmp_path / "o"))
    assert Path(cfg["input_dir"]) == tmp_path / "i"
    assert Path(cfg["output_csv"]).parent == tmp_path / "o" / "camera"
