# Windows installer

`install.bat` (which starts `install.ps1`) sets up the lab software on Windows 10/11. The DC2200, PM400, pE-300 and FLIR Blackfly S all work; administrator rights are not needed.

**Not on Windows:** the Canon EOS R10. Its USB library, libgphoto2, exists only for Linux and macOS, so use the Canon on a Fedora, Ubuntu or Mac computer.

Contents: [Requirements](#requirements) · [Before installing](#before-installing-manufacturer-software) · [Install](#install) · [What it changes](#what-it-changes) · [Options](#options) · [After installing](#after-installing) · [Updating](#updating) · [Undo](#undo) · [Troubleshooting](#troubleshooting)

## Requirements

- Windows 10 (1809 or newer) or Windows 11, 64-bit
- an internet connection
- Python 3.10–3.12. If none is found, the installer installs it with `winget`, which is built into current Windows.

## Before installing: manufacturer software

The instrument drivers can't be shipped with this code, so install them yourself first:

| For | Download | Where | Notes |
|---|---|---|---|
| DC2200 | DC2200 software | thorlabs.com → DC2200 → Software | brings **NI-VISA**, which `equipment` uses |
| PM400 | Optical Power Monitor | thorlabs.com → PM400 → Software | in its **Power Meter Driver Switcher**, set the PM400 to **TLPM (VISA)** |
| FLIR camera | Spinnaker SDK, Windows 64-bit | teledynevisionsolutions.com (free account) | install it: it brings the camera's USB3 driver |
| FLIR camera | Spinnaker **Python** package, e.g. for Python 3.12 (`cp312`) | same page | **don't install it**: leave the `.zip` or `.whl` in Downloads |

The pE-300 needs nothing: Windows 10/11 has its USB serial driver built in (it shows up as one or two `COM` ports).

## Install

1. Get `LAB`: on github.com/matijalakner/LAB use **Code → Download ZIP** and unpack it (e.g. to `Documents\LAB`), or `git clone https://github.com/matijalakner/LAB.git`.
2. Double-click **`install.bat`** in the `LAB` folder.

A console window shows each step; at the end, press a key to close it. If Windows SmartScreen asks, choose *More info → Run anyway* (the script is unsigned).

## What it changes

| Step | What | Where |
|---|---|---|
| 1. Python | finds Python 3.10–3.12, the versions PySpin exists for; the Spinnaker wheel you downloaded decides which. If none is installed: `winget install Python.Python.3.12` (for your user only) | `%LOCALAPPDATA%\Programs\Python` |
| 2. Python environment | `LAB\lab` | `LAB\lab` |
| 3. Python packages | `equipment` with the thorlabs, coolled and flir extras, and `line-analysis` | `LAB\lab` |
| 4. NI-VISA | checks that the VISA library is there (`visa64.dll`); it comes with the Thorlabs software | nothing is changed |
| 5. Spinnaker / PySpin | installs PySpin from the wheel in Downloads (it unpacks the `.zip` if needed) | `LAB\lab` |
| 6. LAB terminal | `LAB\lab-terminal.cmd` opens a terminal with the environment active; a **LAB terminal** shortcut to it goes on the desktop | `LAB`, Desktop |
| 7. Check | `equipment doctor` | prints only |

It also creates `LAB\data\input` and `LAB\data\output` if they are missing. Nothing is written outside your user folder and `LAB`.

## Options

Pass options to `install.bat` in a terminal opened in `LAB`. All of them are described in the built-in help: `Get-Help .\equipment\packaging\windows\install.ps1 -Full`.

| Option | Effect |
|---|---|
| `-Python 3.11` | use this Python version |
| `-SpinnakerWheel C:\path\spinnaker_python-...whl` | the Spinnaker wheel (or its `.zip`), if it is not in Downloads |
| `-PythonOnly` | only steps 1–3 and 7: make or update the Python environment |
| `-NoShortcut` | no desktop shortcut |

Example: `install.bat -Python 3.11 -SpinnakerWheel C:\Temp\spinnaker_python-4.2.0.83-cp311-cp311-win_amd64.zip`

## After installing

1. **Every time you work**, double-click **LAB terminal** on the desktop. In that window the `equipment` and `analysis` commands are available.
2. **Check** with `equipment doctor`. It lists what is ready and what is missing, with the fix.
3. If the check reports something missing (e.g. PySpin, because the Spinnaker wheel wasn't in Downloads yet), add it and double-click `install.bat` again. Running it again is always safe.

## Updating

Download the new `LAB` (or `git pull`), then:

```bat
install.bat -PythonOnly
```

## Undo

1. Delete the `LAB\lab` folder (the environment) and `LAB\lab-terminal.cmd`.
2. Delete the **LAB terminal** shortcut from the desktop.
3. Optional: uninstall Python, the Thorlabs software and Spinnaker in *Settings → Apps*.

## Troubleshooting

| Problem | Fix |
|---|---|
| `winget is not available` | install Python 3.12 from python.org (tick *Add python.exe to PATH*), then run `install.bat` again |
| `no VISA library found` | install the Thorlabs DC2200 software or Optical Power Monitor (or NI-VISA from ni.com), then run again |
| the PM400 is not found | Thorlabs' *Power Meter Driver Switcher*: set the PM400 to **TLPM (VISA)**, then replug it |
| `could not open USB0::... (serial ...)` | another unit is connected: the message shows its serial number; use it with `--dc2200-serial` / `--pm400-serial` |
| `the Spinnaker wheel is for Python 3.X` | delete `LAB\lab` and run `install.bat -Python 3.X` |
| `PySpin is not installed` | download the Spinnaker Python package for the Python version shown, into Downloads, and run again |
| the FLIR camera is not found | use a USB3 (blue) port; check that the Spinnaker SDK is installed (SpinView should see the camera) |
| the pE-300 is not found | check that it shows up in *Device Manager → Ports (COM & LPT)*; give the port with `--port COM5` |
| the window closes immediately | open a terminal (`cmd`) in `LAB` and run `install.bat` there to see the message |
| anything else | `equipment doctor` in the LAB terminal, and its `fix:` lines |
