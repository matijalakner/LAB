# shellcheck shell=bash
# shellcheck disable=SC2034   # the option and step variables are read by the installers
# =============================================================================
# common/lib.sh: building blocks shared by the Unix installers
#   packaging/fedora/install.sh, packaging/ubuntu/install.sh, packaging/macos/install.sh
#
# Each installer sources this file, parses its options with  parse_options "$@",
# and then calls these functions in order, one per step. Everything specific to a
# system (its package manager, where Aravis comes from, which Python) stays in
# that system's install.sh; everything the systems share is here, once.
#
# Written for bash 3.2 (the bash of macOS): no associative arrays, no mapfile,
# no ${var,,}, and arrays are never expanded empty under "set -u".
# =============================================================================

# Aravis version built from source where the system has no package for it.
ARAVIS_VERSION="0.8.36"

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------
LAB_STEP=0          # current step, counted by step()
LAB_STEPS=0         # number of steps, set by the installer

if [ -t 1 ]; then
  _BOLD=$'\033[1m'; _YELLOW=$'\033[33m'; _RED=$'\033[31m'; _GREEN=$'\033[32m'; _RESET=$'\033[0m'
else
  _BOLD=""; _YELLOW=""; _RED=""; _GREEN=""; _RESET=""
fi

# step "Title": prints the next numbered step heading, e.g. "== 2/7  Aravis"
step() {
  LAB_STEP=$((LAB_STEP + 1))
  printf '\n%s== %d/%d  %s%s\n' "$_BOLD" "$LAB_STEP" "$LAB_STEPS" "$*" "$_RESET"
}
note() { printf '   %s\n' "$*"; }
ok()   { printf '   %s%s%s\n' "$_GREEN" "$*" "$_RESET"; }
warn() { printf '   %s! %s%s\n' "$_YELLOW" "$*" "$_RESET"; }
die()  { printf '\n%serror: %s%s\n' "$_RED" "$*" "$_RESET" >&2; exit 1; }

# show_help: prints the comment block at the top of the calling installer
show_help() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

# -----------------------------------------------------------------------------
# Options shared by every Unix installer
# -----------------------------------------------------------------------------
WITH_CANON=1        # --no-canon: skip the Canon camera (libgphoto2)
WITH_FLIR=1         # --no-flir:  skip the FLIR camera library (Aravis)
MASK_GVFS=0         # --mask-gvfs (Linux): GNOME no longer grabs cameras over USB
PYTHON_ONLY=0       # --python-only: only the Python environment, no system changes

parse_options() {
  local arg
  for arg; do                     # "for arg" = every argument; safe when there are none
    case "$arg" in
      --no-canon)            WITH_CANON=0 ;;
      --no-flir|--no-aravis) WITH_FLIR=0 ;;
      --mask-gvfs)           MASK_GVFS=1 ;;
      --python-only)         PYTHON_ONLY=1 ;;
      -h|--help)             show_help; exit 0 ;;
      *) die "unknown option: $arg  (see $0 --help)" ;;
    esac
  done
}

# -----------------------------------------------------------------------------
# Paths
#   PACKAGING  equipment/packaging
#   EQUIPMENT  equipment
#   LAB        the LAB folder (empty when equipment is used on its own)
#   VENV       the Python environment: LAB/lab, or equipment/.venv
# -----------------------------------------------------------------------------
find_paths() {
  PACKAGING="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  EQUIPMENT="$(cd "$PACKAGING/.." && pwd)"
  LAB="$(cd "$EQUIPMENT/.." && pwd)"
  if [ -d "$LAB/line-analysis" ]; then
    VENV="$LAB/lab"
  else
    LAB=""
    VENV="$EQUIPMENT/.venv"
  fi
}

# -----------------------------------------------------------------------------
# Checks before anything is changed
# -----------------------------------------------------------------------------
require_normal_user() {
  if [ "$(id -u)" -eq 0 ]; then
    die "run this as your normal user, not with sudo. It asks for your password itself
       when it needs administrator rights, and the Python environment must be yours."
  fi
}

# Ask for the sudo password once, at the start, instead of in the middle.
ask_sudo_once() {
  note "Some steps need administrator rights: please enter your password."
  sudo -v || die "administrator rights are needed (sudo)"
}

# -----------------------------------------------------------------------------
# Linux: permissions and the USB buffer (Fedora, Ubuntu)
# -----------------------------------------------------------------------------

# udev rules: the DC2200, PM400, pE-300 and FLIR open without sudo
install_udev_rules() {
  sudo install -m 0644 "$PACKAGING/common/99-lab-equipment.rules" \
    /etc/udev/rules.d/99-lab-equipment.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  ok "installed /etc/udev/rules.d/99-lab-equipment.rules"
  note "Unplug and replug instruments that were connected during the install."
}

# The serial-port group (the udev rule already gives access; this is a fallback).
join_dialout_group() {
  if id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
    note "$USER is already in the dialout group"
  else
    sudo usermod -aG dialout "$USER"
    ok "added $USER to the dialout group (active after the next login)"
  fi
}

# 1000 MB usbfs buffer for the FLIR camera: now, and at every boot (systemd unit)
install_usb_buffer() {
  local param=/sys/module/usbcore/parameters/usbfs_memory_mb
  if [ -e "$param" ]; then
    echo 1000 | sudo tee "$param" >/dev/null
    ok "USB buffer: 1000 MB now"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    sudo install -m 0644 "$PACKAGING/common/lab-usbfs-memory.service" \
      /etc/systemd/system/lab-usbfs-memory.service
    sudo systemctl daemon-reload
    sudo systemctl enable lab-usbfs-memory.service >/dev/null 2>&1
    ok "USB buffer: 1000 MB at every boot (lab-usbfs-memory.service)"
  else
    warn "no systemd: set usbcore.usbfs_memory_mb=1000 as a kernel option yourself"
  fi
}

# GNOME's gvfs grabs cameras over USB, which blocks the Canon (only with --mask-gvfs)
mask_gvfs_camera_monitor() {
  if [ "$MASK_GVFS" != 1 ]; then
    note "GNOME may grab the Canon over USB; if so, run this again with --mask-gvfs"
    return 0
  fi
  if systemctl --user mask --now gvfs-gphoto2-volume-monitor.service >/dev/null 2>&1; then
    ok "GNOME no longer grabs cameras over USB"
    note "(undo: systemctl --user unmask gvfs-gphoto2-volume-monitor.service)"
  else
    warn "could not mask gvfs-gphoto2-volume-monitor.service"
  fi
}

# -----------------------------------------------------------------------------
# Aravis (FLIR camera)
# -----------------------------------------------------------------------------

# aravis_works PYTHON: true if that Python can load Aravis 0.8 through GObject
aravis_works() {
  "$1" -c "import gi; gi.require_version('Aravis', '0.8'); from gi.repository import Aravis" \
    >/dev/null 2>&1
}

# build_aravis LIBDIR: builds Aravis $ARAVIS_VERSION from source into /usr/local
#   LIBDIR is relative to /usr/local, e.g. lib64 (Fedora) or lib (Ubuntu).
#   The library is registered with the loader (/etc/ld.so.conf.d) and GObject
#   (/etc/profile.d), so every program and every new login finds it.
build_aravis() {
  local libdir="$1"
  local src="${XDG_CACHE_HOME:-$HOME/.cache}/lab-equipment/aravis"
  if [ ! -d "$src/.git" ]; then
    mkdir -p "$(dirname "$src")"
    git clone https://github.com/AravisProject/aravis.git "$src"
  fi
  git -C "$src" fetch --tags --quiet
  git -C "$src" checkout --quiet "$ARAVIS_VERSION"
  rm -rf "$src/build"
  meson setup "$src/build" "$src" --prefix=/usr/local --libdir="$libdir" \
    -Dviewer=disabled -Dgst-plugin=disabled -Ddocumentation=disabled \
    -Dintrospection=enabled -Dusb=enabled -Dtests=false
  ninja -C "$src/build"
  sudo ninja -C "$src/build" install
  register_local_aravis "$libdir"
  ok "Aravis $ARAVIS_VERSION built and installed in /usr/local"
}

# register_local_aravis LIBDIR: makes /usr/local/LIBDIR known to the loader and GObject
register_local_aravis() {
  local libdir="/usr/local/$1"
  echo "$libdir" | sudo tee /etc/ld.so.conf.d/lab-aravis.conf >/dev/null
  sudo ldconfig
  # shellcheck disable=SC2016   # $GI_TYPELIB_PATH is written literally into the file
  printf '# Aravis in /usr/local (lab equipment installer)\nexport GI_TYPELIB_PATH="%s/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"\n' \
    "$libdir" | sudo tee /etc/profile.d/lab-aravis.sh >/dev/null
  export GI_TYPELIB_PATH="$libdir/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
}

# -----------------------------------------------------------------------------
# Python environment
# -----------------------------------------------------------------------------

# python_is_new_enough PYTHON: 3.10 or newer
python_is_new_enough() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

# make_environment PYTHON: creates $VENV with access to the system packages
#   (--system-site-packages: GObject and Aravis come from the system, not from pip).
#   An existing environment without that access is moved aside and made again.
make_environment() {
  local python="$1"
  python_is_new_enough "$python" || die "$python is older than Python 3.10"
  if [ -f "$VENV/pyvenv.cfg" ] && ! grep -q 'include-system-site-packages = true' "$VENV/pyvenv.cfg"; then
    local old
    old="$VENV.old.$(date +%Y%m%d%H%M%S)"
    warn "the existing environment cannot see the system packages; moved to $old"
    mv "$VENV" "$old"
  fi
  if [ ! -d "$VENV" ]; then
    "$python" -m venv --system-site-packages "$VENV" || die "could not create $VENV"
    ok "created $VENV ($("$VENV/bin/python" --version))"
  else
    note "using the existing $VENV ($("$VENV/bin/python" --version))"
  fi
}

# install_lab_packages: equipment (and line-analysis, inside LAB) into $VENV
install_lab_packages() {
  local extras="thorlabs,coolled,flir"
  if [ "$WITH_CANON" = 1 ]; then
    extras="$extras,canon"
  fi
  "$VENV/bin/python" -m pip install --upgrade pip
  if [ -n "$LAB" ]; then
    "$VENV/bin/python" -m pip install -e "${EQUIPMENT}[${extras}]" -e "${LAB}/line-analysis[test]"
    mkdir -p "$LAB/data/input" "$LAB/data/output"
  else
    "$VENV/bin/python" -m pip install -e "${EQUIPMENT}[${extras}]"
  fi
  ok "installed equipment [$extras]${LAB:+ and line-analysis}"
}

# -----------------------------------------------------------------------------
# Check and finish
# -----------------------------------------------------------------------------
run_doctor() {
  "$VENV/bin/equipment" doctor || true
}

# finish "extra line" ...: how to start working, plus system-specific reminders
finish() {
  printf '\n%s== Done%s\n' "$_BOLD" "$_RESET"
  if [ -n "$LAB" ]; then
    note "Start working in a new terminal with:   cd $LAB && source setup.sh"
  else
    note "Start working in a new terminal with:   source $VENV/bin/activate"
  fi
  local line
  for line in "$@"; do note "$line"; done
  note "Check at any time with:                  equipment doctor"
}
