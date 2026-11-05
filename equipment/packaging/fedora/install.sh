#!/usr/bin/env bash
# Install the lab software on Fedora.
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
#   1. System packages        dnf: Python, libusb, libgphoto2, build tools
#   2. Aravis 0.8             FLIR camera library, built into /usr/local
#   3. Permissions            udev rules + the dialout group: no sudo needed
#   4. USB buffer             1000 MB for the FLIR camera, now and at every boot
#   5. Python environment     LAB/lab, with access to the system packages
#   6. Python packages        equipment and line-analysis
#   7. Check                  equipment doctor
#
# Run it as your normal user; it asks for your password where root is needed.
# Running it again is safe: finished steps are skipped or simply repeated.
# Documentation: packaging/fedora/README.md
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=../common/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../common/lib.sh"

PYTHON=/usr/bin/python3                 # Fedora's Python, which has GObject (python3-gobject)
LOCAL_LIBDIR=lib64                      # where an Aravis built from source goes: /usr/local/lib64

# --- 1. System packages ------------------------------------------------------
install_system_packages() {
  local pkgs=(python3 python3-devel python3-pip python3-gobject gobject-introspection
              libusb1 gcc pkgconf-pkg-config git)
  if [ "$WITH_CANON" = 1 ]; then
    pkgs+=(libgphoto2 libgphoto2-devel gphoto2)
  fi
  if [ "$WITH_FLIR" = 1 ]; then                       # to build Aravis
    pkgs+=(meson ninja-build glib2-devel libxml2-devel libusb1-devel zlib-devel
           gobject-introspection-devel)
  fi
  sudo dnf install -y "${pkgs[@]}"
}

# --- 2. Aravis (FLIR camera) -------------------------------------------------
# Fedora has no Aravis 0.8 package, so it is built from source. An Aravis that
# is already in /usr/local (e.g. built by hand) is kept and only registered.
install_aravis() {
  if [ "$WITH_FLIR" = 0 ]; then
    note "skipped (--no-flir)"
    return 0
  fi
  local typelibs="/usr/local/$LOCAL_LIBDIR/girepository-1.0"
  if [ -d "$typelibs" ]; then
    export GI_TYPELIB_PATH="$typelibs${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
  fi
  if aravis_works "$PYTHON"; then
    ok "Aravis 0.8 is already installed"
    if [ -d "$typelibs" ]; then
      register_local_aravis "$LOCAL_LIBDIR"
    fi
  else
    build_aravis "$LOCAL_LIBDIR"
  fi
  aravis_works "$PYTHON" || warn "Python cannot load Aravis; see packaging/fedora/README.md"
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
    grep -qE '^ID="?fedora"?' /etc/os-release 2>/dev/null \
      || warn "this does not look like Fedora; the dnf steps may fail"
    ask_sudo_once
    step "System packages (dnf)";            install_system_packages
    step "Aravis 0.8 (FLIR camera)";         install_aravis
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
