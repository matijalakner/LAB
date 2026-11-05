# shellcheck shell=bash   # sourced by bash or zsh, never run on its own
# Activate the lab environment in this terminal (Fedora, Ubuntu, macOS):
#
#     source setup.sh          works in bash and zsh, from any folder
#
# After this, the 'equipment' and 'analysis' commands are available.
# The environment itself (LAB/lab) is made once by the installer:  ./install.sh
# (to only remake or update it:  ./install.sh --python-only). Windows: use the
# "LAB terminal" shortcut that install.bat puts on the desktop.

# --- where LAB is: this file's folder (bash: BASH_SOURCE, zsh: %x) ---------------
if [ -n "${BASH_SOURCE:-}" ]; then
  _lab_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then
  # shellcheck disable=SC2296   # zsh syntax, only evaluated by zsh
  _lab_dir="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
  _lab_dir="$(pwd)"
fi

if [ ! -f "$_lab_dir/lab/bin/activate" ]; then
  echo "The lab environment does not exist yet. Make it once with:  $_lab_dir/install.sh"
  unset _lab_dir
  # shellcheck disable=SC2317   # exit only runs when the file is run instead of sourced
  return 1 2>/dev/null || exit 1
fi

# --- _lab_prepend VAR DIR: put DIR in front of the path list VAR (once) ------------
_lab_prepend() {
  local current
  eval "current=\${$1:-}"
  case ":$current:" in
    *":$2:"*) ;;
    *) eval "export $1=\"\$2\${current:+:\$current}\"" ;;
  esac
}

# --- libraries outside the default search paths -----------------------------------
case "$(uname -s)" in
  Linux)
    # Aravis built from source by the Fedora/Ubuntu installer (/usr/local)
    for _d in /usr/local/lib64/girepository-1.0 /usr/local/lib/girepository-1.0; do
      if [ -d "$_d" ]; then _lab_prepend GI_TYPELIB_PATH "$_d"; fi
    done
    ;;
  Darwin)
    # Homebrew: Aravis's GObject data and libusb (for the Thorlabs instruments)
    _brew="$(brew --prefix 2>/dev/null || true)"
    if [ -n "$_brew" ]; then
      if [ -d "$_brew/lib/girepository-1.0" ]; then
        _lab_prepend GI_TYPELIB_PATH "$_brew/lib/girepository-1.0"
      fi
      _lab_prepend DYLD_FALLBACK_LIBRARY_PATH "$_brew/lib"
    fi
    ;;
esac

# --- activate --------------------------------------------------------------------
# shellcheck disable=SC1091   # made by the installer
. "$_lab_dir/lab/bin/activate"
echo "Ready: 'equipment' and 'analysis' are available in this terminal."
unset _lab_dir _d _brew
unset -f _lab_prepend
