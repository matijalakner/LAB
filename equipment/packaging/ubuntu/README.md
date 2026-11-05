# Ubuntu installer

`install.sh` sets up the lab software on Ubuntu: every instrument works (DC2200, PM400, pE-300, FLIR Blackfly S, Canon EOS R10), from a normal user account, without `sudo`.

Contents: [Requirements](#requirements) · [Install](#install) · [What it changes](#what-it-changes) · [Options](#options) · [After installing](#after-installing) · [Updating](#updating) · [Undo](#undo) · [Troubleshooting](#troubleshooting)

## Requirements

- Ubuntu 22.04 or newer; Debian 12, Linux Mint and Pop!_OS work the same way
- a user account that may use `sudo`
- an internet connection (apt, pip)
- the **universe** repository (enabled by default on Ubuntu Desktop), which has Aravis. Without it, Aravis is built from source, which adds about 10 minutes.

## Install

```bash
sudo apt install git                                  # if git is missing
git clone https://github.com/matijalakner/LAB.git     # or Download ZIP on GitHub and unpack it
cd LAB
./install.sh
```

Run it as your **normal user**, not with `sudo`. It asks for your password once, at the start. `./install.sh` in `LAB` recognises Ubuntu and its derivatives and starts `equipment/packaging/ubuntu/install.sh`. If yours is not recognised, run `LAB_SYSTEM=ubuntu ./install.sh`.

## What it changes

| Step | What | Where |
|---|---|---|
| 1. System packages | Python 3 with `venv` and `python3-gi`, libusb, libgphoto2, build tools | apt |
| 2. Aravis 0.8 | the FLIR camera library: Ubuntu's `gir1.2-aravis-0.8` and `aravis-tools`, or, where that package is missing, version 0.8.36 built from source | apt; or `/usr/local/lib` plus `/etc/ld.so.conf.d/lab-aravis.conf` and `/etc/profile.d/lab-aravis.sh` |
| 3. Permissions | udev rules so the DC2200, PM400 (1313), pE-300 (0483:a080) and FLIR (1e10) open without `sudo`; you are added to the `dialout` group (serial ports) | `/etc/udev/rules.d/99-lab-equipment.rules`, `/etc/group` |
| 4. USB buffer | 1000 MB usbfs buffer, which the FLIR camera needs at full speed (default: 16 MB) | `/etc/systemd/system/lab-usbfs-memory.service` |
| 5. Python environment | `LAB/lab`, with access to Ubuntu's Python packages (for Aravis's GObject bindings) | `LAB/lab` |
| 6. Python packages | `equipment` with the thorlabs, coolled, flir and canon extras, and `line-analysis` | `LAB/lab` |
| 7. Check | `equipment doctor` | prints only |

It also creates `LAB/data/input` and `LAB/data/output` if they are missing. Ubuntu's Python is "externally managed" (PEP 668), so nothing is installed into it with pip; everything Python goes into `LAB/lab`.

## Options

```bash
./install.sh --help
```

| Option | Effect |
|---|---|
| `--no-canon` | no Canon support (skips libgphoto2) |
| `--no-flir` | no FLIR support (skips Aravis) |
| `--mask-gvfs` | stops GNOME from grabbing the Canon over USB (see [Troubleshooting](#troubleshooting)) |
| `--python-only` | only steps 5–7: make or update the Python environment, change nothing else |

## After installing

1. **Log out and back in once**, so the `dialout` group applies. The udev rules already work without logging out, but unplug and replug instruments that were connected during the install.
2. **Every time you work**, open a terminal and run:

   ```bash
   cd LAB
   source setup.sh
   ```

3. **Check** with `equipment doctor`.

## Updating

```bash
cd LAB
git pull
./install.sh --python-only     # new Python dependencies; the full ./install.sh also works
```

## Undo

```bash
rm -rf LAB/lab                                              # the Python environment
sudo rm /etc/udev/rules.d/99-lab-equipment.rules && sudo udevadm control --reload-rules
sudo systemctl disable --now lab-usbfs-memory.service
sudo rm /etc/systemd/system/lab-usbfs-memory.service
sudo gpasswd -d "$USER" dialout                             # leave the dialout group
sudo apt remove gir1.2-aravis-0.8 aravis-tools              # Aravis from apt, or, if it was built:
#   sudo ninja -C ~/.cache/lab-equipment/aravis/build uninstall
#   sudo rm /etc/ld.so.conf.d/lab-aravis.conf /etc/profile.d/lab-aravis.sh && sudo ldconfig
systemctl --user unmask gvfs-gphoto2-volume-monitor.service # if you used --mask-gvfs
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied` for `/dev/ttyACM0` (pE-300) or a USB device | unplug and replug the instrument; if it persists, log out and back in |
| `no Aravis 0.8 package` | enable universe: `sudo add-apt-repository universe`, then run `./install.sh` again (or let it build Aravis) |
| `Python cannot load Aravis` | open a new terminal and run `./install.sh` again; check `apt policy gir1.2-aravis-0.8` |
| `ensurepip is not available` / venv fails | `sudo apt install python3-venv` (step 1 normally does this) |
| the FLIR camera drops frames | `cat /sys/module/usbcore/parameters/usbfs_memory_mb` must say 1000; `sudo systemctl start lab-usbfs-memory.service` |
| Canon: `could not claim the USB device` | GNOME holds the camera: `./install.sh --mask-gvfs`, then unplug and replug the camera |
| anything else | `equipment doctor` and its `fix:` lines |
