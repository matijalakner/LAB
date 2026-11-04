# equipment

Drivers and terminal control for the lab equipment:

| Instrument | Command | Python |
|---|---|---|
| Thorlabs **DC2200** LED driver (A) | `equipment dc2200 set / off / ramp` | `equipment.thorlabs.dc2200` |
| CoolLED **pE-300** white/ultra (%) | `equipment pe300 set / off / status / ramp` | `equipment.coolled.pe300` |
| Thorlabs **PM400** power meter | `equipment pm400 measure` | `equipment.thorlabs.pm400` |
| **Canon EOS R10** (USB, libgphoto2) | `equipment canon info / photo / timelapse / video` | `equipment.canon` |
| **FLIR Blackfly S** BFS-U3-27S5C-C (USB3 Vision) | `equipment flir list / info / photo / timelapse / video` | `equipment.flir` |
| Any light source + photos and/or power | `equipment <dc2200\|pe300> ramp ... --photos NAME --power` | `equipment.experiments.paired_ramp` |
| Any light source + PM400 (LIV curve) | `equipment liv --source <dc2200\|pe300>` | `equipment.experiments.liv` |
| What is connected | `equipment devices` | `equipment.devices` |

**Pairing.** Both light sources are behind one interface (`equipment.sources`), so any of them can be combined with any measurement:

| | Canon photos | FLIR photos | PM400 power |
|---|---|---|---|
| **DC2200** | `dc2200 ramp ... --photos NAME` | `... --photos NAME --camera flir` | `dc2200 ramp ... --power`, `liv --source dc2200` |
| **pE-300** | `pe300 ramp ... --photos NAME` | `... --photos NAME --camera flir` | `pe300 ramp ... --power`, `liv --source pe300` |

`--photos` and `--power` can be used together, for example pE-300 + FLIR + PM400 in one run.

The code was split out of [LineTracker](https://github.com/matijalakner/LineTracker) (its `src/Canon`, `src/FLIR`, `src/ThorLabs`). The file layout and CSV formats are unchanged, so LineTracker's `measurement analysis folder` and `analysis report` read the photos and ramp logs written here as they are.

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

Requires Python 3.10 or newer. The core and the CLI need only the standard library. You install the extra for each instrument you use:

```bash
git clone https://github.com/matijalakner/equipment.git
cd equipment
python3 -m venv --system-site-packages equip   # system site packages: needed for Aravis (FLIR)
source equip/bin/activate
pip install -e ".[thorlabs]"        # DC2200, PM400, LIV:  pyusb, pyvisa, pyvisa-py
pip install -e ".[coolled]"         # pE-300:              pyserial
pip install -e ".[canon]"           # Canon:               python-gphoto2 (needs libgphoto2)
pip install -e ".[flir]"            # FLIR:                numpy, opencv-python, pillow
pip install -e ".[all]"             # everything above
equipment --help
```

Two things cannot come from PyPI:

- The **DC2200** driver comes from the separate `measurement_control` package. Install it into the same environment.
- The **FLIR** camera also needs Spinnaker + PySpin, or Aravis. See [FLIR setup](#flir-blackfly-s).

Every hardware library is loaded only when its instrument is used. `equipment --help` and every instrument you have installed work even if the others are missing; the missing ones give a clear error.

`python -m equipment ...` works the same as `equipment ...`.

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

Every setting is read back from the unit and checked. If the Control Pod changes something at the same time, you get an error instead of wrong data.

### How a ramp steps (both sources)

With `--min 0 --max 0.5 --step 0.1 --step-time 2` the level goes 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0. Every value is held for 2 s, 22 s in total. With `--min 0 --max 0.5 --step 0.1 --step-time 2` the current goes 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0 A. Every value is held for 2 s, 22 s in total.

- The maximum is not repeated.
- If `max − min` is not a multiple of `step`, the last step up is shorter, so the ramp always reaches exactly `--max`.
- The steps are timed from a clock, so they do not drift.

### Pairing: photos and power during a ramp

`dc2200 ramp` and `pe300 ramp` take the same pairing options. Photos come from the Canon or the FLIR camera with `--photos NAME`. Power readings come from the PM400 with `--power`. You can use both together.

These options go with `--photos NAME`:

| Option | Meaning |
|---|---|
| `--photos NAME` | Take photos, saved as `input/folder/NAME/NAME_XXXX.jpg` (numbering continues) |
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

`--output-dir` (default `output`) holds the logs; `--input-dir` (default `input`) holds the photos and videos.

| Command | File |
|---|---|
| `dc2200 ramp`, `pe300 ramp` | `output/ramp/ramp_<UTC>.csv`; with `--photos` also `ramp_<UTC>_photos.csv` and `input/folder/<name>/`; with `--power` also `ramp_<UTC>_power.csv` |
| `pm400 measure` | `output/pm/pm_<UTC>.csv` |
| `liv` | `output/liv/liv_<UTC>.csv` |
| `canon ...` | `input/folder/<name>/<name>_XXXX.jpg`/`.mp4`, log `output/camera/camera_<UTC>.csv` |
| `flir ...` | `input/folder/<name>/<name>_XXXX.jpg`/`.png`/`.tif`/`.mp4`, log `output/camera/flir_<UTC>.csv` |

`--output-csv NAME` changes the file name. A plain name goes into the command's folder (`--output-csv run1.csv` → `output/ramp/run1.csv`); a name that contains a folder is used as given. CSVs are written also when a run is interrupted.

The ramp, pm and camera CSVs start with a line `time_stamp,<UTC time at t = 0>`, then the header:

| File | Columns |
|---|---|
| ramp | `time_s, cycle, direction, LEVEL` |
| ramp photos | `time_s, index, file, utc, step, cycle, direction, LEVEL` |
| ramp power | `time_s, power_W, utc, step, cycle, direction, LEVEL` |
| pm | `time_s, power_W` |
| liv | `time_s, cycle, direction, LEVEL, power_W` (no time stamp line) |
| camera / flir | `time_s, index, file, utc` |

`LEVEL` is `current_A` for the DC2200 (the same as before) and `intensity_pct` for the pE-300. LineTracker's `analysis report` expects `current_A`, so for a pE-300 ramp you have to adapt it.

Numbering of `<name>_XXXX` continues after the files already in the folder, so nothing is overwritten.

---

## Instrument setup

### Thorlabs DC2200 / PM400

1. Set the serial numbers using the first option that suits you:
   - per command with `--dc2200-serial` / `--pm400-serial`;
   - with the environment variables `EQUIPMENT_DC2200_SERIAL` / `EQUIPMENT_PM400_SERIAL`;
   - by changing the defaults in `src/equipment/thorlabs/common.py`.

   `equipment devices` shows the connected serials and the configured resources.
2. The modules detach the Linux kernel driver while they run and re-attach it afterwards. This needs `pyusb` and USB permissions: a udev rule for vendor `1313`, or `sudo`.
3. The DC2200 needs the `measurement_control` package. The PM400 is driven directly over SCPI with `pyvisa-py`.

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
   - Windows: a `COM` port. Windows needs `CoolLEDpE.inf` from coolled.com.
2. The port is found automatically when it identifies as CoolLED. Otherwise every USB serial port is asked `CSS?`. Fix it with `--port` or `EQUIPMENT_PE300_PORT=/dev/ttyACM0` if other serial devices are connected.
3. Check with `equipment pe300 status`.
4. Don't use the Control Pod during a run. Every setting is verified, so a change from the pod stops the run with an error.

### Canon EOS R10

1. `pip install -e ".[canon]"`, or `sudo dnf install libgphoto2 gphoto2 python3-gphoto2`. Check the connection with `gphoto2 --auto-detect`.
2. Turn the camera on and connect a USB data cable. Turn **Wi-Fi and Bluetooth off** (while they are connected the R10 disables USB control) and disable auto power off.
3. For video, put the photo/movie switch on movie and insert a card.
4. On GNOME the file manager claims the camera. If you get "could not claim the USB device", run `gio mount -s gphoto2; pkill -f gvfs-gphoto2-volume-monitor`.

### FLIR Blackfly S

The camera needs one of these two libraries (neither is on PyPI).

**Spinnaker + PySpin** (Teledyne's SDK):

1. Install the Spinnaker SDK from teledynevisionsolutions.com.
2. Install the matching wheel with `pip install spinnaker_python-<version>-cp3XX-...whl`.

**Aravis** (open source, easiest on Fedora):

1. Install the packages:
   - Fedora: `sudo dnf install aravis-0.8 aravis-0.8-viewer python3-gobject`
   - Ubuntu: `sudo apt install gir1.2-aravis-0.8 aravis-tools python3-gi`
2. Create the venv with `--system-site-packages`.
3. Install Aravis's udev rule (`aravis.rules`) into `/etc/udev/rules.d/`, or test once with `sudo`.

With either library:

- Use a USB3 port (the blue one).
- For full-speed video, raise the USB buffer: `echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb`.
- Check that the camera is found with `equipment flir list`.

---

## Python API

```python
from equipment import main_ramp, main_source_ramp, main_paired_ramp, main_pe300_set

rows = main_ramp({"i_min": 0, "i_max": 0.5, "step": 0.05, "step_time": 2,      # DC2200
                  "output_csv": "output/ramp/run1.csv"})

main_pe300_set({"intensity": 30, "channels": "ABC"})                           # stays on

rows = main_source_ramp({"source": "pe300", "channels": "B", "min": 0, "max": 100,
                         "step": 10, "step_time": 2})

# any source + any measurements: pE-300 + FLIR + PM400
out = main_paired_ramp({"source": "pe300", "min": 0, "max": 100, "step": 10,
                        "step_time": 10,
                        "camera": "mysample", "camera_type": "flir",
                        "shutter": "1/250", "gain": 0, "whitebalance": "off",
                        "power": True, "wavelength": 470,
                        "output_csv": "output/ramp/run2.csv"})
# out = {"rows": ramp rows, "photos": [files], "power": [power rows]}
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
    ├── utils.py                      UTC time stamps, CSV writing, output paths, value matching
    ├── capture.py                    shared by both cameras: file numbering, capture log
    ├── sources.py                    LightSource interface + registry (dc2200, pe300)
    ├── ramp.py                       stepped ramp of any light source
    ├── thorlabs/
    │   ├── common.py                 USB IDs, serial numbers / VISA resources
    │   ├── usb_driver.py             kernel-driver detach (pyusb)
    │   ├── dc2200.py                 DC2200Source, constant current, ramp
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
