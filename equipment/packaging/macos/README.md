# macOS installer

`install.sh` sets up the lab software on macOS with Homebrew. Every instrument works (DC2200, PM400, pE-300, FLIR Blackfly S, Canon EOS R10). Nothing is installed with `sudo`, and macOS needs no USB permission rules or driver changes.

Contents: [Requirements](#requirements) · [Install](#install) · [What it changes](#what-it-changes) · [Options](#options) · [After installing](#after-installing) · [Updating](#updating) · [Undo](#undo) · [Troubleshooting](#troubleshooting)

## Requirements

- macOS 13 Ventura or newer, on Apple Silicon or Intel
- **Homebrew** (https://brew.sh). Install it first, if you don't have it:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

  It also installs Apple's command line tools, which include `git`.
- an internet connection

## Install

```bash
git clone https://github.com/matijalakner/LAB.git     # or Download ZIP on GitHub and unpack it
cd LAB
./install.sh
```

`./install.sh` in `LAB` recognises macOS and starts `equipment/packaging/macos/install.sh`. If macOS says the file is *not executable*, run `bash install.sh` instead (ZIP downloads may lose the executable flag).

## What it changes

| Step | What | Where |
|---|---|---|
| 1. Homebrew packages | `python`, `pygobject3`, `gobject-introspection`, `libusb`, `aravis` (FLIR, version 0.8.36), `libgphoto2` (Canon), `pkgconf`, `git` | Homebrew (`/opt/homebrew` or `/usr/local`) |
| 2. Python with GObject | picks the Homebrew Python that can load Aravis. Homebrew builds PyGObject only for its newest Python versions, so it is not always the default `python3`. | nothing is changed |
| 3. Python environment | `LAB/lab`, with access to that Python's Homebrew packages (PyGObject) | `LAB/lab` |
| 4. Python packages | `equipment` with the thorlabs, coolled, flir and canon extras, and `line-analysis` | `LAB/lab` |
| 5. Check | `equipment doctor` | prints only |

It also creates `LAB/data/input` and `LAB/data/output` if they are missing.

These Linux steps don't exist on macOS:

| Linux step | Why macOS doesn't need it |
|---|---|
| udev rules | macOS lets every user open USB devices that have no driver |
| `dialout` group | the pE-300's serial ports are open to every user |
| kernel driver detach | macOS has no driver for the Thorlabs instruments, so nothing holds them |
| USB buffer | there is no usbfs limit |

**libusb:** Homebrew's libusb is outside the default library path. `equipment` adds Homebrew's `lib` folder to the search path itself, and `source setup.sh` does the same for other programs.

## Options

```bash
./install.sh --help
```

| Option | Effect |
|---|---|
| `--no-canon` | no Canon support (skips libgphoto2) |
| `--no-flir` | no FLIR support (skips Aravis) |
| `--python-only` | install nothing with Homebrew: only make or update the Python environment |

## After installing

1. **Every time you work**, open Terminal and run:

   ```bash
   cd LAB
   source setup.sh          # works in zsh (the macOS default) and bash
   ```

2. **Check** with `equipment doctor`.

3. **Canon:** macOS's photo service (`ptpcamerad`) takes every camera that is plugged in. Before Canon commands, close Photos and Image Capture and run:

   ```bash
   killall -9 ptpcamerad
   ```

   `equipment doctor` warns you when it is running.

The pE-300 shows up as `/dev/cu.usbmodem…`. It is found automatically, and `equipment pe300 status` shows which port it uses.

## Updating

```bash
cd LAB
git pull
brew upgrade                   # newer Homebrew packages (optional)
./install.sh                   # updates the environment; --python-only skips Homebrew
```

If `brew upgrade` brings a new Python version, run `./install.sh` again. It picks the Python that has PyGObject; if that changed, delete `LAB/lab` first so the environment is made with it.

## Undo

```bash
rm -rf LAB/lab                                         # the Python environment
brew uninstall aravis libgphoto2 pygobject3            # the libraries, if nothing else needs them
```

Nothing else was changed on the system.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Homebrew is needed` | install it (see [Requirements](#requirements)), open a new terminal, run again |
| `no Homebrew Python can load GObject and Aravis` | `brew reinstall python pygobject3 aravis`, then run again |
| `libusb 1.0 not found` in `equipment doctor` | `brew install libusb`, and work in a terminal after `source setup.sh` |
| the DC2200 / PM400 is not found | check the cable and power; `equipment devices` lists what is connected |
| Canon: `could not claim the USB device` | `killall -9 ptpcamerad` (see [After installing](#after-installing)) |
| `permission denied` running `./install.sh` | `bash install.sh` |
| anything else | `equipment doctor` and its `fix:` lines |

**FLIR with Spinnaker instead of Aravis:** Teledyne also offers the Spinnaker SDK for macOS. If you install it and its PySpin wheel into `LAB/lab` (`LAB/lab/bin/pip install spinnaker_python-…whl`), `equipment` uses it automatically.
