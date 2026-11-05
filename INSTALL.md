# Installing the lab software

This sets up everything to run the lab instruments and analyse the measurements:

- **Thorlabs DC2200** LED driver and **PM400** power meter
- **CoolLED pE-300** light source
- **FLIR Blackfly S** camera
- **Canon EOS R10** camera (Fedora only)

There is one installer for **Fedora** and one for **Windows 10/11**. Pick your system below, follow the steps in order, and finish with the check at the end.

| | Fedora | Windows 10/11 |
|---|---|---|
| DC2200, PM400 | ✓ | ✓ |
| pE-300 | ✓ | ✓ |
| FLIR Blackfly S | ✓ | ✓ |
| Canon EOS R10 | ✓ | ✗ (its USB library exists only for Linux and macOS) |

Allow about 15 minutes on Fedora (most of it compiling the camera library) and about 10 minutes on Windows, plus the manufacturer downloads.

---

## Fedora

### 1. Get the code

Open a terminal and run:

```bash
git clone https://github.com/matijalakner/LAB.git
cd LAB
```

If `git` is missing, install it with `sudo dnf install git`. Or, without git: on the GitHub page, use **Code → Download ZIP**, unpack it, and open a terminal in the unpacked `LAB` folder.

### 2. Run the installer

```bash
./install.sh
```

Run it as your **normal user**, not with `sudo`. It asks for your password when it needs administrator rights. It installs the following:

| What | Why |
|---|---|
| System packages (dnf) | Python, USB and camera libraries, build tools |
| Aravis 0.8.36 | the FLIR camera library (compiled; skipped if already there) |
| `/etc/udev/rules.d/99-lab-equipment.rules` | the instruments can be opened without `sudo` |
| the `dialout` group | access to the pE-300's serial ports |
| 1000 MB USB buffer | full-speed FLIR video, set now and after every reboot |
| the `lab` environment in `LAB` | the `equipment` and `analysis` commands |

Options (`./install.sh --help`):

| Option | Effect |
|---|---|
| `--no-canon` | skip the Canon camera |
| `--no-aravis` | skip the FLIR camera library |
| `--mask-gvfs` | stop the GNOME file manager from grabbing the Canon over USB |

### 3. Log out and reboot once

Log out and back in, so the group and library paths apply everywhere. Reboot once, so the USB buffer setting is permanent.

### 4. Every time you work

```bash
cd LAB
source setup.sh
```

The `equipment` and `analysis` commands are now available in that terminal.

---

## Windows 10/11

### 1. Install the manufacturer software

The instrument drivers can't be shipped with this code. Download and install them yourself:

| For | Download | Where |
|---|---|---|
| DC2200 | DC2200 software | thorlabs.com → DC2200 → Software |
| PM400 | Optical Power Monitor | thorlabs.com → PM400 → Software |
| FLIR camera | **Spinnaker SDK**, Windows 64-bit | teledynevisionsolutions.com (free account) |
| FLIR camera | **Spinnaker Python** package for Python 3.12 (`cp312`) | same page as the SDK |

- Install the two Thorlabs programs and the Spinnaker SDK. The Thorlabs software also installs **NI-VISA**, which is needed.
- **Don't install the Spinnaker Python package.** Leave the downloaded `.zip` (or `.whl`) in your **Downloads** folder; the installer picks it up there.
- If your Spinnaker Python download is for another Python version (e.g. `cp311`), the installer uses that version instead.
- **PM400:** open Thorlabs' **Power Meter Driver Switcher** and select **TLPM (VISA)** for the PM400. Otherwise the software can't see it.

The pE-300 needs no extra software: Windows 10/11 has its USB serial driver built in.

### 2. Get the code

Do one of these:

- On the GitHub page (github.com/matijalakner/LAB), use **Code → Download ZIP** and unpack it, e.g. to `Documents\LAB`;
- or, with git: `git clone https://github.com/matijalakner/LAB.git`.

### 3. Run the installer

Double-click **`install.bat`** in the `LAB` folder. You don't need administrator rights. In order, it:

1. finds Python 3.10–3.12, or installs Python with `winget`;
2. creates the `lab` environment in `LAB` with the `equipment` and `analysis` commands;
3. checks that NI-VISA is installed;
4. installs the Spinnaker Python package from Downloads;
5. puts a **LAB terminal** shortcut on the desktop;
6. runs the check (`equipment doctor`).

If it reports something missing, such as the Spinnaker download, add it and double-click `install.bat` again. Running it again is always safe.

### 4. Every time you work

Double-click **LAB terminal** on the desktop. The `equipment` and `analysis` commands are available in that window.

---

## Check that everything works

In a working terminal (Fedora: after `source setup.sh`; Windows: in the LAB terminal), run:

```bash
equipment doctor
```

It checks every instrument's libraries, drivers and permissions on this computer, then lists the connected instruments. Each line has one of these labels:

| Label | Meaning |
|---|---|
| `OK` | ready |
| `WARN` | works, but may cause trouble; a `fix:` line says what to do |
| `FAIL` | this instrument can't be used yet; the `fix:` line says how to fix it |
| `--` | not used on this system (e.g. the Canon on Windows) |

It changes nothing and switches nothing on, so you can run it as often as you like. Once it says *Everything is ready*, connect the instruments and try:

```bash
equipment devices            # which instruments are connected
equipment pe300 status       # the pE-300's channels
equipment flir live          # live view of the FLIR camera (q to quit)
```

`equipment --help` lists all commands. The measurements are saved in `LAB/data/` (photos in `data/input`, logs and results in `data/output`). The [equipment README](equipment/README.md) explains every command.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `permission denied` for `/dev/ttyACM0` (Fedora) | unplug and replug the pE-300. If that doesn't help, log out and back in |
| the DC2200 or PM400 is not found | check the USB cable and that the instrument is on. On Windows, check that the Thorlabs software is installed and the PM400 uses TLPM (VISA) |
| `could not open USB0::... (serial ...)` for a Thorlabs instrument | a unit with another serial number is connected: the message (or `equipment devices`) shows it; use it with `--dc2200-serial` / `--pm400-serial` |
| the FLIR camera is not found | use a USB3 (blue) port; on Windows, check that the Spinnaker SDK is installed |
| `flir live` opens no window | `pip install opencv-python` in the environment. On Fedora Wayland, try `QT_QPA_PLATFORM=xcb equipment flir live` |
| Canon: `could not claim the USB device` (Fedora) | `./install.sh --mask-gvfs`, then unplug and replug the camera |
| anything else | run `equipment doctor` and follow its `fix:` lines |
