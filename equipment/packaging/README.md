# Installers

| Folder | System | Start it with |
|---|---|---|
| [`fedora/`](fedora) | Fedora | `./install.sh` in `LAB` (or `fedora/install.sh` here) |
| [`windows/`](windows) | Windows 10/11 | `install.bat` in `LAB` (or `windows/install.bat` here) |

**Start with the step-by-step guide: [INSTALL.md](../../INSTALL.md).** It includes the manufacturer software to install first on Windows.

Files:

| File | What it is |
|---|---|
| `fedora/install.sh` | the Fedora installer (`--help` lists its options) |
| `fedora/99-lab-equipment.rules` | the Fedora USB permissions (udev rules) it installs: Thorlabs `1313`, pE-300 `0483:a080`, FLIR `1e10` |
| `windows/install.ps1` | the Windows installer (PowerShell), with options `-Python 3.11`, `-SpinnakerWheel <file>`, `-NoShortcut` |
| `windows/install.bat` | starts `install.ps1` on a double-click |

Both installers can be run again at any time, and both end with `equipment doctor`, which checks every instrument.
