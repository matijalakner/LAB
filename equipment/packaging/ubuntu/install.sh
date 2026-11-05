#!/usr/bin/env bash
# Install the lab software on Ubuntu (22.04 or newer; also Debian, Linux Mint, Pop!_OS).
#
# Usage:  ./install.sh [options]          (in LAB: ./install.sh starts this one)
#
# Options:
#   --no-canon      skip the Canon camera (libgphoto2)
#   --no-flir       skip the FLIR camera library (Aravis)
#   --mask-gvfs     stop GNOME from grabbing the Canon over USB
#   --python-only   only (re)make the Python environment; change nothing else
#   -h, --help      show this help
#
# Steps:
#   1. System packages        apt: Python, libusb, libgphoto2, build tools
#   2. Aravis 0.8             FLIR camera library: Ubuntu's package, or built from source
#   3. Permissions            udev rules + the dialout group: no sudo needed
#   4. USB buffer             1000 MB for the FLIR camera, now and at every boot
#   5. Python environment     LAB/lab, with access to the system packages
#   6. Python packages        equipment and line-analysis
#   7. Check                  equipment doctor
#
# Run it as your normal user; it asks for your password where root is needed.
# Running it again is safe: finished steps are skipped or simply repeated.
# Documentation: packaging/ubuntu/README.md
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=../common/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../common/lib.sh"

PYTHON=/usr/bin/python3                 # Ubuntu's Python, which has GObject (python3-gi)
LOCAL_LIBDIR=lib                        # an Aravis built from source goes to /usr/local/lib

# apt_has PACKAGE: true if apt can install PACKAGE (it has an install candidate)
apt_has() {
  apt-cache policy "$1" 2>/dev/null | grep -q 'Candidate: [0-9]'
}

# --- 1. System packages ------------------------------------------------------
install_system_packages() {
  local pkgs=(python3 python3-venv python3-dev python3-pip python3-gi gir1.2-glib-2.0
              libusb-1.0-0 build-essential pkg-config git)
  if [ "$WITH_CANON" = 1 ]; then
    pkgs+=(libgphoto2-dev gphoto2)
  fi
  sudo apt-get update
  sudo apt-get install -y "${pkgs[@]}"
}

# --- 2. Aravis (FLIR camera) -------------------------------------------------
# Ubuntu 24.04 has Aravis 0.8 in the "universe" repository (gir1.2-aravis-0.8).
# Where it is missing, Aravis is built from source like on Fedora.
install_aravis() {
  if [ "$WITH_FLIR" = 0 ]; then
    note "skipped (--no-flir)"
    return 0
  fi
  local typelibs="/usr/local/$LOCAL_LIBDIR/girepository-1.0"      # a source build from before
  if [ -d "$typelibs" ]; then
    export GI_TYPELIB_PATH="$typelibs${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
  fi
  if aravis_works "$PYTHON"; then
    ok "Aravis 0.8 is already installed"
    if [ -d "$typelibs" ]; then
      register_local_aravis "$LOCAL_LIBDIR"
    fi
  elif apt_has gir1.2-aravis-0.8; then
    sudo apt-get install -y gir1.2-aravis-0.8 aravis-tools
    ok "installed Ubuntu's Aravis package"
  else
    note "no Aravis 0.8 package (is the 'universe' repository enabled?): building it"
    sudo apt-get install -y meson ninja-build libglib2.0-dev libxml2-dev libusb-1.0-0-dev \
      zlib1g-dev libgirepository1.0-dev gobject-introspection
    build_aravis "$LOCAL_LIBDIR"
  fi
  aravis_works "$PYTHON" || warn "Python cannot load Aravis; see packaging/ubuntu/README.md"
}

# --- 3. Permissions -----------------------------------------------------------
set_permissions() {
  install_udev_rules
  join_dialout_group
}

# --- 4. USB buffer -------------------------------------------------------------
set_usb_buffer() {
  install_usb_buffer
  if [ "$WITH_CANON" = 1 ]; then
    mask_gvfs_camera_monitor
  fi
}

# --- 5.-7. Python environment, packages, check -----------------------------------
main() {
  parse_options ${1+"$@"}
  find_paths
  require_normal_user
  if [ "$PYTHON_ONLY" = 1 ]; then
    LAB_STEPS=3
  else
    LAB_STEPS=7
    command -v apt-get >/dev/null 2>&1 || die "apt-get not found: this installer is for Ubuntu/Debian"
    ask_sudo_once
    step "System packages (apt)";             install_system_packages
    step "Aravis 0.8 (FLIR camera)";          install_aravis
    step "Permissions (udev rules, dialout)"; set_permissions
    step "USB buffer";                        set_usb_buffer
  fi
  step "Python environment: $VENV";          make_environment "$PYTHON"
  step "Python packages";                    install_lab_packages
  step "Check (equipment doctor)";           run_doctor
  if [ "$PYTHON_ONLY" = 1 ]; then
    finish
  else
    finish "Log out and back in once (dialout group, Aravis paths)."
  fi
}

main ${1+"$@"}         # ${1+"$@"}: also safe without options in bash 3.2 (macOS)
