"""Linux / Windows differences: VISA backend, built-in DC2200 driver, PM400, Canon on
Windows, devices and doctor. Windows is simulated by setting sys.platform."""
import sys

import pytest

from equipment import cli, doctor
from equipment.thorlabs import dc2200, visa
from equipment.thorlabs.common import DC2200_PRODUCT_ID, PM_PRODUCT_ID


# ---------------------------------------------------------------------------
# a simulated DC2200 / PM400 behind a simulated VISA library
# ---------------------------------------------------------------------------
class FakeDC2200Inst:
    """Answers the DC2200 SCPI commands; unknown commands go to the error queue."""

    def __init__(self, idn="Thorlabs,DC2200,M00937194,1.3.0", limit_cmd_ok=True,
                 readback_offset=0.0):
        self.idn, self.limit_cmd_ok, self.readback_offset = idn, limit_cmd_ok, readback_offset
        self.mode, self.limit, self.current, self.on = "CC", 0.5, 0.0, False
        self.errors, self.log, self.closed = [], [], False
        self.timeout = None

    def write(self, cmd):
        self.log.append(cmd)
        head, _, arg = cmd.partition(" ")
        if head == "*CLS":
            self.errors = []
        elif head == "SOUR1:MODE":
            self.mode = arg
        elif head == "SOUR1:CURR:LIM:AMPL" and self.limit_cmd_ok:
            self.limit = float(arg)
        elif head == "SOUR1:CCUR:CURR":
            self.current = min(float(arg), self.limit)        # the device clamps at the limit
        elif head == "OUTP1:STAT":
            self.on = arg == "ON"
        else:
            self.errors.append('-113,"Undefined header"')

    def query(self, cmd):
        self.log.append(cmd)
        if cmd == "*IDN?":
            return self.idn + "\n"
        if cmd == "SYST:ERR?":
            return (self.errors.pop(0) if self.errors else '0,"No error"') + "\n"
        if cmd == "SOUR1:MODE?":
            return self.mode
        if cmd == "SOUR1:CURR:LIM:AMPL?":
            return f"{self.limit + self.readback_offset:.6e}"
        if cmd == "SOUR1:CCUR:CURR?":
            return f"{self.current:.6e}"
        if cmd == "OUTP1:STAT?":
            return "1" if self.on else "0"
        if cmd == "MEAS:CURR?":
            return f"{self.current if self.on else 0:.6e}"
        self.errors.append('-113,"Undefined header"')
        return ""

    def close(self):
        self.closed = True


class FakePMInst:
    def __init__(self):
        self.log, self.closed, self.timeout = [], False, None

    def write(self, cmd):
        self.log.append(cmd)

    def query(self, cmd):
        self.log.append(cmd)
        return {"*IDN?": "Thorlabs,PM400,P5003335,1.6.0", "MEAS:POW?": "1.25e-3"}[cmd]

    def close(self):
        self.closed = True


class FakeRM:
    def __init__(self, instruments):
        self.instruments = instruments          # {resource name: instrument}
        self.opened, self.closed = [], False

    def list_resources(self, query="?*::INSTR"):
        return tuple(self.instruments)

    def open_resource(self, name):
        if name not in self.instruments:
            raise OSError(f"VI_ERROR_RSRC_NFOUND: {name}")
        self.opened.append(name)
        return self.instruments[name]

    def close(self):
        self.closed = True


@pytest.fixture
def fake_visa(monkeypatch):
    """A VISA library with a DC2200 and a PM400, named as NI-VISA lists them (hex)."""
    dc, pm = FakeDC2200Inst(), FakePMInst()
    rm = FakeRM({"USB0::0x1313::0x80C8::M00937194::INSTR": dc,
                 "USB0::0x1313::0x8075::P5003335::INSTR": pm})
    monkeypatch.setattr(visa, "resource_manager", lambda: rm)
    monkeypatch.setenv("EQUIPMENT_DC2200_DRIVER", "builtin")
    monkeypatch.setenv(visa.ENV_VAR, "")                 # system VISA: no kernel detach
    return rm, dc, pm


# ---------------------------------------------------------------------------
# VISA backend and resource lookup
# ---------------------------------------------------------------------------
def test_backend_per_system(monkeypatch):
    monkeypatch.delenv(visa.ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert visa.visa_backend() == ""                     # NI-VISA
    monkeypatch.setattr(sys, "platform", "linux")
    assert visa.visa_backend() == "@py"                  # pyvisa-py
    monkeypatch.setenv(visa.ENV_VAR, "@ivi")
    assert visa.visa_backend() == "@ivi"


def test_resource_found_by_serial_when_the_name_differs(fake_visa):
    rm, dc, _ = fake_visa
    # our name is decimal; the VISA library lists it in hex
    with visa.open_instrument("USB0::4883::32968::M00937194::0::INSTR", DC2200_PRODUCT_ID) as inst:
        assert inst is dc and inst.timeout == 5000
    assert rm.opened == ["USB0::0x1313::0x80C8::M00937194::INSTR"] and rm.closed


def test_wrong_serial_lists_what_is_connected(fake_visa):
    with pytest.raises(RuntimeError, match="Connected: USB0::0x1313::0x80C8::M00937194"):
        with visa.open_instrument("USB0::4883::32968::WRONG::0::INSTR", DC2200_PRODUCT_ID):
            pass


def test_scpi_error_queue():
    inst = FakeDC2200Inst()
    inst.errors = ['-113,"Undefined header"', '-222,"Data out of range"']
    assert visa.scpi_errors(inst) == [(-113, "Undefined header"), (-222, "Data out of range")]
    assert visa.scpi_errors(inst) == []


# ---------------------------------------------------------------------------
# built-in DC2200 driver
# ---------------------------------------------------------------------------
def test_driver_choice(monkeypatch):
    monkeypatch.delenv("EQUIPMENT_DC2200_DRIVER", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert dc2200.dc2200_driver() == "builtin"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(dc2200, "_import_dc2200", lambda: (object, object))
    assert dc2200.dc2200_driver() == "measurement_control"      # tested on the hardware

    def missing():
        raise RuntimeError("no measurement_control")
    monkeypatch.setattr(dc2200, "_import_dc2200", missing)
    assert dc2200.dc2200_driver() == "builtin"
    monkeypatch.setenv("EQUIPMENT_DC2200_DRIVER", "nonsense")
    with pytest.raises(ValueError):
        dc2200.dc2200_driver()


def test_builtin_set_and_off(fake_visa):
    _, dc, _ = fake_visa
    cli.main(["dc2200", "set", "0.25"])
    assert dc.on and dc.current == pytest.approx(0.25) and dc.limit == pytest.approx(0.25)
    assert "SOUR1:MODE CC" in dc.log
    cli.main(["dc2200", "off"])
    assert not dc.on and dc.current == 0


def test_builtin_ramp_through_the_cli(fake_visa, tmp_path):
    _, dc, _ = fake_visa
    seen = []
    original = FakeDC2200Inst.write

    def spy(self, cmd):
        original(self, cmd)
        if cmd.startswith("SOUR1:CCUR:CURR "):
            seen.append(round(self.current, 6))
    FakeDC2200Inst.write = spy
    try:
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.2", "--step", "0.1",
                  "--step-time", "0.01", "--output-dir", str(tmp_path), "--output-csv", "r.csv"])
    finally:
        FakeDC2200Inst.write = original
    assert seen == [0.0, 0.0, 0.1, 0.2, 0.1, 0.0]
    assert dc.limit == pytest.approx(0.2) and not dc.on and dc.closed


def test_limit_has_a_1_mA_minimum(fake_visa):
    _, dc, _ = fake_visa
    drv = dc2200.DC2200SCPI(dc)
    drv.set_user_current_limit(0.0)
    assert dc.limit == pytest.approx(0.001)


def test_refused_command_stops_before_the_led_is_on(monkeypatch, fake_visa):
    rm, dc, _ = fake_visa
    dc.limit_cmd_ok = False                            # the instrument rejects the limit command
    with pytest.raises(SystemExit) as e:
        cli.main(["dc2200", "ramp", "--min", "0", "--max", "0.2", "--step", "0.1",
                  "--step-time", "0.01", "--output-csv", "/dev/null"])
    assert "refused 'SOUR1:CURR:LIM:AMPL" in str(e.value.code)
    assert "OUTP1:STAT ON" not in dc.log and not dc.on


def test_readback_mismatch_is_an_error(fake_visa):
    _, dc, _ = fake_visa
    dc.readback_offset = 0.05
    with pytest.raises(RuntimeError, match="user current limit is"):
        dc2200.DC2200SCPI(dc).set_user_current_limit(0.3)


def test_current_above_the_limit_is_detected(fake_visa):
    _, dc, _ = fake_visa
    drv = dc2200.DC2200SCPI(dc)
    drv.set_user_current_limit(0.1)
    with pytest.raises(RuntimeError, match="LED current is 0.1 A after setting 0.2 A"):
        drv.configure_constant_current(0.2)


def test_not_a_dc2200(fake_visa):
    with pytest.raises(RuntimeError, match="not a DC2200"):
        dc2200.DC2200SCPI(FakeDC2200Inst(idn="Thorlabs,PM400,P1,1.0"))


# ---------------------------------------------------------------------------
# PM400 on the same layer
# ---------------------------------------------------------------------------
def test_pm400_through_visa(fake_visa):
    from equipment.thorlabs.pm400 import open_pm400
    _, _, pm = fake_visa
    with open_pm400(wavelength=470, averaging_count=5, verbose=False) as meter:
        assert meter.read_power() == pytest.approx(1.25e-3)
    assert "SENS:CORR:WAV 470" in pm.log and "SENS:AVER:COUN 5" in pm.log and pm.closed


# ---------------------------------------------------------------------------
# Windows specifics
# ---------------------------------------------------------------------------
def test_canon_on_windows_says_why(monkeypatch):
    from equipment.canon.camera import import_gphoto2
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="not supported on Windows"):
        import_gphoto2()


def test_devices_on_windows_uses_visa(fake_visa, monkeypatch):
    from equipment import devices
    monkeypatch.setattr(sys, "platform", "win32")
    found = devices.probe_thorlabs()
    assert ("Thorlabs DC2200 LED driver",
            "serial M00937194 (USB0::0x1313::0x80C8::M00937194::INSTR)") in found
    assert any("PM400" in name for name, _ in found)
    with pytest.raises(RuntimeError, match="Windows"):
        devices.probe_canon()


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("system", ["fedora", "ubuntu", "macos", "windows"])
def test_doctor_never_crashes(system):
    name, checks = doctor.run_checks(system)
    groups = {c.group for c in checks}
    assert {"Python", "Thorlabs DC2200/PM400", "CoolLED pE-300", "FLIR Blackfly S",
            "Canon EOS R10", "Data"} <= groups
    assert all(c.status in (doctor.OK, doctor.WARN, doctor.FAIL, doctor.NA) for c in checks)
    canon = [c for c in checks if c.group == "Canon EOS R10"]
    assert (canon[0].status == doctor.NA) == (system == "windows")
    for c in checks:
        if c.status == doctor.FAIL:
            assert c.fix or "check failed" in c.text or c.group == "Python"
    linux_only = [c for c in checks if "udev" in c.text or "usbfs" in c.text
                  or "dialout" in c.text]
    if system in ("macos", "windows"):
        assert linux_only == []                       # no udev, groups or usbfs there


def test_doctor_fixes_point_to_the_right_installer():
    for system in ("fedora", "ubuntu", "macos"):
        _, checks = doctor.run_checks(system)
        assert not any("install.bat" in c.fix for c in checks), system
        assert not any("dnf" in c.fix for c in checks if system != "fedora"), system
    _, windows = doctor.run_checks("windows")
    assert not any("install.sh" in c.fix for c in windows)


@pytest.mark.parametrize("release,expected", [
    ({"ID": "fedora"}, "fedora"),
    ({"ID": "ubuntu", "ID_LIKE": "debian"}, "ubuntu"),
    ({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, "ubuntu"),
    ({"ID": "debian"}, "ubuntu"),
    ({"ID": "rocky", "ID_LIKE": "rhel centos fedora"}, "fedora"),
    ({"ID": "arch"}, "linux"),
])
def test_system_name_on_linux(monkeypatch, release, expected):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor, "_os_release", lambda: release)
    assert doctor.system_name() == expected


def test_system_name_macos_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert doctor.system_name() == "macos"
    monkeypatch.setattr(sys, "platform", "win32")
    assert doctor.system_name() == "windows"


def test_no_kernel_driver_detach_on_macos(fake_visa, monkeypatch):
    """macOS has no usbtmc driver: the Thorlabs instrument is opened directly."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv(visa.ENV_VAR, "@py")

    def boom(*a, **k):
        raise AssertionError("the kernel driver must not be touched on macOS")
    monkeypatch.setattr(visa, "ThorlabsUSBDriver", boom)
    monkeypatch.delenv("EQUIPMENT_DC2200_DRIVER")
    assert dc2200.dc2200_driver() == "builtin"
    with visa.open_instrument("USB0::4883::32968::M00937194::0::INSTR", DC2200_PRODUCT_ID):
        pass


def test_canon_claim_hint_per_system(monkeypatch):
    from types import SimpleNamespace
    from equipment.canon.camera import _connect_hint
    gp = SimpleNamespace(GP_ERROR_IO_USB_CLAIM=-53, GP_ERROR_MODEL_NOT_FOUND=-105)
    err = SimpleNamespace(code=-53)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "ptpcamerad" in _connect_hint(gp, err)
    monkeypatch.setattr(sys, "platform", "linux")
    assert "gvfs" in _connect_hint(gp, err)


def test_doctor_command_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_call", lambda target, cfg=None: 2 if target == "doctor:main_doctor"
                        else None)
    with pytest.raises(SystemExit) as e:
        cli.main(["doctor"])
    assert e.value.code == 1
    monkeypatch.setattr(cli, "_call", lambda target, cfg=None: 0)
    cli.main(["doctor"])                                   # no exception when all is fine


def test_doctor_output(capsys, monkeypatch):
    from equipment import devices
    monkeypatch.setattr(devices, "PROBES", ())
    doctor.main_doctor()
    out = capsys.readouterr().out
    assert out.startswith("System: ") and "Thorlabs DC2200/PM400" in out
    assert "Connected instruments:" in out
