# Installing the lab software

This sets up everything to run the lab instruments and analyse the measurements:

- **Thorlabs DC2200** LED driver and **PM400** power meter
- **CoolLED pE-300** light source
- **FLIR Blackfly S** camera
- **Canon EOS R10** camera

There is one installer per system. Pick yours, follow its steps in order, and finish with [the check](#check-that-everything-works).

| Your computer | Go to | Time |
|---|---|---|
| Fedora | [Fedora](#fedora) | about 15 min (it compiles the camera library) |
| Ubuntu (or Debian, Linux Mint, Pop!_OS) | [Ubuntu](#ubuntu) | about 5 min |
| macOS (Apple Silicon or Intel) | [macOS](#macos) | about 10 min |
| Windows 10/11 | [Windows](#windows) | about 10 min, plus the manufacturer downloads |

| Instrument | Fedora | Ubuntu | macOS | Windows |
|---|---|---|---|---|
| DC2200, PM400 | ✓ | ✓ | ✓ | ✓ |
| pE-300 | ✓ | ✓ | ✓ | ✓ |
| FLIR Blackfly S | ✓ | ✓ | ✓ | ✓ |
| Canon EOS R10 | ✓ | ✓ | ✓ | ✗ (its USB library exists only for Linux and macOS) |

Each installer has its own detailed page (what it changes, options, how to undo it, troubleshooting) in [`equipment/packaging/`](equipment/packaging).

---

## Fedora

**1. Get the code.** Open a terminal:

```bash
sudo dnf install git          # if git is missing
git clone https://github.com/matijalakner/LAB.git
cd LAB
```

**2. Run the installer** as your normal user (not with `sudo`; it asks for your password once):

```bash
./install.sh
```

It installs the system packages, builds the FLIR camera library (Aravis), sets USB permissions so no `sudo` is needed for the instruments, and creates the Python environment `LAB/lab`. Options: `./install.sh --help`.

**3. Log out and back in once** (and reboot once, so the camera's USB buffer setting is in place).

**4. Every time you work:**

```bash
cd LAB
source setup.sh
```

Details: [equipment/packaging/fedora/README.md](equipment/packaging/fedora/README.md)

---

## Ubuntu

**1. Get the code.** Open a terminal:

```bash
sudo apt install git          # if git is missing
git clone https://github.com/matijalakner/LAB.git
cd LAB
```

**2. Run the installer** as your normal user (not with `sudo`; it asks for your password once):

```bash
./install.sh
```

It installs the system packages and the FLIR camera library (Ubuntu's Aravis package), sets USB permissions so no `sudo` is needed for the instruments, and creates the Python environment `LAB/lab`. Options: `./install.sh --help`.

**3. Log out and back in once.**

**4. Every time you work:**

```bash
cd LAB
source setup.sh
```

Details: [equipment/packaging/ubuntu/README.md](equipment/packaging/ubuntu/README.md)

---

## macOS

**1. Install Homebrew** (skip this if you have it). Open Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow what it prints at the end, then open a new Terminal window.

**2. Get the code:**

```bash
git clone https://github.com/matijalakner/LAB.git
cd LAB
```

**3. Run the installer** (no `sudo` needed):

```bash
./install.sh
```

It installs Python, the FLIR camera library (Aravis), libusb and libgphoto2 with Homebrew, and creates the Python environment `LAB/lab`. macOS needs no USB permission changes. Options: `./install.sh --help`.

**4. Every time you work:**

```bash
cd LAB
source setup.sh
```

**Canon on macOS:** before using the Canon, close Photos and Image Capture and run `killall -9 ptpcamerad`; macOS otherwise takes the camera for itself.

Details: [equipment/packaging/macos/README.md](equipment/packaging/macos/README.md)

---

## Windows

**1. Install the manufacturer software.** The drivers can't be shipped with this code:

| For | Download | Where |
|---|---|---|
| DC2200 | DC2200 software | thorlabs.com → DC2200 → Software |
| PM400 | Optical Power Monitor | thorlabs.com → PM400 → Software |
| FLIR camera | **Spinnaker SDK**, Windows 64-bit | teledynevisionsolutions.com (free account) |
| FLIR camera | **Spinnaker Python** package for Python 3.12 (`cp312`) | same page as the SDK |

- Install the two Thorlabs programs and the Spinnaker SDK. The Thorlabs software also installs **NI-VISA**, which is needed.
- **Don't install the Spinnaker Python package.** Leave the downloaded `.zip` (or `.whl`) in your **Downloads** folder; the installer picks it up there. If it's for another Python version (e.g. `cp311`), the installer uses that version.
- **PM400:** open Thorlabs' **Power Meter Driver Switcher** and select **TLPM (VISA)** for the PM400.

The pE-300 needs nothing extra; Windows has its USB serial driver built in.

**2. Get the code.** On github.com/matijalakner/LAB, use **Code → Download ZIP** and unpack it (e.g. to `Documents\LAB`). Or, with git: `git clone https://github.com/matijalakner/LAB.git`.

**3. Run the installer.** Double-click **`install.bat`** in the `LAB` folder. No administrator rights are needed. It finds or installs Python, creates the environment `LAB\lab`, installs PySpin from Downloads, and puts a **LAB terminal** shortcut on the desktop. If it reports something missing, add it and double-click `install.bat` again.

**4. Every time you work:** double-click **LAB terminal** on the desktop.

Details: [equipment/packaging/windows/README.md](equipment/packaging/windows/README.md)

---

## Check that everything works

In a working terminal (Fedora, Ubuntu, macOS: after `source setup.sh`; Windows: the LAB terminal):

```bash
equipment doctor
```

It checks every instrument's libraries, drivers and permissions on this computer, then lists the connected instruments:

| Label | Meaning |
|---|---|
| `OK` | ready |
| `WARN` | works, but may cause trouble; the `fix:` line says what to do |
| `FAIL` | this instrument can't be used yet; the `fix:` line says how to fix it |
| `--` | not used on this system (e.g. the Canon on Windows) |

It changes nothing and switches nothing on, so you can run it as often as you like. When it says *Everything is ready*, connect the instruments and try:

```bash
equipment devices            # which instruments are connected
equipment pe300 status       # the pE-300's channels
equipment flir live          # live view of the FLIR camera (q to quit)
```

`equipment --help` lists all commands, and the [equipment README](equipment/README.md) explains them. Measurements are saved in `LAB/data/`: photos in `data/input`, logs and results in `data/output`.

## Updating

Get the new code (`git pull` in `LAB`, or download it again), then update the Python environment:

| System | Command |
|---|---|
| Fedora, Ubuntu, macOS | `./install.sh --python-only` |
| Windows | `install.bat -PythonOnly` |

## If something goes wrong

| Problem | Fix |
|---|---|
| `permission denied` for a USB or serial device (Linux) | unplug and replug the instrument; if it persists, log out and back in |
| the DC2200 or PM400 is not found | check the USB cable and that it is on. Windows: check the Thorlabs software and that the PM400 uses TLPM (VISA) |
| `could not open USB0::... (serial ...)` | a unit with another serial number is connected: the message (or `equipment devices`) shows it; use it with `--dc2200-serial` / `--pm400-serial` |
| the FLIR camera is not found | use a USB3 (blue) port. Windows: check that the Spinnaker SDK is installed |
| `flir live` opens no window | Linux with Wayland: `QT_QPA_PLATFORM=xcb equipment flir live` |
| Canon: `could not claim the USB device` | Linux: `./install.sh --mask-gvfs`, then replug. macOS: `killall -9 ptpcamerad` |
| `./install.sh: Permission denied` | the ZIP download lost the executable flag: `bash install.sh` |
| anything else | `equipment doctor` and its `fix:` lines; then the troubleshooting table on your system's page |
