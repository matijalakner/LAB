"""Micrometers per pixel from the camera and the objective."""
import pytest
from PIL import Image

from line_analysis import calibration, cli
from line_analysis.report import choose_px_to_um, detect_camera, main_report
from test_equipment_files import make_photos, make_ramp


def photo(path, make):
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    Image.new("RGB", (20, 10), (128, 128, 128)).save(path, exif=exif)


def test_calculated_values():
    assert calibration.px_to_um("flir", "4x")[0] == pytest.approx(1.125)
    assert calibration.px_to_um("flir", "10x")[0] == pytest.approx(0.45)
    assert calibration.px_to_um("FLIR", "10X")[0] == pytest.approx(0.45)
    assert calibration.px_to_um("canon", "10x")[0] == pytest.approx(0.372)


def test_measured_value_wins(monkeypatch):
    assert calibration.px_to_um("canon", "20x") == (0.1813, "canon, 20x, measured")
    monkeypatch.setitem(calibration.PX_UM_MEASURED, ("flir", "10x"), 0.447)
    assert calibration.px_to_um("flir", "10x")[0] == 0.447


def test_adapter_changes_the_value(monkeypatch):
    monkeypatch.setitem(calibration.CAMERA_ADAPTER, "flir", 0.5)
    assert calibration.px_to_um("flir", "10x")[0] == pytest.approx(0.9)


def test_unknown_camera_or_objective():
    with pytest.raises(ValueError):
        calibration.px_to_um("nikon", "10x")
    with pytest.raises(ValueError):
        calibration.px_to_um("flir", "15x")


def test_camera_from_exif(tmp_path):
    photo(tmp_path / "f" / "a_0000.png", "Teledyne FLIR")
    photo(tmp_path / "c" / "a_0000.jpg", "Canon")
    photo(tmp_path / "n" / "a_0000.png", None)
    assert detect_camera(tmp_path / "f", ["a_0000.png"]) == "flir"
    assert detect_camera(tmp_path / "c", ["a_0000.jpg"]) == "canon"
    assert detect_camera(tmp_path / "n", ["a_0000.png"]) is None
    assert detect_camera(tmp_path / "missing", ["x.jpg"]) is None


def test_choice_order(tmp_path):
    photo(tmp_path / "a_0000.png", "Teledyne FLIR")
    files = ["a_0000.png"]
    assert choose_px_to_um(0.3, "flir", "10x", tmp_path, files)[0] == 0.3     # --px-um wins
    v, how = choose_px_to_um(None, "auto", "10x", tmp_path, files)
    assert v == pytest.approx(0.45) and "from the photos" in how
    v, how = choose_px_to_um(None, "auto", None, tmp_path, files)
    assert v == pytest.approx(0.225) and "20x assumed" in how
    v, how = choose_px_to_um(None, "auto", "10x", tmp_path / "none", files)
    assert v == calibration.PX_TO_UM and "unknown" in how


def test_report_uses_the_flir_value(dirs):
    inp, out = dirs
    seq = make_ramp(out, "ramp_f", "intensity_pct", [0, 50, 100])
    make_photos(inp, out, "ramp_f", "f1", seq, "intensity_pct", spacing=lambda x: 40 + x / 5)
    for p in (inp / "folder" / "f1").iterdir():               # mark them as FLIR photos
        with Image.open(p) as im:
            img = im.copy()
        exif = Image.Exif()
        exif[0x010F] = "Teledyne FLIR"
        img.save(p, exif=exif, quality=95)
    cli.main(["folder", "f1", "--yes", "--no-show", "--input-dir", str(inp),
              "--output-dir", str(out)])
    rep = main_report("f1", output_dir=out, input_dir=inp, objective="4x")
    assert rep["px_um"] == pytest.approx(1.125) and "flir, 4x" in rep["px_source"]


def test_dc2200_with_4x_has_no_intensity_axis(dirs):
    inp, out = dirs
    seq = make_ramp(out, "ramp_d", "current_A", [0.1, 0.2])
    make_photos(inp, out, "ramp_d", "d1", seq, "current_A", spacing=lambda x: 40 + 100 * x)
    cli.main(["folder", "d1", "--yes", "--no-show", "--input-dir", str(inp),
              "--output-dir", str(out)])
    rep = main_report("d1", output_dir=out, input_dir=inp, objective="4x", camera="flir")
    assert "intensity[W/um2]" not in rep["table"]
    assert rep["px_um"] == pytest.approx(1.125)


def test_cli_prints_the_value(dirs, capsys):
    inp, out = dirs
    seq = make_ramp(out, "ramp_c", "intensity_pct", [0, 100])
    make_photos(inp, out, "ramp_c", "c1", seq, "intensity_pct")
    cli.main(["folder", "c1", "--yes", "--no-show", "--input-dir", str(inp),
              "--output-dir", str(out)])
    capsys.readouterr()
    cli.main(["report", "c1", "--camera", "flir", "--objective", "10x",
              "--input-dir", str(inp), "--output-dir", str(out)])
    assert "Micrometers per pixel: 0.45 (flir, 10x, calculated" in capsys.readouterr().out
