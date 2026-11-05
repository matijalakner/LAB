"""The installers in packaging/: present, valid, documented and consistent with the code.

These run without installing anything: they check the files, run bash's syntax
check and --help, and the system recognition of LAB/install.sh.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
LAB = PACKAGING.parents[1]
UNIX = ("fedora", "ubuntu", "macos")
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None or sys.platform.startswith("win"),
                                reason="needs bash")


def unix_scripts():
    return [PACKAGING / s / "install.sh" for s in UNIX] + [PACKAGING / "common" / "lib.sh"]


@pytest.mark.parametrize("system", UNIX + ("windows",))
def test_every_system_has_an_installer_and_a_readme(system):
    folder = PACKAGING / system
    assert (folder / ("install.ps1" if system == "windows" else "install.sh")).is_file()
    readme = (folder / "README.md").read_text(encoding="utf-8")
    for section in ("## Requirements", "## Install", "## What it changes", "## Options",
                    "## After installing", "## Updating", "## Undo", "## Troubleshooting"):
        assert section in readme, f"{system}/README.md lacks {section}"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="file modes")
@pytest.mark.parametrize("script", [PACKAGING / s / "install.sh" for s in UNIX]
                         + [LAB / "install.sh"])
def test_installers_are_executable(script):
    assert os.access(script, os.X_OK), f"{script} is not executable (chmod +x)"


@needs_bash
@pytest.mark.parametrize("script", unix_scripts() + [LAB / "install.sh", LAB / "setup.sh"])
def test_bash_syntax(script):
    subprocess.run([BASH, "-n", str(script)], check=True)


@needs_bash
@pytest.mark.parametrize("system", UNIX)
def test_help_lists_the_options_and_steps(system):
    out = subprocess.run([BASH, str(PACKAGING / system / "install.sh"), "--help"],
                         capture_output=True, text=True, check=True).stdout
    assert out.startswith("Install the lab software on")
    for word in ("--no-canon", "--no-flir", "--python-only", "Steps:", "README.md"):
        assert word in out, f"{system} --help lacks {word}"


@pytest.mark.parametrize("script", unix_scripts())
def test_bash_32_compatible(script):
    """macOS ships bash 3.2: none of the newer bash features may be used."""
    text = script.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for pattern, what in ((r"\bmapfile\b|\breadarray\b", "mapfile/readarray"),
                          (r"declare -A|local -A", "associative arrays"),
                          (r"\$\{\w+(,,|\^\^)\}", "${var,,} / ${var^^}"),
                          (r"&>>", "&>>"), (r"\|&", "|&"),
                          (r'^\s*main "\$@"', 'main "$@" (use ${1+"$@"})')):
        assert not re.search(pattern, code, re.M), f"{script.name}: {what}"


def test_udev_rules_match_the_code():
    from equipment.coolled.pe300 import USB_ID
    from equipment.thorlabs.usb_driver import THORLABS_VENDOR_ID
    rules = (PACKAGING / "common" / "99-lab-equipment.rules").read_text().lower()
    assert f'"{THORLABS_VENDOR_ID:04x}"' in rules
    assert f'"{USB_ID[0]:04x}"' in rules and f'"{USB_ID[1]:04x}"' in rules
    assert '"1e10"' in rules                                   # FLIR / Point Grey


def test_windows_files_are_ascii_and_crlf_in_git():
    for f in ("install.ps1", "install.bat"):
        (PACKAGING / "windows" / f).read_bytes().decode("ascii")   # PowerShell 5.1 safe
    attrs = (LAB / ".gitattributes").read_text()
    for pattern in ("*.ps1", "*.bat", "*.sh"):
        assert pattern in attrs


@needs_bash
@pytest.mark.parametrize("system,expected", [("windows", "install.bat"),
                                             ("arch", "not recognised")])
def test_lab_install_sh_refuses_what_it_cannot_install(system, expected):
    r = subprocess.run([BASH, str(LAB / "install.sh")], capture_output=True, text=True,
                       env={**os.environ, "LAB_SYSTEM": system})
    assert r.returncode == 1 and expected in r.stderr


def test_ensure_libusb_findable_on_macos(monkeypatch):
    from equipment.thorlabs import visa
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os.path, "isdir", lambda d: d in ("/opt/homebrew/lib", "/usr/lib"))
    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "/mine")
    visa.ensure_libusb_findable()
    assert os.environ["DYLD_FALLBACK_LIBRARY_PATH"] == "/mine:/opt/homebrew/lib:/usr/lib"
    visa.ensure_libusb_findable()                                # only once
    assert os.environ["DYLD_FALLBACK_LIBRARY_PATH"] == "/mine:/opt/homebrew/lib:/usr/lib"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "")
    visa.ensure_libusb_findable()
    assert os.environ["DYLD_FALLBACK_LIBRARY_PATH"] == ""          # only on macOS
