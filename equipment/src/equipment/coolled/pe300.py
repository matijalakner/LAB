"""CoolLED pE-300 (white / ultra) LED illumination over its USB virtual serial port.

Protocol (CoolLED Commands Manual DOC-038): 57600 baud, ASCII commands ending
in CR, replies ending in CR LF. Three channels A, B, C (pE-300white: violet/UV,
blue, green-yellow-red), each one

    selected (S) or deselected (X),  on (N) or off (F),  intensity 000 - 100 %

    CSS?                    status of all channels, reply e.g. CSSASN050BSF050CXF000
    CSSASN050BSN050CXF000   set all channels at once (long form; also the reply)
    CSN / CSF               all selected channels on / off
    XVER, LAMS              firmware versions, installed wavelengths

A deselected channel is always off (the pE-300white refuses "XN"), so a channel
is lit only when it is selected AND on. Every set command is checked by reading
the status back.

pyserial is imported lazily, so the package works without it.
"""
import os
import re
import time
from dataclasses import dataclass

from ..sources import LightSource
from ..utils import read_cfg

BAUD = 57600
CHANNELS = "ABC"
PORT_ENV = "EQUIPMENT_PE300_PORT"
_CSS_ITEM = re.compile(r"([ABCD])([SX])([NF])(\d{1,3})")
_PORT_WORDS = ("coolled", "pe-300", "pe300")


@dataclass(frozen=True)
class Channel:
    selected: bool
    on: bool
    intensity: int

    @property
    def lit(self):
        return self.selected and self.on


def parse_css(line):
    """'CSSASN050BSF050CXF000' -> {'A': Channel(True, True, 50), ...}."""
    line = line.strip().upper()
    if not line.startswith("CSS"):
        raise ValueError(f"not a CSS status line: {line!r}")
    out = {}
    for ch, sel, on, value in _CSS_ITEM.findall(line[3:]):
        out[ch] = Channel(sel == "S", on == "N", int(value))
    if not out:
        raise ValueError(f"no channels in CSS line: {line!r}")
    return out


def css_command(states):
    """{'A': Channel(...), ...} -> 'CSSASN050BXF020...'."""
    parts = []
    for ch in sorted(states):
        c = states[ch]
        on = c.on and c.selected                      # XN is not allowed
        parts.append(f"{ch}{'S' if c.selected else 'X'}{'N' if on else 'F'}"
                     f"{int(c.intensity):03d}")
    return "CSS" + "".join(parts)


def normalize_channels(channels):
    """'abc', 'A,C', ['A', 'B'] -> 'ABC', 'AC', 'AB'; None -> 'ABC'."""
    text = "".join(CHANNELS if channels is None else channels).upper().replace(",", "").replace(" ", "")
    if not text or any(c not in CHANNELS for c in text):
        raise ValueError(f"channels must be letters from {CHANNELS}, got '{channels}'")
    return "".join(c for c in CHANNELS if c in text)


def check_intensity(value):
    v = float(value)
    if not 0 <= v <= 100:
        raise ValueError(f"intensity must be between 0 and 100 %, got {value}")
    return int(round(v))


def _import_serial():
    try:
        import serial
        import serial.tools.list_ports
    except ImportError as e:
        raise RuntimeError("pyserial is required for the pE-300: "
                           "pip install -e \".[coolled]\"") from e
    return serial


def candidate_ports():
    """[(device, description)] of serial ports that identify as CoolLED."""
    serial = _import_serial()
    out = []
    for p in serial.tools.list_ports.comports():
        text = " ".join(str(x) for x in (p.description, p.manufacturer, p.product,
                                          p.interface) if x).lower()
        if any(w in text for w in _PORT_WORDS):
            out.append((p.device, p.description or ""))
    return out


def _probe(port, timeout=0.6):
    """True if a pE-300 answers 'CSS?' on ``port``."""
    serial = _import_serial()
    try:
        with serial.Serial(port, BAUD, timeout=0.1, write_timeout=0.5) as s:
            s.reset_input_buffer()
            s.write(b"CSS?\r")
            end = time.monotonic() + timeout
            buf = b""
            while time.monotonic() < end:
                buf += s.read(64)
                if b"CSS" in buf.upper() and b"\n" in buf:
                    return True
    except (OSError, serial.SerialException):
        return False
    return False


def find_port(port=None):
    """The pE-300's serial port: argument > $EQUIPMENT_PE300_PORT > a port that
    identifies as CoolLED > the first USB serial port that answers 'CSS?'."""
    if port or os.environ.get(PORT_ENV):
        return port or os.environ[PORT_ENV]
    named = candidate_ports()
    if len(named) == 1:
        return named[0][0]
    if len(named) > 1:
        raise RuntimeError("more than one CoolLED port found ("
                           + ", ".join(d for d, _ in named) + "); choose one with --port")
    serial = _import_serial()
    usb = [p.device for p in serial.tools.list_ports.comports()
           if p.vid is not None or re.search(r"ttyACM|ttyUSB|usbmodem|COM\d", p.device)]
    found = [d for d in usb if _probe(d)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise RuntimeError("no pE-300 found. Check the USB cable and power, that your "
                           "user may open serial ports (Linux: group 'dialout'), and give "
                           f"the port with --port or ${PORT_ENV} (e.g. /dev/ttyACM0, COM3).")
    raise RuntimeError("more than one pE-300 answered (" + ", ".join(found)
                       + "); choose one with --port")


class PE300:
    """Low-level pE-300: send a command, read its reply lines.

    >>> with PE300() as pe:
    ...     pe.set_channels("ABC", 30, on=True)
    ...     print(pe.status())
    """

    def __init__(self, port=None, timeout=2.0):
        self.port_wanted = port
        self.port = None
        self.timeout = timeout
        self.ser = None

    # -- connection -------------------------------------------------------------
    def open(self):
        serial = _import_serial()
        self.port = find_port(self.port_wanted)
        try:
            self.ser = serial.Serial(self.port, BAUD, timeout=0.05, write_timeout=1.0)
        except serial.SerialException as e:
            raise RuntimeError(f"could not open {self.port}: {e} (is another program "
                               "using it? Linux: is your user in the 'dialout' group?)") from e
        try:
            self.status()
        except Exception as e:
            self.close()
            raise RuntimeError(f"no pE-300 answer on {self.port}: {e}") from e
        return self

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- commands ---------------------------------------------------------------
    def command(self, cmd, until=None, idle=0.15):
        """Send ``cmd`` and return the reply lines.

        Reading stops at the first line for which ``until(line)`` is true, or
        else ``idle`` seconds after the last line; a command with ``until``
        that gets no matching line within the timeout raises TimeoutError.
        """
        if self.ser is None:
            raise RuntimeError("the pE-300 is not open")
        self.ser.reset_input_buffer()            # drop XLIVE reports and old replies
        self.ser.write(cmd.strip().upper().encode("ascii") + b"\r")
        self.ser.flush()
        lines, buf = [], b""
        end = time.monotonic() + self.timeout
        last = None
        while time.monotonic() < end:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                while b"\n" in buf or b"\r" in buf:
                    i = min(x for x in (buf.find(b"\n"), buf.find(b"\r")) if x >= 0)
                    line, buf = buf[:i].decode("ascii", "replace").strip(), buf[i + 1:]
                    if line:
                        lines.append(line)
                        last = time.monotonic()
                        if until is not None and until(line):
                            return lines
            elif until is None and last is not None and time.monotonic() - last > idle:
                return lines
        if until is not None:
            raise TimeoutError(f"no reply to '{cmd}' within {self.timeout:g} s"
                               + (f" (got: {' | '.join(lines)})" if lines else ""))
        return lines

    def _css(self, cmd):
        lines = self.command(cmd, until=lambda ln: ln.upper().startswith("CSS"))
        return parse_css(lines[-1])

    def status(self):
        """{'A': Channel(selected, on, intensity), 'B': ..., 'C': ...}"""
        return self._css("CSS?")

    def apply(self, states):
        """Set every channel in ``states`` and verify it by reading the status back."""
        self._css(css_command(states))
        now = self.status()
        for ch, want in states.items():
            got = now.get(ch)
            want_on = want.on and want.selected
            if got is None or (got.selected, got.on and got.selected, got.intensity) != \
                    (want.selected, want_on, int(want.intensity)):
                raise RuntimeError(f"pE-300 channel {ch} is {got}, expected {want} "
                                   "(is the Control Pod being used at the same time?)")
        return now

    def set_channels(self, channels, intensity, on=True):
        """Select ``channels`` at ``intensity`` %, on or off; deselect the others
        (their intensity setting is kept)."""
        channels = normalize_channels(channels)
        intensity = check_intensity(intensity)
        current = self.status()
        states = {}
        for ch, c in current.items():
            if ch in channels:
                states[ch] = Channel(True, on, intensity)
            else:
                states[ch] = Channel(False, False, c.intensity)
        return self.apply(states)

    def all_off(self):
        """Switch every channel off, keep selection and intensities (verified)."""
        current = self.status()
        return self.apply({ch: Channel(c.selected, False, c.intensity)
                           for ch, c in current.items()})

    def version(self):
        return self.command("XVER")

    def wavelengths(self):
        """{'A': '1UV', ...} from LAMS (empty dict if the unit does not answer it)."""
        out = {}
        for line in self.command("LAMS"):
            parts = line.split(":")
            if len(parts) == 3 and parts[0].upper() == "LAM" and "-" not in parts[2]:
                out[parts[1].upper()] = parts[2]
        return out


# ---------------------------------------------------------------------------
# as a light source
# ---------------------------------------------------------------------------
class PE300Source(LightSource):
    """pE-300 as a light source: the level is the intensity in % of the chosen
    channels (all at the same value); the other channels are switched off."""

    key = "pe300"
    name = "pE-300"
    unit = "%"
    column = "intensity_pct"
    max_level = 100

    def __init__(self, port=None, channels=CHANNELS):
        self.channels = normalize_channels(channels)
        self.port = port
        self.dev = None
        self._level = 0
        self._on = False

    @classmethod
    def from_cfg(cls, cfg):
        get = read_cfg(cfg)
        return cls(port=get("port"), channels=get("channels") or CHANNELS)

    def open(self):
        self.dev = PE300(self.port).open()
        print(f"pE-300 on {self.dev.port}, channels {self.channels}.")
        return self

    def close(self):
        if self.dev is not None:
            self.dev.close()
            self.dev = None

    def quantize(self, level):
        return int(round(level))                  # the unit has 1 % steps

    def set_level(self, level):
        self._level = self.check_level(level, "intensity")
        self.dev.set_channels(self.channels, self._level, on=self._on)

    def switch_on(self):
        self._on = True
        self.dev.set_channels(self.channels, self._level, on=True)

    def switch_off(self):
        self._on = False
        if self.dev is not None:
            self.dev.all_off()

    def fmt(self, level):
        return f"{level:g} %"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def main_pe300_set(cfg):
    """Set ``intensity`` (%) on ``channels`` (default ABC) and LEAVE THE LIGHT ON.

    cfg: intensity; optional channels, port. 0 switches the light off.
    """
    get = read_cfg(cfg)
    if get("intensity") is None:
        raise ValueError("setting 'intensity' is missing")
    intensity = check_intensity(get("intensity"))
    with PE300Source.from_cfg(cfg) as light:
        if intensity == 0:
            print("pE-300 light switched off.")
            return
        light.set_level(intensity)
        light.switch_on()
        light.leave_on = True
        print(f"pE-300 ON: channels {light.channels} at {intensity} %.")


def main_pe300_off(cfg=None):
    """Switch all channels of the pE-300 off. cfg: optional port."""
    with PE300(read_cfg(cfg)("port")) as pe:
        pe.all_off()
    print("pE-300 light switched off.")


def main_pe300_status(cfg=None):
    """Print port, versions, wavelengths and the state of every channel."""
    with PE300(read_cfg(cfg)("port")) as pe:
        print(f"port              {pe.port}")
        for line in pe.version():
            if "=" in line:
                key, value = line.split("=", 1)
                print(f"{key.lstrip('X').lower():<17} {value}")
        names = pe.wavelengths()
        status = pe.status()
    for ch, c in status.items():
        state = "ON " if c.lit else "off"
        sel = "selected" if c.selected else "deselected"
        print(f"channel {ch} {names.get(ch, ''):<6} {state} {c.intensity:3d} %  ({sel})")
    return status
