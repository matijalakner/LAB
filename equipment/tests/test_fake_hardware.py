"""Full command runs through the CLI, with fake instruments instead of the hardware."""
import contextlib
import csv

import pytest

from equipment import cli
from equipment.experiments import ramp_camera
from equipment.thorlabs import dc2200


class FakeDC2200:
    log = []

    def __init__(self, communicator):
        self.resource = communicator.resource
        FakeDC2200.log.append(("open", self.resource))

    def set_user_current_limit(self, a):
        self.log.append(("limit", a))

    def configure_constant_current(self, a):
        self.log.append(("current", a))

    def switch_on(self):
        self.log.append(("on",))

    def switch_off(self):
        self.log.append(("off",))


class FakeComm:
    def __init__(self, resource):
        self.resource = resource

    def close(self):
        pass


class FakeCamera:
    photo_suffix = ".jpg"

    def __init__(self):
        self.closed = False

    def set_capture_target(self, card):
        pass

    def drain_events(self, seconds=0.0, until_complete=False):
        import time
        time.sleep(max(0.0, min(seconds, 0.005)))
        return []

    def capture_photo(self, dest, keep_on_card=False):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpeg")

    def close(self):
        self.closed = True


@pytest.fixture
def fake_dc2200(monkeypatch):
    FakeDC2200.log = []
    monkeypatch.setattr(dc2200, "_import_dc2200", lambda: (FakeComm, FakeDC2200))
    monkeypatch.setattr(dc2200, "ThorlabsUSBDriver",
                        lambda product_id=None: contextlib.nullcontext())
    return FakeDC2200.log


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def test_ramp_through_the_cli(fake_dc2200, tmp_path, capsys):
    cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.2", "--step", "0.1",
              "--step-time", "0.01", "--dc2200-serial", "SN9",
              "--output-dir", str(tmp_path), "--output-csv", "r.csv"])
    assert fake_dc2200[0] == ("open", "USB0::4883::32968::SN9::0::INSTR")
    currents = [a for k, *a in fake_dc2200 if k == "current" for a in a]
    assert currents == [0.0, 0.0, 0.1, 0.2, 0.1, 0.0]       # initial + 5 steps
    assert fake_dc2200[-1] == ("off",)
    rows = read_csv(tmp_path / "ramp" / "r.csv")
    assert rows[0][0] == "time_stamp" and rows[1] == dc2200.RAMP_CSV_HEADER
    assert len(rows) == 2 + 5
    assert "Ramp completed." in capsys.readouterr().out


def test_set_and_off(fake_dc2200):
    cli.main(["dc2200", "set", "0.25"])
    assert ("on",) in fake_dc2200 and ("limit", 0.25) in fake_dc2200
    fake_dc2200.clear()
    cli.main(["dc2200", "off"])
    assert ("off",) in fake_dc2200 and ("on",) not in fake_dc2200


def test_led_is_switched_off_when_a_step_fails(fake_dc2200, monkeypatch):
    def broken(self, a):
        if a > 0.05:
            raise RuntimeError("USB gone")
        FakeDC2200.log.append(("current", a))
    monkeypatch.setattr(FakeDC2200, "configure_constant_current", broken)
    with pytest.raises(SystemExit):
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.2", "--step", "0.1",
                  "--step-time", "0.01", "--output-csv", "/dev/null"])
    assert fake_dc2200[-1] == ("off",)


def test_ramp_with_photos_through_the_cli(fake_dc2200, monkeypatch, tmp_path):
    cam = FakeCamera()
    monkeypatch.setattr(ramp_camera, "_connect", lambda get: cam)
    cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.1", "--step", "0.1",
              "--step-time", "0.05", "--photos", "run", "--shutter", "1/250",
              "--output-dir", str(tmp_path / "out"), "--output-csv", "r.csv",
              "--input-dir", str(tmp_path / "in")])
    photos = sorted((tmp_path / "in" / "folder" / "run").glob("*.jpg"))
    assert [p.name for p in photos] == ["run_0000.jpg", "run_0001.jpg", "run_0002.jpg"]
    log = read_csv(tmp_path / "out" / "ramp" / "r_photos.csv")
    assert log[1] == ramp_camera.PHOTO_HEADER
    assert [r[7] for r in log[2:]] == ["0.0", "0.1", "0.0"]       # current at each photo
    assert cam.closed and fake_dc2200[-1] == ("off",)


def test_canon_timelapse_through_the_cli(monkeypatch, tmp_path):
    from equipment.canon import capture

    class Cam(FakeCamera):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    monkeypatch.setattr(capture, "_connect", lambda get: Cam())
    argv = ["canon", "timelapse", "s1", "-n", "0.02", "--count", "3",
            "--input-dir", str(tmp_path / "in"), "--output-dir", str(tmp_path / "out"),
            "--output-csv", "log.csv"]
    cli.main(argv)
    cli.main(argv)                                   # numbering continues
    names = sorted(p.name for p in (tmp_path / "in" / "folder" / "s1").iterdir())
    assert names == [f"s1_{i:04d}.jpg" for i in range(6)]
    assert len(read_csv(tmp_path / "out" / "camera" / "log.csv")) == 2 + 3


def test_flir_modules_import():
    pytest.importorskip("cv2")
    from equipment.flir import backends, camera, capture  # noqa: F401
    assert camera.FlirCamera and capture.main_flir_photo
