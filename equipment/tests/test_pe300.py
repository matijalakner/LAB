"""pE-300 driver and pairings, against an emulated pE-300 (CoolLED DOC-038 protocol)."""
import contextlib
import csv
import types

import pytest

from equipment import cli
from equipment.coolled import pe300
from equipment.coolled.pe300 import Channel, css_command, parse_css
from equipment.experiments import liv, paired_ramp


class FakePE300Port:
    """Serial port with a pE-300 behind it."""

    instances = []

    def __init__(self, port, baud, timeout=None, write_timeout=None):
        assert baud == 57600
        self.port = port
        self.state = {"A": [False, False, 10], "B": [True, False, 20], "C": [True, False, 30]}
        self.history = []                 # every CSS set command received
        self.out = b""
        self.closed = False
        FakePE300Port.instances.append(self)

    # -- device ----------------------------------------------------------------
    def _status(self):
        return "CSS" + "".join(f"{ch}{'S' if s else 'X'}{'N' if n else 'F'}{i:03d}"
                               for ch, (s, n, i) in self.state.items())

    def _handle(self, cmd):
        if cmd == "CSS?":
            return [self._status()]
        if cmd.startswith("CSS"):
            self.history.append(cmd)
            for ch, sel, on, val in pe300._CSS_ITEM.findall(cmd[3:]):
                selected = sel == "S"
                self.state[ch] = [selected, on == "N" and selected, int(val)]   # XN -> XF
            return [cmd]
        if cmd == "XVER":
            return ["XFW_VER=2.2.9", "XHW_VER=1", "XDATA_VER=1.0", "XPOD_FW=2.0.0"]
        if cmd == "LAMS":
            return ["LAM:A:1V", "LAM:B:2B", "LAM:C:3GR", "LAM:D:----"]
        return []

    # -- pyserial API --------------------------------------------------------------
    def write(self, data):
        for cmd in data.decode().split("\r"):
            if cmd:
                for line in self._handle(cmd.strip().upper()):
                    self.out += line.encode() + b"\r\n"

    def read(self, n):
        chunk, self.out = self.out[:n], self.out[n:]
        return chunk

    def reset_input_buffer(self):
        self.out = b""

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def lit(self):
        return {ch: i for ch, (s, n, i) in self.state.items() if s and n}


@pytest.fixture
def fake_serial(monkeypatch):
    FakePE300Port.instances = []
    ports = [types.SimpleNamespace(device="/dev/ttyACM7", description="CoolLED pE-300",
                                   manufacturer="CoolLED", product=None, interface=None,
                                   vid=0x1234, pid=1)]
    mod = types.SimpleNamespace(
        Serial=FakePE300Port, SerialException=OSError,
        tools=types.SimpleNamespace(list_ports=types.SimpleNamespace(comports=lambda: ports)))
    monkeypatch.setattr(pe300, "_import_serial", lambda: mod)
    monkeypatch.delenv(pe300.PORT_ENV, raising=False)
    return FakePE300Port


def device(fake_serial):
    return fake_serial.instances[-1]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


# -- protocol -------------------------------------------------------------------
def test_parse_and_build_css():
    status = parse_css("CSSAXF050BSN060CSF070\r\n")
    assert status == {"A": Channel(False, False, 50), "B": Channel(True, True, 60),
                      "C": Channel(True, False, 70)}
    assert css_command(status) == "CSSAXF050BSN060CSF070"
    assert css_command({"A": Channel(False, True, 5)}) == "CSSAXF005"      # no XN
    with pytest.raises(ValueError):
        parse_css("XFW_VER=2")


def test_normalize_channels():
    assert pe300.normalize_channels("cba") == "ABC"
    assert pe300.normalize_channels(["A", "C"]) == "AC"
    for bad in ("", "AD", "X"):
        with pytest.raises(ValueError):
            pe300.normalize_channels(bad)


def test_port_is_found_by_name(fake_serial):
    assert pe300.find_port() == "/dev/ttyACM7"
    assert pe300.find_port("/dev/other") == "/dev/other"


def test_set_channels_verifies_and_deselects_the_others(fake_serial):
    with pe300.PE300() as pe:
        now = pe.set_channels("B", 45, on=True)
    dev = device(fake_serial)
    assert dev.lit() == {"B": 45}
    assert now["A"] == Channel(False, False, 10) and now["C"] == Channel(False, False, 30)
    assert dev.closed


def test_set_is_checked_against_the_status(fake_serial, monkeypatch):
    def deaf(self, cmd):          # the unit ignores the command (e.g. pod in use)
        return [self._status()] if cmd.startswith("CSS") else []
    monkeypatch.setattr(FakePE300Port, "_handle", deaf)
    with pe300.PE300() as pe:
        with pytest.raises(RuntimeError, match="expected"):
            pe.set_channels("ABC", 50)


def test_no_reply_times_out(fake_serial, monkeypatch):
    monkeypatch.setattr(FakePE300Port, "_handle", lambda self, cmd: [])
    pe = pe300.PE300(timeout=0.2)
    with pytest.raises(RuntimeError, match="no pE-300 answer"):
        pe.open()


# -- commands through the CLI --------------------------------------------------------
def test_cli_set_leaves_the_light_on_and_off_switches_it_off(fake_serial, capsys):
    cli.main(["pe300", "set", "35", "--channels", "AC"])
    assert device(fake_serial).lit() == {"A": 35, "C": 35}
    cli.main(["pe300", "off"])
    assert device(fake_serial).lit() == {}


def test_cli_status(fake_serial, capsys):
    cli.main(["pe300", "status"])
    out = capsys.readouterr().out
    assert "/dev/ttyACM7" in out and "fw_ver" in out
    assert "channel B 2B" in out and "20 %" in out


def test_cli_ramp(fake_serial, tmp_path):
    cli.main(["pe300", "ramp", "--min", "0", "--max", "20", "--step", "10",
              "--step-time", "0.01", "--channels", "AB", "--output-dir", str(tmp_path),
              "--output-csv", "r.csv"])
    dev = device(fake_serial)
    lit = [cmd for cmd in dev.history if "ASN" in cmd]
    assert [int(c[6:9]) for c in lit] == [0, 0, 10, 20, 10, 0]   # on at min, then 5 steps
    assert dev.lit() == {} and dev.closed                          # off at the end
    rows = read_csv(tmp_path / "ramp" / "r.csv")
    assert rows[1] == ["time_s", "cycle", "direction", "intensity_pct"]
    assert [r[3] for r in rows[2:]] == ["0", "10", "20", "10", "0"]


def test_light_is_switched_off_when_a_step_fails(fake_serial, monkeypatch):
    original = FakePE300Port._handle

    def failing(self, cmd):
        if cmd.startswith("CSS") and "020" in cmd and "N" in cmd:
            raise OSError("USB unplugged")
        return original(self, cmd)
    monkeypatch.setattr(FakePE300Port, "_handle", failing)
    with pytest.raises(SystemExit):
        cli.main(["pe300", "ramp", "--min", "0", "--max", "20", "--step", "10",
                  "--step-time", "0.01", "--output-csv", "/dev/null"])
    assert device(fake_serial).lit() == {}


# -- pairings --------------------------------------------------------------------
class FakeMeter:
    def __init__(self):
        self.reads = 0

    def read_power(self):
        self.reads += 1
        return 1e-3 * self.reads


class FakeCam:
    photo_suffix = ".png"

    def __init__(self, fail_after=None):
        self.fail_after, self.shots, self.closed = fail_after, 0, False

    def set_capture_target(self, card):
        pass

    def drain_events(self, seconds=0.0):
        import time
        time.sleep(min(seconds, 0.002))

    def capture_photo(self, dest, keep_on_card=False):
        if self.fail_after is not None and self.shots >= self.fail_after:
            raise RuntimeError("camera disconnected")
        self.shots += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")

    def close(self):
        self.closed = True


@pytest.fixture
def fake_meter(monkeypatch):
    meter = FakeMeter()
    monkeypatch.setattr(paired_ramp, "_open_power_meter",
                        lambda get: contextlib.nullcontext(meter))
    monkeypatch.setattr(liv, "open_pm400", lambda *a, **k: contextlib.nullcontext(meter))
    return meter


def test_pe300_with_pm400(fake_serial, fake_meter, tmp_path):
    cli.main(["pe300", "ramp", "--min", "0", "--max", "20", "--step", "10",
              "--step-time", "0.04", "--power", "--output-dir", str(tmp_path),
              "--output-csv", "r.csv"])
    log = read_csv(tmp_path / "ramp" / "r_power.csv")
    assert log[0][0] == "time_stamp"
    assert log[1] == ["time_s", "power_W", "utc", "step", "cycle", "direction",
                      "intensity_pct"]
    assert [r[6] for r in log[2:]] == ["0", "10", "20", "10", "0"]   # one per step
    assert fake_meter.reads == 5 and device(fake_serial).lit() == {}


def test_pe300_with_flir_and_pm400(fake_serial, fake_meter, monkeypatch, tmp_path):
    cam = FakeCam()
    monkeypatch.setattr(paired_ramp, "_connect_flir", lambda get: cam)
    cli.main(["pe300", "ramp", "--min", "0", "--max", "10", "--step", "10",
              "--step-time", "0.05", "--photos", "s1", "--camera", "flir", "--gain", "0",
              "--power", "--power-interval", "0.02",
              "--output-dir", str(tmp_path / "out"), "--output-csv", "r.csv",
              "--input-dir", str(tmp_path / "in")])
    photos = sorted(p.name for p in (tmp_path / "in" / "folder" / "s1").iterdir())
    assert photos == ["s1_0000.png", "s1_0001.png", "s1_0002.png"]
    plog = read_csv(tmp_path / "out" / "ramp" / "r_photos.csv")
    assert plog[1][-1] == "intensity_pct" and [r[-1] for r in plog[2:]] == ["0", "10", "0"]
    wlog = read_csv(tmp_path / "out" / "ramp" / "r_power.csv")
    assert len(wlog) - 2 == fake_meter.reads >= 7         # every 0.02 s over 0.15 s
    assert cam.closed and device(fake_serial).lit() == {}


def test_camera_failure_stops_the_ramp_and_the_light(fake_serial, fake_meter, monkeypatch):
    cam = FakeCam(fail_after=1)
    monkeypatch.setattr(paired_ramp, "_connect_flir", lambda get: cam)
    with pytest.raises(SystemExit) as e:
        cli.main(["pe300", "ramp", "--min", "0", "--max", "50", "--step", "10",
                  "--step-time", "0.05", "--photos", "s2", "--camera", "flir",
                  "--input-dir", "/tmp/eq-test-in", "--output-csv", "/dev/null"])
    assert "camera failed" in str(e.value.code)
    assert device(fake_serial).lit() == {} and cam.closed


def test_missing_camera_never_switches_the_light_on(fake_serial, monkeypatch):
    def no_camera(get):
        raise RuntimeError("no FLIR camera connected")
    monkeypatch.setattr(paired_ramp, "_connect_flir", no_camera)
    with pytest.raises(SystemExit):
        cli.main(["pe300", "ramp", "--min", "0", "--max", "50", "--step", "10",
                  "--step-time", "1", "--photos", "s3", "--camera", "flir"])
    assert fake_serial.instances == []          # the pE-300 was never even opened


def test_liv_with_pe300(fake_serial, fake_meter, tmp_path):
    cli.main(["liv", "--source", "pe300", "--max", "50", "--ramp-duration", "0.05",
              "--update-rate", "100", "--channels", "C", "--output-dir", str(tmp_path),
              "--output-csv", "l.csv"])
    rows = read_csv(tmp_path / "liv" / "l.csv")
    assert rows[0] == ["time_s", "cycle", "direction", "intensity_pct", "power_W"]
    levels = [int(r[3]) for r in rows[1:]]
    assert levels[0] == 0 and max(levels) == 50 and levels[-1] == 0
    assert all(isinstance(x, int) for x in levels)
    assert device(fake_serial).lit() == {}


def _ports(*specs):
    """(device, serial_number, location) as the real pE-300 reports them."""
    return [types.SimpleNamespace(device=d, description="pE300 - USB Virtual Serial Port",
                                  manufacturer=None, product=None, interface=None,
                                  vid=0x0483, pid=0xA080, serial_number=sn, location=loc)
            for d, sn, loc in specs]


def test_two_coolled_ports_the_answering_one_is_used(fake_serial, monkeypatch):
    mod = pe300._import_serial()
    two = _ports(("/dev/ttyACM1", "0000", "3-9:1.0"), ("/dev/ttyACM0", "0000", "3-10:1.0"))
    monkeypatch.setattr(mod.tools.list_ports, "comports", lambda: two)
    monkeypatch.setattr(pe300, "_probe", lambda port, timeout=0.6: port == "/dev/ttyACM0")
    assert pe300.find_port() == "/dev/ttyACM0"
    monkeypatch.setattr(pe300, "_probe", lambda port, timeout=0.6: True)
    with pytest.raises(RuntimeError, match="different USB devices"):
        pe300.find_port()
    monkeypatch.setattr(pe300, "_probe", lambda port, timeout=0.6: False)
    with pytest.raises(RuntimeError, match="none answered"):
        pe300.find_port()


def test_one_unit_with_two_answering_ports(fake_serial, monkeypatch):
    mod = pe300._import_serial()
    # the real unit: one USB device, "Virtual Serial Port A" and "B"
    same = _ports(("/dev/ttyACM10", "0000", "3-9:1.2"), ("/dev/ttyACM2", "0000", "3-9:1.0"))
    monkeypatch.setattr(mod.tools.list_ports, "comports", lambda: same)
    monkeypatch.setattr(pe300, "_probe", lambda port, timeout=0.6: True)
    assert pe300.find_port() == "/dev/ttyACM2"          # numeric order, not text order
    no_loc = _ports(("/dev/ttyACM0", "0000", None), ("/dev/ttyACM1", "0000", None))
    monkeypatch.setattr(mod.tools.list_ports, "comports", lambda: no_loc)
    with pytest.raises(RuntimeError, match="different USB devices"):
        pe300.find_port()                              # 0000 alone proves nothing


def test_probe_ignores_an_echo(fake_serial, monkeypatch):
    assert pe300._probe("/dev/x", timeout=0.2) is True                       # real reply
    monkeypatch.setattr(FakePE300Port, "_handle", lambda self, cmd: [cmd])   # echo only
    assert pe300._probe("/dev/x", timeout=0.2) is False


def test_channel_letter_as_port_is_refused(fake_serial):
    with pytest.raises(SystemExit) as e:
        cli.main(["pe300", "set", "30", "--port", "B"])
    assert "not a serial port" in str(e.value.code)


def test_permission_denied_is_reported(fake_serial, monkeypatch):
    def denied(*a, **k):
        raise PermissionError(13, "Permission denied: '/dev/ttyACM7'")
    monkeypatch.setattr(FakePE300Port, "__init__", denied)
    with pytest.raises(SystemExit) as e:
        cli.main(["pe300", "status", "--port", "/dev/ttyACM7"])
    assert "dialout" in str(e.value.code)
    with pytest.raises(PermissionError, match="dialout"):
        pe300._probe("/dev/ttyACM7")


def test_devices_lists_one_unit_once(fake_serial, monkeypatch):
    from equipment import devices
    mod = pe300._import_serial()
    same = _ports(("/dev/ttyACM1", "0000", "3-9:1.2"), ("/dev/ttyACM0", "0000", "3-9:1.0"))
    monkeypatch.setattr(mod.tools.list_ports, "comports", lambda: same)
    assert devices.probe_pe300() == [("CoolLED pE-300", "ports /dev/ttyACM0, /dev/ttyACM1")]


def test_parse_hold():
    assert pe300.parse_hold("c=1") == {"C": 1}
    assert pe300.parse_hold("A=5, C=1") == {"A": 5, "C": 1}
    assert pe300.parse_hold({"C": 2.4}) == {"C": 2}
    assert pe300.parse_hold(None) == {}
    for bad in ("C", "D=1", "AB=1", "C=101"):
        with pytest.raises(ValueError):
            pe300.parse_hold(bad)


def test_ramp_blue_with_green_held_at_1(fake_serial, tmp_path):
    seen = []
    original = FakePE300Port._handle

    def spy(self, cmd):
        out = original(self, cmd)
        if cmd.startswith("CSS") and cmd != "CSS?":
            seen.append(dict(self.lit()))
        return out
    FakePE300Port._handle = spy
    try:
        cli.main(["pe300", "ramp", "--channels", "B", "--hold", "C=1", "--min", "0",
                  "--max", "2", "--step", "1", "--step-time", "0.01",
                  "--output-dir", str(tmp_path), "--output-csv", "r.csv"])
    finally:
        FakePE300Port._handle = original
    lit = [s for s in seen if s]
    assert all(s.get("C") == 1 for s in lit)                     # green stays at 1 %
    assert [s["B"] for s in lit] == [0, 0, 1, 2, 1, 0]           # blue ramps
    assert all("A" not in s for s in lit)
    assert device(fake_serial).lit() == {}                       # everything off at the end


def test_set_with_hold(fake_serial):
    cli.main(["pe300", "set", "40", "--channels", "B", "--hold", "C=1"])
    assert device(fake_serial).lit() == {"B": 40, "C": 1}
    cli.main(["pe300", "off"])
    assert device(fake_serial).lit() == {}
