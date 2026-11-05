#!/usr/bin/env bash
# Install the lab software: recognises the system and starts its installer.
#
#   Fedora (and RHEL-like)        equipment/packaging/fedora/install.sh
#   Ubuntu (and Debian, Mint ...) equipment/packaging/ubuntu/install.sh
#   macOS                         equipment/packaging/macos/install.sh
#   Windows                       not this file: double-click install.bat
#
# Usage:  ./install.sh [options]      the options are passed on; see ./install.sh --help
#         LAB_SYSTEM=ubuntu ./install.sh   to choose the installer yourself
#
# Step-by-step guide: INSTALL.md
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

detect_system() {
  case "$(uname -s)" in
    Darwin) echo macos; return ;;
    Linux)  ;;
    MINGW*|MSYS*|CYGWIN*) echo windows; return ;;
    *) echo unknown; return ;;
  esac
  local id="" id_like=""
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091   # read in a subshell: only ID and ID_LIKE are taken
    id="$(. /etc/os-release && echo "${ID:-}")"
    # shellcheck disable=SC1091
    id_like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
  fi
  case " $id $id_like " in
    *" fedora "*|*" rhel "*|*" centos "*) echo fedora ;;
    *" ubuntu "*|*" debian "*)            echo ubuntu ;;
    *) echo unknown ;;
  esac
}

system="${LAB_SYSTEM:-$(detect_system)}"
case "$system" in
  fedora|ubuntu|macos)
    # through bash: works even if a ZIP download lost the files' executable flags
    exec bash "$here/equipment/packaging/$system/install.sh" ${1+"$@"} ;;
  windows)
    echo "On Windows, double-click install.bat (or run it in a terminal)." >&2
    exit 1 ;;
  *)
    echo "This system is not recognised. Installers exist for Fedora, Ubuntu, macOS and" >&2
    echo "Windows. Choose one yourself, e.g.  LAB_SYSTEM=ubuntu ./install.sh   (see INSTALL.md)" >&2
    exit 1 ;;
esac
