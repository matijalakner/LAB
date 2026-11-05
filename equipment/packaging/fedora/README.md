# Fedora installer

`install.sh` sets up the lab software on Fedora: every instrument works (DC2200, PM400, pE-300, FLIR Blackfly S, Canon EOS R10), from a normal user account, without `sudo`.

Contents: [Requirements](#requirements) · [Install](#install) · [What it changes](#what-it-changes) · [Options](#options) · [After installing](#after-installing) · [Updating](#updating) · [Undo](#undo) · [Troubleshooting](#troubleshooting)

## Requirements

- Fedora 39 or newer (other RHEL-like systems may work: Rocky, Alma, CentOS Stream)
- a user account that may use `sudo`
- an internet connection (dnf, pip, and Aravis's source code on GitHub)
- about 15 minutes, most of it compiling Aravis

## Install

```bash
git clone https://github.com/matijalakner/LAB.git     # or Download ZIP on GitHub and unpack it
cd LAB
./install.sh
```

Run it as your **normal user**, not with `sudo`. It asks for your password once, at the start. `./install.sh` in `LAB` recognises Fedora and starts `equipment/packaging/fedora/install.sh`; you can also run that file directly.

## What it changes

| Step | What | Where |
|---|---|---|
| 1. System packages | Python 3, `python3-gobject`, libusb, libgphoto2, and the build tools for Aravis (meson, ninja, the `-devel` packages) | dnf |
| 2. Aravis 0.8 | the FLIR camera library, version 0.8.36, built from source (Fedora has no Aravis 0.8 package). An Aravis that is already in `/usr/local` is kept. | `/usr/local/lib64`, plus `/etc/ld.so.conf.d/lab-aravis.conf` and `/etc/profile.d/lab-aravis.sh` so programs find it; source in `~/.cache/lab-equipment/aravis` |
| 3. Permissions | udev rules so the DC2200, PM400 (1313), pE-300 (0483:a080) and FLIR (1e10) open without `sudo`; you are added to the `dialout` group (serial ports) | `/etc/udev/rules.d/99-lab-equipment.rules`, `/etc/group` |
| 4. USB buffer | 1000 MB usbfs buffer, which the FLIR camera needs at full speed (default: 16 MB) | `/etc/systemd/system/lab-usbfs-memory.service` |
| 5. Python environment | `LAB/lab`, with access to Fedora's Python packages (for Aravis's GObject bindings) | `LAB/lab` |
| 6. Python packages | `equipment` with the thorlabs, coolled, flir and canon extras, and `line-analysis` | `LAB/lab` |
| 7. Check | `equipment doctor` | prints only |

It also creates `LAB/data/input` and `LAB/data/output` if they are missing.

## Options

```bash
./install.sh --help
```

| Option | Effect |
|---|---|
| `--no-canon` | no Canon support (skips libgphoto2) |
| `--no-flir` | no FLIR support (skips building Aravis) |
| `--mask-gvfs` | stops GNOME from grabbing the Canon over USB (see [Troubleshooting](#troubleshooting)) |
| `--python-only` | only steps 5–7: make or update the Python environment, change nothing else |

## After installing

1. **Log out and back in once.** After that, the `dialout` group and the Aravis paths apply everywhere. The udev rules already work without logging out, but unplug and replug instruments that were connected during the install.
2. **Every time you work**, open a terminal and run:

   ```bash
   cd LAB
   source setup.sh
   ```

3. **Check** with `equipment doctor`. It lists what is ready and what is missing, with the fix.

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
# Aravis in /usr/local:
sudo ninja -C ~/.cache/lab-equipment/aravis/build uninstall
sudo rm /etc/ld.so.conf.d/lab-aravis.conf /etc/profile.d/lab-aravis.sh && sudo ldconfig
systemctl --user unmask gvfs-gphoto2-volume-monitor.service # if you used --mask-gvfs
```

The dnf packages stay installed; remove them with `sudo dnf remove ...` if you want.

## Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied` for `/dev/ttyACM0` (pE-300) or a USB device | unplug and replug the instrument; if it persists, log out and back in |
| `Python cannot load Aravis` at the end of step 2 | open a new terminal (or `source /etc/profile.d/lab-aravis.sh`) and run `./install.sh` again |
| `meson setup` fails | an old build is in the way: `rm -rf ~/.cache/lab-equipment/aravis` and run again |
| the FLIR camera drops frames | `cat /sys/module/usbcore/parameters/usbfs_memory_mb` must say 1000; `sudo systemctl start lab-usbfs-memory.service` |
| Canon: `could not claim the USB device` | GNOME holds the camera: `./install.sh --mask-gvfs`, then unplug and replug the camera |
| `this does not look like Fedora` | on another distribution, choose the installer: `LAB_SYSTEM=ubuntu ./install.sh` |
| anything else | `equipment doctor` and its `fix:` lines |
