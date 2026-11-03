# equipment

Drivers and terminal control for the lab equipment:

| Instrument | Command | Python |
|---|---|---|
| Thorlabs **DC2200** LED driver | `equipment dc2200 set / off / ramp` | `equipment.thorlabs.dc2200` |
| Thorlabs **PM400** power meter | `equipment pm400 measure` | `equipment.thorlabs.pm400` |
| DC2200 + PM400 together (LIV curve) | `equipment liv` | `equipment.thorlabs.liv` |
| **Canon EOS R10** (USB, libgphoto2) | `equipment canon info / photo / timelapse / video` | `equipment.canon` |
| **FLIR Blackfly S** BFS-U3-27S5C-C (USB3 Vision) | `equipment flir list / info / photo / timelapse / video` | `equipment.flir` |
| DC2200 ramp with photos from either camera | `equipment dc2200 ramp ... --photos NAME` | `equipment.experiments.ramp_camera` |
| What is connected | `equipment devices` | `equipment.devices` |

The code was split out of [LineTracker](https://github.com/matijalakner/LineTracker) (its `src/Canon`, `src/FLIR`, `src/ThorLabs`). The file layout and CSV formats are unchanged, so LineTracker's `measurement analysis folder` and `analysis report` read the photos and ramp logs written here as they are.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
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

This command lists the Thorlabs USB devices with their serial numbers, the cameras gphoto2 sees, and the FLIR/GenICam cameras. It also prints the VISA resources the Thorlabs commands will use. A missing library is reported for its group only, so the other groups are still listed.

### DC2200 LED driver

Currents are in **amperes** (0 – 2 A). Check your LED head's rating first. The CLI refuses values above 2 A before it touches the device.

| Command | What it does |
|---|---|
| `dc2200 set CURRENT` | Constant current. **The LED stays on.** The user current limit is set to the same value. `set 0` switches the output off. |
| `dc2200 off` | Switches the output off. |
| `dc2200 ramp --min A --max A --step A --step-time S [--cycles N]` | Steps min → max → min. The LED is switched off at the end, on any error and on Ctrl+C. |

All DC2200 commands take `--dc2200-serial SN`.

**How the ramp steps.** With `--min 0 --max 0.5 --step 0.1 --step-time 2` the current goes 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0 A. Every value is held for 2 s, 22 s in total.

- The maximum is not repeated.
- If `max − min` is not a multiple of `step`, the last step up is shorter, so the ramp always reaches exactly `--max`.
- The steps are timed from a clock, so they do not drift.

**Ramp with photos.** These options are used together with `--photos NAME`:

| Option | Meaning |
|---|---|
| `--photos NAME` | Take photos, saved as `input/folder/NAME/NAME_XXXX.jpg` (numbering continues) |
| `--camera canon\|flir` | Which camera (default `canon`) |
| `--photo-delay S` | One photo per step, `S` s after the step starts (default: half the step time) |
| `--photo-interval S` | Instead: a photo every `S` s from the ramp start |
| `--shutter`, `--wb` | For both cameras |
| `--iso --color-temp --picture-style --image-format --sync-clock --keep-on-card` | Canon only |
| `--gain --wb-red --wb-blue --gamma --black-level --pixel-format --save-format --quality --defaults --serial --backend` | FLIR only |

How the ramp and the camera work together:

- The camera is connected first. If it is not found, the LED is never switched on.
- The camera runs in its own thread, so a slow capture never delays a current step.
- If the camera fails, the ramp stops and the LED is switched off.
- A photo log `<ramp>_photos.csv` is written next to the ramp CSV. It uses the same t = 0 as the ramp CSV, and its `current_A` column is the current that was set when each photo was taken.
- The CLI refuses camera options without `--photos`, and options that belong to the other camera.

### PM400 power meter

`equipment pm400 measure` (or `equipment pm measure`) takes these options:

| Option | Default |
|---|---|
| `--wavelength NM` | 450 |
| `--averaging-count N` | 10 |
| `--duration S` (`--sample-duration`) | 5 |
| `--rate HZ` (`--sample-rate`) | 10 |
| `--pm400-serial SN` | see [Thorlabs setup](#thorlabs-dc2200--pm400) |

### LIV (DC2200 + PM400)

`equipment liv` ramps the current linearly up and down and reads the power at every point.

| Option | Default |
|---|---|
| `--min A` | 0 |
| `--max A` | 0.05 |
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
| `dc2200 ramp` | `output/ramp/ramp_<UTC>.csv`; with `--photos` also `output/ramp/ramp_<UTC>_photos.csv` and `input/folder/<name>/` |
| `pm400 measure` | `output/pm/pm_<UTC>.csv` |
| `liv` | `output/liv/liv_<UTC>.csv` |
| `canon ...` | `input/folder/<name>/<name>_XXXX.jpg`/`.mp4`, log `output/camera/camera_<UTC>.csv` |
| `flir ...` | `input/folder/<name>/<name>_XXXX.jpg`/`.png`/`.tif`/`.mp4`, log `output/camera/flir_<UTC>.csv` |

`--output-csv NAME` changes the file name. A plain name goes into the command's folder (`--output-csv run1.csv` → `output/ramp/run1.csv`); a name that contains a folder is used as given. CSVs are written also when a run is interrupted.

The ramp, pm and camera CSVs start with a line `time_stamp,<UTC time at t = 0>`, then the header:

| File | Columns |
|---|---|
| ramp | `time_s, cycle, direction, current_A` |
| ramp photos | `time_s, index, file, utc, step, cycle, direction, current_A` |
| pm | `time_s, power_W` |
| liv | `time_s, cycle, direction, current_A, power_W` (no time stamp line) |
| camera / flir | `time_s, index, file, utc` |

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
from equipment import main_ramp, main_set_current, main_power_measurement
from equipment import main_photo, main_flir_timelapse, main_ramp_camera

rows = main_ramp({"i_min": 0, "i_max": 0.5, "step": 0.05, "step_time": 2,
                  "output_csv": "output/ramp/run1.csv"})

main_ramp_camera({"i_min": 0.05, "i_max": 1, "step": 0.05, "step_time": 100,
                  "camera": "mysample", "camera_type": "flir",
                  "shutter": "1/250", "gain": 0, "whitebalance": "off",
                  "output_csv": "output/ramp/run2.csv"})
```

Every `main_*` function takes a dict, or an object with the same attributes. The lower-level classes are `CanonCamera`, `FlirCamera`, `PM400` and `ThorlabsUSBDriver`. Names are imported lazily, so `import equipment` loads no hardware library. The scripts in `examples/` show every instrument.

## Project structure

```text
equipment/
├── pyproject.toml                    extras: thorlabs, canon, flir, all, test
├── examples/                         01_dc2200_ramp ... 06_ramp_with_photos
├── tests/                            parser, logic, and full runs with fake instruments
└── src/equipment/
    ├── __init__.py                   lazy public API
    ├── __main__.py                   python -m equipment
    ├── cli.py                        the `equipment` command
    ├── devices.py                    `equipment devices`
    ├── utils.py                      UTC time stamps, CSV writing, output paths, value matching
    ├── capture.py                    shared by both cameras: file numbering, capture log
    ├── thorlabs/
    │   ├── common.py                 USB IDs, serial numbers / VISA resources, timing helpers
    │   ├── usb_driver.py             kernel-driver detach (pyusb)
    │   ├── dc2200.py                 constant current and stepped ramp
    │   ├── pm400.py                  PM400 SCPI driver and power logging
    │   └── liv.py                    DC2200 + PM400 LIV measurement
    ├── canon/
    │   ├── camera.py                 CanonCamera (gphoto2)
    │   └── capture.py                photo, time-lapse, video
    ├── flir/
    │   ├── backends.py               Spinnaker/PySpin and Aravis
    │   ├── camera.py                 FlirCamera: settings, triggered photos, EXIF time
    │   └── capture.py                photo, time-lapse, video
    └── experiments/
        └── ramp_camera.py            DC2200 ramp with photos (Canon or FLIR)
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

The tests need no instrument. They check the command parser and the ramp, numbering and parsing logic. They also run the ramp, the ramp with photos and a Canon time-lapse end to end through the CLI, with fake instruments.
