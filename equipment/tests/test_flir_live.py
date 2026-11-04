"""`equipment flir live` with a fake camera and a scripted window (no display needed)."""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from equipment import cli                                     # noqa: E402
from equipment.flir import capture                            # noqa: E402
from equipment.flir.backends import Frame                     # noqa: E402


class FakeDev:
    def bounds(self, name):
        return {"ExposureTime": (15.0, 30e6), "Gain": (0.0, 48.0)}.get(name)


class FakeLiveCam:
    model, serial, quality, photo_suffix, backend = "Blackfly S", "123", 95, ".png", "fake"

    def __init__(self):
        self.values = {"ExposureTime": 4000.0, "Gain": 0.0}
        self.dev, self.mode, self.closed = FakeDev(), None, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def start_live_mode(self):
        self.mode = "live"

    def stop(self):
        self.mode = None

    def exposure_s(self):
        return self.values["ExposureTime"] / 1e6

    def get(self, name):
        return self.values.get(name)

    def _try_set(self, name, value):
        return True

    def set_live(self, name, value):
        self.values[name] = value
        return value

    def grab(self, timeout_s=None):
        img = np.full((100, 200, 3), 120, np.uint8)
        img[:10, :10] = 255                                    # 0.5 % saturated
        return Frame(img, "BGR8", 0, 0)


def test_live_view_keys(monkeypatch, tmp_path, capsys):
    cam = FakeLiveCam()
    monkeypatch.setattr(capture, "_connect", lambda get, mode=None: cam)
    keys = iter([ord("+"), ord("]"), ord("o"), ord("c"), ord("s"), ord("-"), ord("q")])
    shown = []
    monkeypatch.setattr(cv2, "namedWindow", lambda *a: None)
    monkeypatch.setattr(cv2, "imshow", lambda win, img: shown.append(img.copy()))
    monkeypatch.setattr(cv2, "waitKey", lambda ms: next(keys, ord("q")))
    monkeypatch.setattr(cv2, "getWindowProperty", lambda *a: 1.0)
    monkeypatch.setattr(cv2, "destroyWindow", lambda *a: None)

    cli.main(["flir", "live", "focus", "--input-dir", str(tmp_path), "--width", "100"])

    assert cam.values["ExposureTime"] == pytest.approx(4000.0)    # x1.25 then /1.25
    assert cam.values["Gain"] == 1.0
    snaps = list((tmp_path / "folder" / "focus").glob("focus_*.png"))
    assert [p.name for p in snaps] == ["focus_0000.png"]
    assert shown[0].shape[1] == 100                               # scaled to --width
    assert (shown[-1][:5, :5] == (0, 0, 255)).all()               # saturation overlay
    out = capsys.readouterr().out
    assert "--shutter 4000us --gain 1.0" in out and cam.mode is None


def test_live_without_gui_gives_a_hint(monkeypatch):
    cam = FakeLiveCam()
    monkeypatch.setattr(capture, "_connect", lambda get, mode=None: cam)

    def no_gui(*a):
        raise cv2.error("The function is not implemented")
    monkeypatch.setattr(cv2, "namedWindow", no_gui)
    with pytest.raises(SystemExit) as e:
        cli.main(["flir", "live"])
    assert "opencv-python" in str(e.value.code)


def test_live_parser(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_call", lambda t, cfg=None: seen.append((t, cfg)))
    cli.main(["flir", "live", "--shutter", "1/250", "--gain", "0"])
    target, cfg = seen[0]
    assert target == "flir.capture:main_flir_live"
    assert cfg["name"] == "live" and cfg["shutter"] == "1/250" and cfg["width"] == 1280
    assert "output_csv" not in cfg
