#!/usr/bin/env bash
# Install the lab software on macOS (13 Ventura or newer; Apple Silicon or Intel).
#
# Usage:  ./install.sh [options]          (in LAB: ./install.sh starts this one)
#
# Options:
#   --no-canon      skip the Canon camera (libgphoto2)
#   --no-flir       skip the FLIR camera library (Aravis)
#   --python-only   only (re)make the Python environment; install nothing with Homebrew
#   -h, --help      show this help
#
# Steps:
#   1. Homebrew packages      Python, PyGObject, libusb, Aravis, libgphoto2
#   2. Python with GObject    picks the Homebrew Python that can load Aravis
#   3. Python environment     LAB/lab, with access to Homebrew's Python packages
#   4. Python packages        equipment and line-analysis
#   5. Check                  equipment doctor
#
# Needs Homebrew (https://brew.sh). Nothing is installed with sudo, and macOS
# needs no USB permission rules or driver changes. Running it again is safe.
# Documentation: packaging/macos/README.md
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=../common/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../common/lib.sh"

PYTHON=""                               # set in step 2

# --- 0. Homebrew -------------------------------------------------------------
find_homebrew() {
  local b
  if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do       # Apple Silicon, Intel
      if [ -x "$b" ]; then
        eval "$("$b" shellenv)"
        break
      fi
    done
  fi
  command -v brew >/dev/null 2>&1 || die "Homebrew is needed. Install it with
       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
       then open a new terminal and run this installer again."
  BREW_PREFIX="$(brew --prefix)"
}

# --- 1. Homebrew packages ------------------------------------------------------
install_homebrew_packages() {
  local pkgs=(python pygobject3 gobject-introspection libusb pkgconf git)
  if [ "$WITH_FLIR" = 1 ]; then
    pkgs+=(aravis)
  fi
  if [ "$WITH_CANON" = 1 ]; then
    pkgs+=(libgphoto2)
  fi
  brew install "${pkgs[@]}"
}

# --- 2. Python with GObject ------------------------------------------------------
# Homebrew builds PyGObject (and so Aravis's Python access) for its newest Python
# versions only. The first Homebrew Python that can load it is used.
choose_python() {
  local candidates=("$BREW_PREFIX/bin/python3")
  local py
  for py in "$BREW_PREFIX"/opt/python@3.*/bin/python3.[0-9]*; do
    case "$py" in *-config) continue ;; esac
    [ -x "$py" ] && candidates+=("$py")
  done
  for py in "${candidates[@]}"; do
    [ -x "$py" ] || continue
    python_is_new_enough "$py" || continue
    if [ "$WITH_FLIR" = 1 ]; then
      aravis_works "$py" || continue
    else
      "$py" -c "import gi" >/dev/null 2>&1 || continue
    fi
    PYTHON="$py"
    ok "using $PYTHON ($("$PYTHON" --version))"
    return 0
  done
  local what="GObject"
  if [ "$WITH_FLIR" = 1 ]; then
    what="GObject and Aravis"
  fi
  die "no Homebrew Python can load $what.
       Run: brew reinstall python pygobject3 aravis   and run this installer again."
}

# --- 3.-5. Python environment, packages, check -----------------------------------
main() {
  parse_options ${1+"$@"}
  find_paths
  require_normal_user
  [ "$(uname -s)" = Darwin ] || die "this installer is for macOS"
  if [ "$MASK_GVFS" = 1 ]; then
    warn "--mask-gvfs is for GNOME on Linux; ignored on macOS"
  fi
  find_homebrew
  if [ "$PYTHON_ONLY" = 1 ]; then
    LAB_STEPS=4
  else
    LAB_STEPS=5
    step "Homebrew packages";                install_homebrew_packages
  fi
  step "Python with GObject";                choose_python
  step "Python environment: $VENV";          make_environment "$PYTHON"
  step "Python packages";                    install_lab_packages
  step "Check (equipment doctor)";           run_doctor
  if [ "$WITH_CANON" = 1 ]; then
    finish "Canon: macOS's photo service grabs cameras; before a Canon command run" \
           "       killall -9 ptpcamerad   (and keep Photos / Image Capture closed)."
  else
    finish
  fi
}

main ${1+"$@"}         # ${1+"$@"}: also safe without options in bash 3.2 (macOS)
