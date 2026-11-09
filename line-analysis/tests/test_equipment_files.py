"""Folder, report and video on files laid out exactly as equipment writes them."""
import csv
import json

import numpy as np
from PIL import Image
import pandas as pd
import pytest

from line_analysis import cli
from line_analysis.calibration import COEFF, PE300_W_PER_PCT
from line_analysis.folder import main_folder, strip_positions
from line_analysis.report import main_report
from conftest import save_photo, write_log

PHOTO_HEADER = ["time_s", "index", "file", "utc", "step", "cycle", "direction"]
STAMP = "2026-11-02T07:31:11.102Z"


def make_ramp(out, name, column, levels, step_time=10.0, stamp=STAMP):
    seq = [(1, "up", x) for x in levels] + [(1, "down", x) for x in levels[-2::-1]]
    rows = [(round(k * step_time, 4), c, d, x) for k, (c, d, x) in enumerate(seq)]
    write_log(out / "ramp" / f"{name}.csv", ["time_s", "cycle", "direction", column], rows,
              stamp)
    return seq


def make_photos(inp, out, ramp_name, sample, seq, column, step_time=10.0,
                spacing=lambda x: 40 + x, with_log=True):
    t0 = pd.Timestamp(STAMP)
    rows = []
    for k, (cycle, direction, level) in enumerate(seq):
        t = k * step_time + step_time / 2
        f = f"{sample}_{k:04d}.jpg"
        save_photo(inp / "folder" / sample / f, spacing(level), seed=k)
        utc = (t0 + pd.Timedelta(seconds=t)).isoformat().replace("+00:00", "Z")
        rows.append((t, k, f, utc, k + 1, cycle, direction, level))
    if with_log:
        write_log(out / "ramp" / f"{ramp_name}_photos.csv", PHOTO_HEADER + [column], rows)
    return rows


def results(out, sample):
    with open(out / "folder" / sample / "results.csv") as f:
        return list(csv.DictReader(f))


def test_pe300_ramp_photo_log_power_report(dirs):
    inp, out = dirs
    seq = make_ramp(out, "ramp_20261102T073111Z", "intensity_pct", [0, 10, 20, 30])
    rows = make_photos(inp, out, "ramp_20261102T073111Z", "s1", seq, "intensity_pct")
    write_log(out / "ramp" / "ramp_20261102T073111Z_power.csv",
              ["time_s", "power_W", "utc", "step", "cycle", "direction", "intensity_pct"],
              [(r[0], r[7] * 1e-4, r[3], r[4], r[5], r[6], r[7]) for r in rows])
    # an older ramp without photos must not be picked
    make_ramp(out, "ramp_20261101T000000Z", "current_A", [0, 0.1], stamp="2026-11-01T00:00:00Z")

    res = main_folder("s1", out, inp, interactive=False, show=False)
    assert len(res) == len(seq)
    rec = results(out, "s1")
    assert {r["time_source"] for r in rec} == {"log"}
    assert [r["file"] for r in rec] == [r[2] for r in rows]          # sorted by log time
    assert all(r["warning"] == "" for r in rec)

    rep = main_report("s1", output_dir=out)
    assert rep["matched_by"] == "photo log" and rep["level"] == "intensity_pct"
    assert rep["ramp_path"].endswith("ramp_20261102T073111Z.csv")
    t = rep["table"]
    assert list(t["intensity[%]"]) == [r[7] for r in rows]
    assert np.allclose(t["power[W]"], t["intensity[%]"] * 1e-4)
    assert np.allclose(t["mean_spacing_px"], 40 + t["intensity[%]"], atol=0.5)
    assert set(t["direction"]) == {"up", "down"}
    for f in ("data.csv", "plots.png", "timeline.png"):
        assert (out / "report" / "s1" / f).stat().st_size > 0


def test_dc2200_by_time_without_photo_log(dirs):
    """Photos from a timelapse during a ramp: matched by their logged capture time."""
    inp, out = dirs
    seq = make_ramp(out, "ramp_x", "current_A", [0.1, 0.2, 0.3])
    rows = make_photos(inp, out, "ramp_x", "s2", seq, "current_A",
                       spacing=lambda x: 40 + 100 * x, with_log=False)
    write_log(out / "camera" / "flir_20261102T073111Z.csv", ["time_s", "index", "file", "utc"],
              [(r[0], r[1], r[2], r[3]) for r in rows])
    cli.main(["folder", "s2", "--yes", "--no-show", "--input-dir", str(inp),
              "--output-dir", str(out)])
    assert {r["time_source"] for r in results(out, "s2")} == {"log"}
    rep = main_report("s2", output_dir=out, objective="10x")
    assert rep["matched_by"] == "time"
    t = rep["table"]
    assert list(t["current[A]"]) == [r[7] for r in rows]
    assert list(t["step"]) == list(range(1, len(rows) + 1))
    assert np.allclose(t["intensity[W/um2]"], t["current[A]"] * COEFF["10x"])


def test_liv_curve_gives_the_power_axis(dirs):
    inp, out = dirs
    seq = make_ramp(out, "r", "intensity_pct", [0, 50, 100])
    make_photos(inp, out, "r", "s3", seq, "intensity_pct")
    liv = write_log(out / "liv" / "liv_1.csv",
                    ["time_s", "cycle", "direction", "intensity_pct", "power_W"],
                    [(i, 1, "up", x, x * 2e-5) for i, x in enumerate(range(0, 101, 10))],
                    stamp=None)
    main_folder("s3", out, inp, interactive=False, show=False)
    rep = main_report("s3", output_dir=out, liv=liv)
    assert rep["power_source"].startswith("LIV")
    assert np.allclose(rep["table"]["power[W]"], rep["table"]["intensity[%]"] * 2e-5)


def test_pe300_color_calibration_gives_the_power(dirs):
    inp, out = dirs
    seq = make_ramp(out, "r", "intensity_pct", [0, 50, 100])
    make_photos(inp, out, "r", "s5", seq, "intensity_pct")
    main_folder("s5", out, inp, interactive=False, show=False)
    rep = main_report("s5", output_dir=out, color="green")
    assert rep["power_source"].startswith("pE-300 green")
    assert np.allclose(rep["table"]["power[W]"],
                       rep["table"]["intensity[%]"] * PE300_W_PER_PCT["green"])
    fits = pd.read_csv(rep["fits_path"])
    assert set(fits["x"]) == {"intensity[%]", "power[mW]"}
    assert set(fits["y"]) == {"distance", "pitch"}
    assert "power[W]" not in main_report("s5", output_dir=out)["table"]


def test_report_needs_photos_of_the_ramp(dirs):
    inp, out = dirs
    make_ramp(out, "r", "current_A", [0.1, 0.2], stamp="2020-01-01T00:00:00Z")
    seq = [(1, "up", 0.1), (1, "up", 0.2)]
    make_photos(inp, out, "other", "s4", seq, "current_A", with_log=False)
    write_log(out / "camera" / "camera_1.csv", ["time_s", "index", "file", "utc"],
              [(0, 0, "s4_0000.jpg", STAMP), (1, 1, "s4_0001.jpg", STAMP)])
    main_folder("s4", out, inp, interactive=False, show=False)
    with pytest.raises(ValueError, match="No photo"):
        main_report("s4", output_dir=out)


def test_flir_video_uses_the_frame_log(dirs):
    import cv2
    from conftest import line_image
    inp, out = dirs
    path = inp / "folder" / "v1" / "v1_0000.mp4"
    path.parent.mkdir(parents=True)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (400, 200))
    # 20 frames written at a nominal 10 fps, but the camera really delivered
    # one frame every 0.2 s (dropped frames): the log has the true times
    for i in range(20):
        img, _ = line_image(30 + i, width=400, height=200, offset=20)
        w.write(img)
    w.release()
    write_log(out / "camera" / "flir_A.csv", ["time_s", "index", "file", "utc"],
              [(0, 0, "v1_0000.mp4", STAMP)])
    write_log(out / "camera" / "flir_A_frames.csv",
              ["frame", "time_s", "camera_time_s", "frame_id"],
              [(i, round(0.2 * i, 4), 0.2 * i, i) for i in range(20)])
    cli.main(["video", "v1_0000.mp4", "-n", "1", "--quiet", "--input-dir", str(inp),
              "--output-dir", str(out)])
    lines = (out / "video" / "v1_0000" / "lines.csv").read_text().splitlines()
    assert lines[0] == f"time_stamp,{STAMP}"
    rows = list(csv.DictReader(lines[1:]))
    assert [int(r["frame"]) for r in rows] == [0, 5, 10, 15]     # 1 s = 5 real frames
    assert [float(r["time"]) for r in rows] == [0.0, 1.0, 2.0, 3.0]
    gaps = [np.mean(np.diff(json.loads(r["lines"]))) for r in rows]
    assert np.allclose(gaps, [30, 35, 40, 45], atol=1)

    cli.main(["spacing", "v1_0000", "--output-dir", str(out)])
    assert (out / "video" / "v1_0000" / "spacing.png").exists()

    cli.main(["video", str(path), "-n", "1", "--quiet", "--nominal-fps",
              "--output-dir", str(out)])
    rows = list(csv.DictReader((out / "video" / "v1_0000" / "lines.csv")
                               .read_text().splitlines()[1:]))
    assert [int(r["frame"]) for r in rows] == [0, 10]


def test_cli_errors_are_one_line(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["image", "does_not_exist_0000.jpg"])
    assert e.value.code == 1
    assert capsys.readouterr().err.startswith("error: File not found")


def test_strip_positions():
    assert strip_positions(100) == [1, 20, 40, 60, 80, 100]
    assert strip_positions(200) == [1, 40, 80, 120, 160, 200]
    assert strip_positions(12) == [1, 2, 5, 7, 10, 12]
    assert strip_positions(3) == [1, 2, 3]
    assert strip_positions(1) == [1]


def test_folder_saves_the_middle_strips_of_evenly_spread_photos(dirs):
    inp, out = dirs
    for i in range(12):
        save_photo(inp / "folder" / "st" / f"st_{i:04d}.png", 80, height=301, seed=i)
    main_folder("st", out, inp, interactive=False, show=False, middle_strips=False)
    strips = sorted((out / "folder" / "st" / "full_image" / "strips").iterdir())
    assert [p.name for p in strips] == [f"st_{i:04d}_strip.png" for i in (0, 1, 4, 6, 9, 11)]
    source = np.asarray(Image.open(inp / "folder" / "st" / "st_0006.png").convert("RGB"))
    assert np.array_equal(np.asarray(Image.open(strips[3])), source[100:200])


@pytest.mark.parametrize("track", [False, True])
def test_middle_strips_are_300_px_with_the_lines_marked(dirs, track):
    inp, out = dirs
    for i in range(4):
        save_photo(inp / "folder" / "m" / f"m_{i:04d}.png", 80, height=701, seed=i)
    rows = main_folder("m", out, inp, interactive=False, show=False, tracking=track or None)
    target = out / "folder" / "m"
    assert [r[4] for r in rows] == [8] * 4 and all(r[6] == "" for r in rows)
    assert len(results(out, "m")) == 4
    assert not (target / "strips").exists()
    source = np.asarray(Image.open(inp / "folder" / "m" / "m_0002.png").convert("RGB"))
    for i in range(4):
        marked = np.asarray(Image.open(target / f"m_{i:04d}_marked.png"))
        assert marked.shape[:2] == (300, 800)
    marked = np.asarray(Image.open(target / "m_0002_marked.png"))
    painted = np.any(marked != source[200:500], axis=(0, 2))
    assert painted.sum() > 0 and marked[0, 40].tolist() == [255, 0, 0]


def test_middle_strips_warn_about_a_photo_that_is_too_low(dirs):
    inp, out = dirs
    for i, h in enumerate((400, 400, 200, 400)):
        save_photo(inp / "folder" / "low" / f"low_{i}.png", 80, height=h, seed=i)
    rows = main_folder("low", out, inp, interactive=False, show=False)
    assert "failed: photo has only 200 rows" in rows[2][6]


def test_full_image_mode_keeps_the_marked_photos_at_full_size(dirs):
    inp, out = dirs
    for i in range(3):
        save_photo(inp / "folder" / "f" / f"f_{i}.png", 80, height=701, seed=i)
    main_folder("f", out, inp, interactive=False, show=False, middle_strips=False)
    marked = Image.open(out / "folder" / "f" / "full_image" / "f_1_marked.png")
    assert marked.size == (800, 701)
    assert not (out / "folder" / "f" / "results.csv").exists()


def walls(xs, defects=(), width=6000, height=500, seed=0):
    """Photo with lines drawn as a bright peak followed by a dark dip, and dark defects."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 150, np.float32) + rng.normal(0, 2, (height, width, 3))
    for x in xs:
        img[:, x - 8:x] += 40
        img[:, x:x + 8] -= 50
    for x in defects:
        img[:, x:x + 6] -= 30
    return np.clip(img, 0, 255).astype(np.uint8)


def test_contrast_finds_the_zero_crossings_and_ignores_fixed_defects(dirs):
    inp, out = dirs
    for i in range(10):
        xs = [600 + 650 * n + 25 * i for n in range(6)]
        path = inp / "folder" / "w" / f"w_{i:02d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(walls(xs, defects=[300, 5300], seed=i)).save(path)
    rows = main_folder("w", out, inp, interactive=False, show=False)
    assert [r[4] for r in rows] == [6] * 10
    assert all(abs(r[3] - 650) < 2 for r in rows)
    params = json.loads((out / "folder" / "w" / "parameters.json").read_text())
    assert params["method"] == "contrast"
    assert len(params["defects_x"]) == 2 and abs(params["defects_x"][0] - 303) < 10
    marked = np.asarray(Image.open(out / "folder" / "w" / "w_00_marked.png"))
    assert marked.shape[:2] == (300, 6000)
    assert marked[0, 600].tolist() == [255, 0, 0] or marked[0, 599].tolist() == [255, 0, 0]
