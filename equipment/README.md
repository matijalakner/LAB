# equipment

Drivers and terminal control for the lab equipment:

| Instrument | Command | Python |
|---|---|---|
| Thorlabs **DC2200** LED driver (A) | `equipment dc2200 set / off / ramp` | `equipment.thorlabs.dc2200` |
| CoolLED **pE-300** white/ultra (%) | `equipment pe300 set / off / status / ramp` | `equipment.coolled.pe300` |
| Thorlabs **PM400** power meter | `equipment pm400 measure` | `equipment.thorlabs.pm400` |
| **Canon EOS R10** (USB, libgphoto2) | `equipment canon info / photo / timelapse / video` | `equipment.canon` |
| **FLIR Blackfly S** BFS-U3-27S5C-C (USB3 Vision) | `equipment flir list / info / live / photo / timelapse / video` | `equipment.flir` |
| Any light source + photos and/or power | `equipment <dc2200\|pe300> ramp ... --photos NAME --power` | `equipment.experiments.paired_ramp` |
| Any light source + PM400 (LIV curve) | `equipment liv --source <dc2200\|pe300>` | `equipment.experiments.liv` |
| What is connected | `equipment devices` | `equipment.devices` |

**Pairing.** Both light sources are behind one interface (`equipment.sources`), so any of them can be combined with any measurement:

| | Canon photos | FLIR photos | PM400 power |
|---|---|---|---|
| **DC2200** | `dc2200 ramp ... --photos NAME` | `... --photos NAME --camera flir` | `dc2200 ramp ... --power`, `liv --source dc2200` |
| **pE-300** | `pe300 ramp ... --photos NAME` | `... --photos NAME --camera flir` | `pe300 ramp ... --power`, `liv --source pe300` |

`--photos` and `--power` can be used together, for example pE-300 + FLIR + PM400 in one run.

The code was split out of [LineTracker](https://github.com/matijalakner/LineTracker) (its `src/Canon`, `src/FLIR`, `src/ThorLabs`). The file layout and CSV formats are unchanged. The photos and logs written here are analysed by [line-analysis](../line-analysis), the other module of this LAB repository.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
  - [pE-300](#coolled-pe-300) · [Pairing](#pairing-photos-and-power-during-a-ramp)
- [Where the data goes](#where-the-data-goes)
- [Instrument setup](#instrument-setup)
- [Python API](#python-api)
- [Project structure](#project-structure)
- [Tests](#tests)

---

## Installation

There is one installer per system. Each installs everything every instrument needs, then runs `equipment doctor` to check the result. Both can be run again at any time.

| | Fedora | Windows 10/11 |
|---|---|---|
| Run | `./install.sh` in `LAB` | `install.bat` in `LAB` (double-click) |
| Script | `equipment/packaging/fedora/install.sh` | `equipment/packaging/windows/install.ps1` |
| Then | `source LAB/setup.sh` in each new terminal | the **LAB terminal** shortcut on the desktop |
| DC2200, PM400 | ✓ (pyvisa-py over libusb, udev rule) | ✓ (NI-VISA from the Thorlabs software) |
| pE-300 | ✓ (`/dev/ttyACM*`, udev rule) | ✓ (`COM` port, built-in driver) |
| FLIR Blackfly S | ✓ (Aravis 0.8, built by the installer) | ✓ (Spinnaker SDK + PySpin) |
| Canon EOS R10 | ✓ (libgphoto2) | ✗ (libgphoto2 is Linux/macOS only) |

### Fedora

```bash
git clone https://github.com/matijalakner/LAB.git
cd LAB
./install.sh                 # options: --no-canon, --no-aravis, --mask-gvfs, --help
source setup.sh              # in every new terminal
```

Run it as your normal user, not with `sudo`; it asks for your password when it needs root. It does the following:

1. installs the system packages with dnf (Python, libusb, libgphoto2, the build tools);
2. builds Aravis 0.8.36 into `/usr/local` for the FLIR camera, if Aravis 0.8 isn't there yet;
3. installs `99-lab-equipment.rules` in `/etc/udev/rules.d/`, so the DC2200, PM400, pE-300 and FLIR open without `sudo`;
4. adds you to `dialout` and sets the 1000 MB USB buffer the camera needs (now, and after every reboot);
5. creates the environment `LAB/lab` (with `--system-site-packages`, for Aravis) and installs `equipment` and `line-analysis` in it.

Log out and back in once, and reboot once, when it's done.

### Windows

1. Install the manufacturer software first. These bring the drivers, which aren't allowed to be redistributed:
   - **Thorlabs DC2200** software and **Optical Power Monitor** (PM400) from thorlabs.com. They install NI-VISA, which `equipment` uses for both instruments. In Thorlabs' *Power Meter Driver Switcher*, the PM400 must use the **TLPM (VISA)** driver.
   - **Spinnaker SDK** (Windows, 64-bit) from teledynevisionsolutions.com (free account). Also download the **Spinnaker Python** package for your Python version (e.g. cp312) and leave the `.zip` or `.whl` in Downloads.
2. Get `LAB` (`git clone https://github.com/matijalakner/LAB.git`, or *Download ZIP* on GitHub and unpack it), then double-click **`install.bat`** in `LAB`.

The installer does the following:

1. finds Python 3.10–3.12, the versions PySpin exists for (the Spinnaker wheel decides which), or installs it with `winget`;
2. creates `LAB\lab` with `equipment` and `line-analysis`;
3. checks NI-VISA;
4. installs PySpin from the wheel in Downloads;
5. makes `LAB\lab-terminal.cmd` and a **LAB terminal** shortcut on the desktop;
6. runs `equipment doctor`.

It needs no administrator rights. If something was missing (e.g. the Spinnaker wheel), add it and run `install.bat` again. Options: `install.bat -Python 3.11`, `install.bat -SpinnakerWheel C:\path\spinnaker_python-...whl`.

### Checking: `equipment doctor`

`equipment doctor` checks every library, driver and permission the instruments need on this computer and lists the connected instruments. Each line is `OK`, `WARN` (works, but may cause trouble), `FAIL` (that instrument cannot be used yet) or `--` (not used on this system). Every `WARN` and `FAIL` line comes with the fix. It changes nothing and switches nothing on.

### By hand

Requires Python 3.10 or newer. The core and the CLI need only the standard library; install the extra for each instrument you use:

```bash
pip install -e ".[thorlabs]"        # DC2200, PM400, LIV:  pyvisa, pyvisa-py (+ pyusb on Linux)
pip install -e ".[coolled]"         # pE-300:              pyserial
pip install -e ".[canon]"           # Canon:               python-gphoto2 (Linux/macOS)
pip install -e ".[flir]"            # FLIR:                numpy, opencv-python, pillow
pip install -e ".[all]"             # everything above
```

The FLIR camera also needs Spinnaker + PySpin, or Aravis. Neither comes from PyPI; see [FLIR setup](#flir-blackfly-s). Every hardware library is loaded only when its instrument is used, so `equipment --help` and every installed instrument work even if the others are missing. `python -m equipment ...` works the same as `equipment ...`.

---

## Quick start

```bash
equipment devices                                   # what is connected?

equipment dc2200 set 0.25                           # 250 mA, LED stays on
equipment dc2200 off

# 0 -> 0.5 A in 0.05 A steps, every step held 2 s, and back down
equipment dc2200 ramp --min 0 --max 0.5 --step 0.05 --step-time 2

# the same ramp with a Canon photo in the middle of every step
equipment dc2200 ramp --min 0 --max 0.5 --step 0.05 --step-time 2 \
    --photos mysample --shutter 1/250 --iso 100 --wb Daylight --sync-clock

# ... or with the FLIR camera
equipment dc2200 ramp --min 0 --max 0.5 --step 0.05 --step-time 2 \
    --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off

equipment pe300 status                              # channels, intensities, firmware
equipment pe300 set 30                              # white (A+B+C) at 30 %, stays on
equipment pe300 set 50 --channels B                 # blue only
equipment pe300 off
equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 2
equipment pe300 ramp --channels B --hold C=1 --min 0 --max 100 --step 1 --step-time 5   # blue ramp, green at 1 %

# pairings
equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 5 --power --wavelength 470
equipment pe300 ramp --min 0 --max 100 --step 10 --step-time 10 \
    --photos mysample --camera flir --shutter 1/250 --gain 0 --wb off --power
equipment liv --source pe300 --max 100 --channels B --ramp-duration 20

equipment pm400 measure --wavelength 450 --duration 5 --rate 10
equipment liv --max 0.05 --ramp-duration 10

equipment canon photo sample-1 --shutter 1/250 --iso 200
equipment flir timelapse sample-1 -n 5 --duration 1200 --save-format png
```

`--debug` (before the instrument name, `equipment --debug dc2200 ramp ...`) prints the full traceback instead of the one-line error.

---

## Command reference

Every command has its own help: `equipment dc2200 ramp -h`, `equipment flir photo -h`, …

### `equipment devices`

This command lists the Thorlabs USB devices with their serial numbers, the pE-300 serial port, the cameras gphoto2 sees, and the FLIR/GenICam cameras. It also prints the VISA resources and the pE-300 port the commands will use. A missing library is reported for its group only, so the other groups are still listed.

### DC2200 LED driver

Currents are in **amperes** (0 – 2 A). Check your LED head's rating first. The CLI refuses values above 2 A before it touches the device.

| Command | What it does |
|---|---|
| `dc2200 set CURRENT` | Constant current. **The LED stays on.** The user current limit is set to the same value. `set 0` switches the output off. |
| `dc2200 off` | Switches the output off. |
| `dc2200 ramp --min A --max A --step A --step-time S [--cycles N]` | Steps min → max → min. The LED is switched off at the end, on any error and on Ctrl+C. Can be [paired](#pairing-photos-and-power-during-a-ramp). |

All DC2200 commands take `--dc2200-serial SN`.

### CoolLED pE-300

Levels are **intensities in %** (0 – 100, whole percent) of the chosen channels. The pE-300white has three channels: A (violet/UV), B (blue) and C (green to red). All three together give white light.

| Command | What it does |
|---|---|
| `pe300 set INTENSITY [--channels ABC]` | Lights the channels at that intensity and **leaves the light on**. The other channels are switched off. `set 0` switches the light off. |
| `pe300 off` | Switches all channels off. Selection and intensities are kept. |
| `pe300 status` | Shows the port, firmware, wavelengths, and the state and intensity of every channel. |
| `pe300 ramp --min % --max % --step % --step-time S [--cycles N] [--channels ABC]` | The same stepped ramp as for the DC2200. Can be [paired](#pairing-photos-and-power-during-a-ramp). |

Every pE-300 command takes:

- `--port` (e.g. `/dev/ttyACM0`, `COM3`). The default is `$EQUIPMENT_PE300_PORT`, otherwise the port is found automatically.
- `--channels`: any of `A`, `B`, `C`. The default is `ABC`.
- `--hold CH=PCT` (`set`, `ramp`, `liv`): keeps other channels on at a fixed intensity while the light is on, for example `--channels B --hold C=1` ramps blue with green held at 1 %. Several values: `--hold A=5,C=1`. Held channels switch off with the light.

Every setting is read back from the unit and checked. If the Control Pod changes something at the same time, you get an error instead of wrong data.

### How a ramp steps (both sources)

With `--min 0 --max 0.5 --step 0.1 --step-time 2` the level goes 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0. Every value is held for 2 s, 22 s in total. With `--min 0 --max 0.5 --step 0.1 --step-time 2` the current goes 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0 A. Every value is held for 2 s, 22 s in total.

- The maximum is not repeated.
- `--final-hold S` keeps the light at the last level (back at `--min`) for `S` seconds longer before switching it off. Photos and power readings continue on the same schedule. In the logs the hold counts as part of the last step (same step number, `direction` `down`), so `analysis report` reads it as before.
- If `max − min` is not a multiple of `step`, the last step up is shorter, so the ramp always reaches exactly `--max`.
- The steps are timed from a clock, so they do not drift.

### Pairing: photos and power during a ramp

`dc2200 ramp` and `pe300 ramp` take the same pairing options. Photos come from the Canon or the FLIR camera with `--photos NAME`. Power readings come from the PM400 with `--power`. You can use both together.

These options go with `--photos NAME`:

| Option | Meaning |
|---|---|
| `--photos NAME` | Take photos, saved as `<data>/input/folder/NAME/NAME_XXXX.jpg` (numbering continues) |
| `--camera canon\|flir` | Which camera (default `canon`) |
| `--photo-delay S` | One photo per step, `S` s after the step starts (default: half the step time) |
| `--photo-interval S` | Instead: a photo every `S` s from the ramp start |
| `--shutter`, `--wb` | For both cameras |
| `--iso --color-temp --picture-style --image-format --sync-clock --keep-on-card` | Canon only |
| `--gain --wb-red --wb-blue --gamma --black-level --pixel-format --save-format --quality --defaults --serial --backend` | FLIR only |

These options go with `--power`:

| Option | Meaning |
|---|---|
| `--power` | Read the optical power with the PM400 |
| `--power-delay S` | One reading per step, `S` s after the step starts (default: half the step time) |
| `--power-interval S` | Instead: a reading every `S` s from the ramp start |
| `--wavelength NM`, `--averaging-count N`, `--pm400-serial SN` | PM400 settings (defaults 450 nm, 10) |

How the light and the paired instruments work together:

- The camera and the PM400 are connected first. If one of them is not found, the light is never switched on.
- Each runs in its own thread, so a slow capture never delays a step.
- If one of them fails, the ramp stops and the light is switched off.
- Ctrl+C stops everything. Data taken so far is kept.
- Logs are written next to the ramp CSV: `<ramp>_photos.csv` and `<ramp>_power.csv`. They use the same t = 0 and time stamp line as the ramp CSV. Their last column is the level that was set at each measurement (`current_A` or `intensity_pct`), so no device clock is needed to match them.
- The CLI refuses camera options without `--photos`, PM400 options without `--power`, and options that belong to the other camera.

### PM400 power meter

`equipment pm400 measure` (or `equipment pm measure`) takes these options:

| Option | Default |
|---|---|
| `--wavelength NM` | 450 |
| `--averaging-count N` | 10 |
| `--duration S` (`--sample-duration`) | 5 |
| `--rate HZ` (`--sample-rate`) | 10 |
| `--pm400-serial SN` | see [Thorlabs setup](#thorlabs-dc2200--pm400) |

### LIV (any light source + PM400)

`equipment liv` ramps a light source linearly up and down and reads the power at every point. Use `--source dc2200` (the default; levels in A) or `--source pe300` (levels in %, with `--channels` and `--port`).

| Option | Default |
|---|---|
| `--source` | `dc2200` |
| `--min LEVEL` | 0 |
| `--max LEVEL` | 0.05 A (DC2200), 100 % (pE-300) |
| `--ramp-duration S` | 10 |
| `--update-rate HZ` | 10 |
| `--cycles N` | 1 |
| `--wavelength NM` | 450 |
| `--averaging-count N` | 10 |
| `--settle-time S` | automatic; must be shorter than `1 / update-rate` |
| `--dc2200-serial`, `--pm400-serial` | |

### Canon EOS R10

| Command | What it does |
|---|---|
| `canon info [--sync-clock]` | Current settings and every value the camera accepts. |
| `canon photo NAME [-i]` | One photo. With `-i`, Enter takes a photo and `q` + Enter quits. |
| `canon timelapse NAME -n S [--count N \| --duration S]` | A photo every `S` s (clock based). Without `--count` or `--duration` it runs until Ctrl+C. |
| `canon video NAME [--duration S] [--delete-from-card]` | Records on the card (switch on movie), then downloads. Without `--duration` it stops on Enter. |

Settings are all optional; any you leave out keep the value set on the camera. Each value is checked against the camera's own list, so `1/250`, `0.004` and `1/250s` all work.

| Option | Example |
|---|---|
| `--shutter` | `1/250`, `0.5`, `2` (mode dial on M or Tv) |
| `--iso` | `100`, `Auto` |
| `--wb` | `Daylight`, `Tungsten`, `Auto` (a unique part of the name is enough) |
| `--color-temp` | `5200` |
| `--picture-style` | `Neutral` |
| `--image-format` | `"Large Fine JPEG"` |
| `--sync-clock` | Sets the camera clock to the computer clock |
| `--keep-on-card` | Also keeps the photos on the card (by default they are captured to RAM) |

### FLIR Blackfly S

| Command | What it does |
|---|---|
| `flir list [--backend]` | Connected cameras with serial numbers. |
| `flir info [--serial] [--backend]` | Current settings with their allowed values or ranges. |
| `flir live [NAME]` | Live view in a window, showing frame rate, exposure, gain and % saturated pixels. Keys: `+`/`-` exposure, `]`/`[` gain, `o` marks saturated pixels red, `c` crosshair, `s` saves a full-resolution snapshot to `<data>/input/folder/NAME/`, `q` quits. On exit it prints the `--shutter`/`--gain` values to reuse in other commands. |
| `flir photo NAME [-i]` | One photo, software-triggered (a fresh exposure). |
| `flir timelapse NAME -n S [--count N \| --duration S]` | A photo every `S` s. |
| `flir video NAME [--duration S] [--fps F] [--codec mp4v]` | Records the stream to `.mp4` on the computer. A `_frames.csv` file holds the real time of every frame. |

Settings are all optional:

| Option | Example |
|---|---|
| `--shutter` / `--exposure` | `1/250`, `0.004`, `4ms`, `250us`, `auto` (a plain number is seconds) |
| `--gain` | `0`, `6.5`, `auto` (dB) |
| `--wb` | `off`, `once`, `auto` |
| `--wb-red`, `--wb-blue` | `1.4`, `2.0` |
| `--gamma` | `1.0`, `off` |
| `--black-level` | `1.5` (%) |
| `--pixel-format` | `BGR8` (default), `BayerRG8`, `BayerRG16`, `Mono8`, `Mono16` |
| `--save-format` | `jpg` (default), `png`, `tiff` |
| `--quality` | `95` |
| `--defaults` | Loads the factory defaults first |
| `--serial`, `--backend` | `auto` (Spinnaker if installed, else Aravis), `spinnaker`, `aravis` |

For measurements, fix the exposure, gain and white balance (`--shutter 1/250 --gain 0 --wb off`). With `auto` the brightness is not comparable between photos.

---

## Where the data goes

Photos and videos go to `<data>/input`, logs and measurements to `<data>/output`. `<data>` is the first of:

1. `--data-dir DIR` (before the instrument name: `equipment --data-dir DIR pe300 ...`), or the environment variable `EQUIPMENT_DATA`, or `LINE_ANALYSIS_DATA` (the one `analysis` uses, so one setting serves both);
2. `LAB/data`, the `data` folder next to this package's folder, when installed with `pip install -e` from `LAB/equipment`;
3. `./data` in the folder you run the command from.

These are the same rules `analysis` uses, so both always find the same folder, wherever you run them from. `equipment devices` prints the folder in use. `--input-dir` and `--output-dir` still override it for one run.

| Command | File |
|---|---|
| `dc2200 ramp`, `pe300 ramp` | `<data>/output/ramp/ramp_<UTC>.csv`; with `--photos` also `ramp_<UTC>_photos.csv` and `<data>/input/folder/<name>/`; with `--power` also `ramp_<UTC>_power.csv` |
| `pm400 measure` | `<data>/output/pm/pm_<UTC>.csv` |
| `liv` | `<data>/output/liv/liv_<UTC>.csv` |
| `canon ...` | `<data>/input/folder/<name>/<name>_XXXX.jpg`/`.mp4`, log `<data>/output/camera/camera_<UTC>.csv` |
| `flir ...` | `<data>/input/folder/<name>/<name>_XXXX.jpg`/`.png`/`.tif`/`.mp4`, log `<data>/output/camera/flir_<UTC>.csv` |

`--output-csv NAME` changes the file name. A plain name goes into the command's folder (`--output-csv run1.csv` → `<data>/output/ramp/run1.csv`); a name that contains a folder is used as given. CSVs are written also when a run is interrupted.

The ramp, pm and camera CSVs start with a line `time_stamp,<UTC time at t = 0>`, then the header:

| File | Columns |
|---|---|
| ramp | `time_s, cycle, direction, LEVEL` |
| ramp photos | `time_s, index, file, utc, step, cycle, direction, LEVEL` |
| ramp power | `time_s, power_W, utc, step, cycle, direction, LEVEL` |
| pm | `time_s, power_W` |
| liv | `time_s, cycle, direction, LEVEL, power_W` (no time stamp line) |
| camera / flir | `time_s, index, file, utc` |

`LEVEL` is `current_A` for the DC2200 (the same as before) and `intensity_pct` for the pE-300. [line-analysis](../line-analysis) reads both.

Numbering of `<name>_XXXX` continues after the files already in the folder, so nothing is overwritten.

---

## Instrument setup

### Thorlabs DC2200 / PM400

1. Set the serial numbers using the first option that suits you:
   - per command with `--dc2200-serial` / `--pm400-serial`;
   - with the environment variables `EQUIPMENT_DC2200_SERIAL` / `EQUIPMENT_PM400_SERIAL`;
   - by changing the defaults in `src/equipment/thorlabs/common.py`.

   `equipment devices` shows the connected serials and the configured resources.
2. How they are reached:
   - **Fedora**: through `pyvisa-py` over libusb. The Linux kernel driver is detached while an instrument is open and attached again afterwards. This needs `pyusb` and USB permissions; the installer's udev rule for vendor `1313` gives them.
   - **Windows**: through the VISA library the Thorlabs software installs (NI-VISA). If the resource name differs (hex vs decimal IDs), the instrument is found by its serial number.
   - `EQUIPMENT_VISA=@py` (or `@ivi`, or a VISA library path) overrides the choice.
3. Both instruments are driven directly over SCPI.
   - **DC2200**: a built-in driver (`SOURce1:MODe CC`, `SOURce1:CURRent:LIMit:AMPLitude`, `SOURce1:CCURrent:CURRent`, `OUTPut1:STATe`). Every setting is read back and the instrument's error queue is checked, so a refused command stops the run before the LED is switched on. On Linux, the lab's `measurement_control` package is used instead when it is installed (`EQUIPMENT_DC2200_DRIVER=auto|builtin|measurement_control`).
   - **PM400**: a built-in driver as well.

### CoolLED pE-300

1. Install pyserial with `pip install -e ".[coolled]"`. The pE-300 is a USB virtual serial port (57600 baud):
   - Linux: the unit shows up as two ports, `/dev/ttyACM0` and `/dev/ttyACM1` ("pE300 - USB Virtual Serial Port A/B", USB ID `0483:A080`). Both accept commands, and the program uses the first. To give your user access, either:
     - install a udev rule, which works without logging out and survives replugging:
       ```bash
       echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="a080", MODE="0666"' \
           | sudo tee /etc/udev/rules.d/99-coolled-pe300.rules
       sudo udevadm control --reload-rules && sudo udevadm trigger
       ```
     - or join the `dialout` group with `sudo usermod -aG dialout $USER`, then log out and back in.
   - Windows: one or two `COM` ports. Windows 10/11 has the USB serial driver built in (older Windows: `CoolLEDpE.inf` from coolled.com).
2. The port is found automatically when it identifies as CoolLED. Otherwise every USB serial port is asked `CSS?`. Fix it with `--port` or `EQUIPMENT_PE300_PORT=/dev/ttyACM0` if other serial devices are connected.
3. Check with `equipment pe300 status`.
4. Don't use the Control Pod during a run. Every setting is verified, so a change from the pod stops the run with an error.

### Canon EOS R10

Fedora only: libgphoto2, which controls the camera over USB, does not exist for Windows.

1. The Fedora installer installs libgphoto2 and python-gphoto2. By hand: `pip install -e ".[canon]"`, or `sudo dnf install libgphoto2 gphoto2 python3-gphoto2`. Check the connection with `gphoto2 --auto-detect`.
2. Turn the camera on and connect a USB data cable. Turn **Wi-Fi and Bluetooth off** (while they are connected the R10 disables USB control) and disable auto power off.
3. For video, put the photo/movie switch on movie and insert a card.
4. On GNOME the file manager claims the camera. If you get "could not claim the USB device", run `gio mount -s gphoto2; pkill -f gvfs-gphoto2-volume-monitor`. For a permanent fix, use `./install.sh --mask-gvfs`.

### FLIR Blackfly S

The camera needs one of these two libraries (neither is on PyPI).

**Spinnaker + PySpin** (Teledyne's SDK; the one to use on **Windows**):

1. Install the Spinnaker SDK from teledynevisionsolutions.com. It also installs the camera's USB3 driver.
2. Install the matching wheel. The Windows installer does this from Downloads; by hand: `pip install spinnaker_python-<version>-cp3XX-...whl`.

**Aravis** (open source; the one to use on **Fedora**):

1. The Fedora installer builds Aravis 0.8.36 into `/usr/local` and registers it (`/etc/ld.so.conf.d/lab-aravis.conf`, `/etc/profile.d/lab-aravis.sh`; `LAB/setup.sh` sets `GI_TYPELIB_PATH` as well).
2. The environment must be created with `--system-site-packages`, as the installer does.
3. The installer's udev rule (vendor `1e10`) lets you open the camera without `sudo`.

With either library:

- Use a USB3 port (the blue one).
- For full-speed video on Linux, the USB buffer must be 1000 MB. The Fedora installer sets it, also for every boot. By hand: `echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb`.
- Check that the camera is found with `equipment flir list`.

---

## Python API

```python
from equipment import main_ramp, main_source_ramp, main_paired_ramp, main_pe300_set
from equipment.utils import output_csv_path        # output_csv_path(None, ...) -> <data>/output/...

rows = main_ramp({"i_min": 0, "i_max": 0.5, "step": 0.05, "step_time": 2,      # DC2200
                  "output_csv": output_csv_path(None, "ramp", "run1.csv")})

main_pe300_set({"intensity": 30, "channels": "ABC"})                           # stays on

rows = main_source_ramp({"source": "pe300", "channels": "B", "min": 0, "max": 100,
                         "step": 10, "step_time": 2})

# any source + any measurements: pE-300 + FLIR + PM400
out = main_paired_ramp({"source": "pe300", "min": 0, "max": 100, "step": 10,
                        "step_time": 10,
                        "camera": "mysample", "camera_type": "flir",
                        "shutter": "1/250", "gain": 0, "whitebalance": "off",
                        "power": True, "wavelength": 470,
                        "output_csv": output_csv_path(None, "ramp", "run2.csv")})
# out = {"rows": ramp rows, "photos": [files], "power": [power rows]}
# photos go to <data>/input/folder/mysample/ unless "input_dir" is given
```

Light sources can also be used directly. Each one is a context manager, and the light is switched off when you leave the block:

```python
from equipment import make_source, run_ramp

with make_source("pe300", {"channels": "AC"}) as light:      # or "dc2200"
    light.set_level(20)
    light.switch_on()
    ...
```

Every `main_*` function takes a dict, or an object with the same attributes. The lower-level classes are `PE300`, `CanonCamera`, `FlirCamera`, `PM400` and `ThorlabsUSBDriver`.

**Adding another light source.** Subclass `LightSource` in `sources.py` and set `key`, `name`, `unit`, `column` and `max_level`. Implement `open`, `close`, `set_level`, `switch_on` and `switch_off`, plus `from_cfg`. Then add the class to `SOURCES`. The ramp, the pairings and LIV then work with it. In the CLI, add a `SOURCE_INFO` entry and call `add_ramp_command`. Names are imported lazily, so `import equipment` loads no hardware library. The scripts in `examples/` show every instrument.

## Project structure

```text
equipment/
├── pyproject.toml                    extras: thorlabs, coolled, canon, flir, all, test
├── examples/                         01_dc2200_ramp ... 07_pe300, 08_pairings
├── tests/                            parser, logic, and full runs with fake instruments
└── src/equipment/
    ├── __init__.py                   lazy public API
    ├── __main__.py                   python -m equipment
    ├── cli.py                        the `equipment` command
    ├── devices.py                    `equipment devices`
    ├── doctor.py                     `equipment doctor`: is this computer ready
    ├── paths.py                      where <data>/input and <data>/output are (LAB/data)
    ├── utils.py                      UTC time stamps, CSV writing, output paths, value matching
    ├── capture.py                    shared by both cameras: file numbering, capture log
    ├── sources.py                    LightSource interface + registry (dc2200, pe300)
    ├── ramp.py                       stepped ramp of any light source
    ├── thorlabs/
    │   ├── common.py                 USB IDs, serial numbers / VISA resources
    │   ├── usb_driver.py             kernel-driver detach (pyusb, Linux)
    │   ├── visa.py                   opening an instrument: pyvisa-py (Linux) / NI-VISA (Windows)
    │   ├── dc2200.py                 built-in SCPI driver, DC2200Source, constant current
    │   ├── pm400.py                  PM400 SCPI driver, open_pm400, power logging
    │   └── liv.py                    (old import path of experiments/liv.py)
    ├── coolled/
    │   └── pe300.py                  PE300 serial driver, PE300Source, set/off/status
    ├── canon/
    │   ├── camera.py                 CanonCamera (gphoto2)
    │   └── capture.py                photo, time-lapse, video
    ├── flir/
    │   ├── backends.py               Spinnaker/PySpin and Aravis
    │   ├── camera.py                 FlirCamera: settings, triggered photos, EXIF time
    │   └── capture.py                photo, time-lapse, video
    └── experiments/
        ├── paired_ramp.py            any source + photos (Canon/FLIR) and/or power (PM400)
        ├── liv.py                    any source + PM400, linear ramp
        └── ramp_camera.py            (old API: ramp with photos)
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

The tests need no instrument. They check the command parser and the ramp, numbering and parsing logic. They also run the ramps, the pairings (pE-300 with PM400, with FLIR, with both, and DC2200 with Canon) and LIV end to end through the CLI. These runs use fake instruments, including a pE-300 emulator that follows CoolLED's protocol. They also check that the light goes off when anything fails.
