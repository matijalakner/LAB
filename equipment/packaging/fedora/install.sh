#!/usr/bin/env bash
# Install everything the lab equipment needs on Fedora, in one go.
#
#   ./install.sh                 everything (DC2200, PM400, pE-300, FLIR, Canon)
#   ./install.sh --no-canon      without the Canon (libgphoto2)
#   ./install.sh --no-aravis     without building Aravis (no FLIR camera)
#   ./install.sh --mask-gvfs     also stop GNOME from grabbing the Canon over USB
#   ./install.sh --help
#
# Run it as your normal user (not with sudo): it asks for your password when it
# needs root, and the Python environment must belong to you. It can be run
# again at any time; steps that are already done are skipped.
#
# What it does
#   1. dnf: Python, libusb, libgphoto2, the build tools for Aravis
#   2. Aravis 0.8 for the FLIR camera (built from source into /usr/local)
#   3. udev rules: the DC2200, PM400, pE-300 and FLIR open without sudo
#   4. the 'dialout' group for serial ports, a 1000 MB USB buffer for the camera
#   5. the Python environment (LAB/lab, the same one setup.sh uses) with
#      equipment and line-analysis
#   6. 'equipment doctor' to check the result
set -euo pipefail

ARAVIS_VERSION=0.8.36
WITH_CANON=1
WITH_ARAVIS=1
MASK_GVFS=0

for arg in "$@"; do
  case "$arg" in
    --no-canon)  WITH_CANON=0 ;;
    --no-aravis) WITH_ARAVIS=0 ;;
    --mask-gvfs) MASK_GVFS=1 ;;
    -h|--help)   sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EQUIPMENT="$(cd "$HERE/../.." && pwd)"
LAB="$(cd "$EQUIPMENT/.." && pwd)"
if [ -d "$LAB/line-analysis" ]; then
  VENV="$LAB/lab"                  # the same environment as LAB/setup.sh
else
  LAB=""
  VENV="$EQUIPMENT/.venv"
fi
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/lab-equipment"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '\033[33m   ! %s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not with sudo (it uses sudo itself where needed)." >&2
  exit 1
fi
if ! grep -qE '^ID="?fedora"?' /etc/os-release 2>/dev/null; then
  warn "this is not Fedora; the dnf steps may fail (continuing)"
fi
sudo -v                            # ask for the password once, at the start

# ---------------------------------------------------------------------------
say "1/6  System packages (dnf)"
PKGS=(python3 python3-devel python3-pip python3-gobject gobject-introspection
      libusb1 gcc pkgconf-pkg-config git)
[ "$WITH_CANON" = 1 ] && PKGS+=(libgphoto2 libgphoto2-devel gphoto2)
[ "$WITH_ARAVIS" = 1 ] && PKGS+=(meson ninja-build glib2-devel libxml2-devel libusb1-devel
                                 zlib-devel gobject-introspection-devel)
sudo dnf install -y "${PKGS[@]}"

# ---------------------------------------------------------------------------
aravis_ok() {
  GI_TYPELIB_PATH="/usr/local/lib64/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}" \
    /usr/bin/python3 -c "import gi; gi.require_version('Aravis', '0.8'); from gi.repository import Aravis" \
    2>/dev/null
}

say "2/6  Aravis $ARAVIS_VERSION (FLIR camera)"
if [ "$WITH_ARAVIS" = 0 ]; then
  note "skipped (--no-aravis)"
elif aravis_ok; then
  note "Aravis 0.8 is already installed"
else
  mkdir -p "$CACHE"
  if [ ! -d "$CACHE/aravis/.git" ]; then
    git clone https://github.com/AravisProject/aravis.git "$CACHE/aravis"
  fi
  git -C "$CACHE/aravis" fetch --tags --quiet
  git -C "$CACHE/aravis" checkout --quiet "$ARAVIS_VERSION"
  rm -rf "$CACHE/aravis/build"
  meson setup "$CACHE/aravis/build" "$CACHE/aravis" --prefix=/usr/local \
    -Dviewer=disabled -Dgst-plugin=disabled -Ddocumentation=disabled \
    -Dintrospection=enabled -Dusb=enabled -Dtests=false
  ninja -C "$CACHE/aravis/build"
  sudo ninja -C "$CACHE/aravis/build" install
fi
if [ "$WITH_ARAVIS" = 1 ]; then
  # /usr/local is not searched by default: register it for the loader and for GObject
  echo /usr/local/lib64 | sudo tee /etc/ld.so.conf.d/lab-aravis.conf >/dev/null
  sudo ldconfig
  sudo tee /etc/profile.d/lab-aravis.sh >/dev/null <<'PROFILE'
# Aravis in /usr/local (installed by the lab equipment installer)
export GI_TYPELIB_PATH="/usr/local/lib64/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
PROFILE
  export GI_TYPELIB_PATH="/usr/local/lib64/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
  if aravis_ok; then note "Aravis OK"; else warn "Aravis could not be loaded from Python"; fi
  if [ -f "$CACHE/aravis/src/aravis.rules" ]; then
    sudo install -m 0644 "$CACHE/aravis/src/aravis.rules" /etc/udev/rules.d/80-aravis.rules
  fi
fi

# ---------------------------------------------------------------------------
say "3/6  udev rules (instruments open without sudo)"
sudo install -m 0644 "$HERE/99-lab-equipment.rules" /etc/udev/rules.d/99-lab-equipment.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
note "installed /etc/udev/rules.d/99-lab-equipment.rules"
note "unplug and replug instruments that were connected during the install"

# ---------------------------------------------------------------------------
say "4/6  Serial-port group and USB buffer"
if id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
  note "$USER is already in the dialout group"
else
  sudo usermod -aG dialout "$USER"
  note "added $USER to the dialout group (active after the next login;"
  note "the udev rule already gives access now)"
fi
USBFS=/sys/module/usbcore/parameters/usbfs_memory_mb
if [ -w "$USBFS" ] || sudo test -e "$USBFS"; then
  echo 1000 | sudo tee "$USBFS" >/dev/null && note "USB buffer 1000 MB (now)"
fi
if command -v grubby >/dev/null; then
  if ! sudo grubby --info=DEFAULT 2>/dev/null | grep -q 'usbcore.usbfs_memory_mb=1000'; then
    sudo grubby --update-kernel=ALL --args="usbcore.usbfs_memory_mb=1000"
    note "USB buffer 1000 MB after every reboot (kernel option)"
  else
    note "USB buffer already set for every boot"
  fi
fi
if [ "$WITH_CANON" = 1 ] && [ "$MASK_GVFS" = 1 ]; then
  if systemctl --user mask --now gvfs-gphoto2-volume-monitor.service 2>/dev/null; then
    note "GNOME no longer grabs cameras over USB"
    note "(undo: systemctl --user unmask gvfs-gphoto2-volume-monitor.service)"
  else
    warn "could not mask gvfs-gphoto2-volume-monitor"
  fi
fi

# ---------------------------------------------------------------------------
say "5/6  Python environment: $VENV"
if [ -f "$VENV/pyvenv.cfg" ] && ! grep -q 'include-system-site-packages = true' "$VENV/pyvenv.cfg"; then
  warn "the existing environment cannot see the system packages (Aravis); it is recreated"
  mv "$VENV" "$VENV.old.$(date +%Y%m%d%H%M%S)"
fi
[ -d "$VENV" ] || /usr/bin/python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
EXTRAS="thorlabs,coolled,flir"
[ "$WITH_CANON" = 1 ] && EXTRAS="$EXTRAS,canon"
if [ -n "$LAB" ]; then
  "$VENV/bin/python" -m pip install -e "${EQUIPMENT}[${EXTRAS}]" -e "${LAB}/line-analysis[test]"
  mkdir -p "$LAB/data/input" "$LAB/data/output"
else
  "$VENV/bin/python" -m pip install -e "${EQUIPMENT}[${EXTRAS}]"
fi

# ---------------------------------------------------------------------------
say "6/6  Check (equipment doctor)"
"$VENV/bin/equipment" doctor || true

say "Done"
if [ -n "$LAB" ]; then
  note "Start working in a new terminal with:   source $LAB/setup.sh"
else
  note "Start working in a new terminal with:   source $VENV/bin/activate"
fi
note "Log out and back in once, so the dialout group and Aravis paths apply everywhere."
note "Reboot once, so the 1000 MB USB buffer is permanent."
