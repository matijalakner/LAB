# Installers

One installer per operating system. Each sets up everything the lab instruments need on that system (drivers, libraries, permissions and the Python environment), then checks the result with `equipment doctor`.

**To install, follow [INSTALL.md](../../INSTALL.md) in `LAB`.** This page is the overview for whoever maintains the installers.

| System | Start it with | Documentation |
|---|---|---|
| Fedora (also RHEL-like) | `./install.sh` in `LAB` | [fedora/README.md](fedora/README.md) |
| Ubuntu 22.04+ (also Debian, Mint, Pop!_OS) | `./install.sh` in `LAB` | [ubuntu/README.md](ubuntu/README.md) |
| macOS 13+ (Apple Silicon or Intel) | `./install.sh` in `LAB` | [macos/README.md](macos/README.md) |
| Windows 10/11 | `install.bat` in `LAB` | [windows/README.md](windows/README.md) |

`./install.sh` in `LAB` recognises the system and starts the right installer. To choose one yourself, set `LAB_SYSTEM` (e.g. `LAB_SYSTEM=ubuntu ./install.sh`).

## What works where

| Instrument | Fedora | Ubuntu | macOS | Windows |
|---|---|---|---|---|
| Thorlabs DC2200, PM400 | ✓ pyvisa-py + libusb | ✓ pyvisa-py + libusb | ✓ pyvisa-py + libusb | ✓ NI-VISA |
| CoolLED pE-300 | ✓ `/dev/ttyACM*` | ✓ `/dev/ttyACM*` | ✓ `/dev/cu.usbmodem*` | ✓ `COM*` |
| FLIR Blackfly S | ✓ Aravis (built) | ✓ Aravis (package) | ✓ Aravis (Homebrew) | ✓ Spinnaker |
| Canon EOS R10 | ✓ libgphoto2 | ✓ libgphoto2 | ✓ libgphoto2 | ✗ |

The Canon can't work on Windows because libgphoto2, the library that controls it over USB, exists only for Linux and macOS.

## What each installer does

| | Fedora | Ubuntu | macOS | Windows |
|---|---|---|---|---|
| Package manager | dnf | apt | Homebrew | winget (Python only) |
| Python | `/usr/bin/python3` | `/usr/bin/python3` | Homebrew's (the one with PyGObject) | python.org 3.10–3.12 |
| FLIR library | Aravis 0.8.36 built into `/usr/local` | `gir1.2-aravis-0.8` (or built) | `brew install aravis` | PySpin from the Spinnaker wheel |
| USB permissions | udev rules | udev rules | not needed | the drivers' installers |
| Serial ports | udev rule + `dialout` | udev rule + `dialout` | not needed | built in |
| USB buffer for the FLIR | systemd unit, 1000 MB | systemd unit, 1000 MB | not needed | not needed |
| Environment | `LAB/lab` | `LAB/lab` | `LAB/lab` | `LAB\lab` |
| Afterwards | `source setup.sh` | `source setup.sh` | `source setup.sh` | **LAB terminal** shortcut |
| Needs root | sudo (asked once) | sudo (asked once) | no | no |

The **environment** is always made with access to the system's Python packages (`--system-site-packages`), because the GObject bindings for Aravis come from the system, not from pip. Windows is the exception; it doesn't need them.

## Options

Fedora, Ubuntu and macOS take the same options; Windows has its PowerShell equivalents:

| Unix | Windows | Effect |
|---|---|---|
| `--no-canon` | (no Canon on Windows) | skip the Canon camera |
| `--no-flir` | (skip the Spinnaker wheel) | skip the FLIR camera library |
| `--mask-gvfs` | | Linux: stop GNOME from grabbing the Canon over USB |
| `--python-only` | `-PythonOnly` | only make or update the Python environment |
| | `-Python 3.11` | use this Python version |
| | `-SpinnakerWheel <file>` | the Spinnaker wheel, if it is not in Downloads |
| | `-NoShortcut` | no desktop shortcut |
| `--help` | `Get-Help .\install.ps1 -Full` | the built-in help |

Every installer can be run again at any time. Steps that are already done are skipped or simply repeated, so running it again also updates the Python packages.

## Layout

```text
packaging/
├── README.md                     this overview
├── common/                       shared by the Fedora, Ubuntu and macOS installers
│   ├── lib.sh                    the building blocks (output, options, paths, udev,
│   │                             USB buffer, Aravis build, environment, doctor)
│   ├── 99-lab-equipment.rules    udev rules: Thorlabs 1313, pE-300 0483:a080, FLIR 1e10
│   └── lab-usbfs-memory.service  systemd unit: 1000 MB USB buffer at every boot
├── fedora/   install.sh  README.md
├── ubuntu/   install.sh  README.md
├── macos/    install.sh  README.md
└── windows/  install.ps1 install.bat README.md
```

## How the Unix installers are built

All three installers have the same shape, so a change in one is easy to make in the others:

```bash
source ../common/lib.sh             # the shared building blocks

install_system_packages() { ... }   # one function per step that is specific
install_aravis()          { ... }   # to this system

main() {
  parse_options ${1+"$@"}           # --no-canon, --no-flir, --mask-gvfs, --python-only
  find_paths                        # EQUIPMENT, LAB, VENV
  require_normal_user
  LAB_STEPS=7
  step "System packages (dnf)";  install_system_packages     # "== 1/7  System packages"
  step "Aravis 0.8";             install_aravis
  ...                                                        # shared steps from lib.sh:
  step "Python environment";     make_environment "$PYTHON"
  step "Python packages";        install_lab_packages
  step "Check";                  run_doctor
  finish "reminders for this system"
}
```

Rules the scripts follow:

- **bash 3.2.** macOS still ships bash 3.2, so the scripts use no associative arrays, no `mapfile`, no `${var,,}`, and no `"${array[@]}"` or `"$@"` that could be empty under `set -u` (`${1+"$@"}` instead).
- **`set -euo pipefail`.** Any failing command stops the installer, with the step it was in still visible.
- **Normal user, sudo only where needed.** The environment must belong to the user, and the password is asked once, at the start.
- **Safe to run again.** Every step checks what is already there.
- **shellcheck-clean.** Check with `shellcheck -x */install.sh common/lib.sh` from this folder.

The Windows installer has the same shape in PowerShell: one function per step and a short main block at the end. It uses PowerShell's standard comment-based help, and it is written for Windows PowerShell 5.1, which is built into Windows.

## Adding a step

1. Write a function for it, in `common/lib.sh` if more than one system needs it, otherwise in that system's `install.sh`.
2. Call it from `main` with `step "Title"; your_function`, and increase `LAB_STEPS`.
3. Add it to the step list at the top of the installer (that is its `--help`) and to the system's README.
4. If it installs something `equipment doctor` can check, add the check to `src/equipment/doctor.py`, with the fix for each system.
