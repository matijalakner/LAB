#!/usr/bin/env bash
# One environment with both packages.
# Usage:  source setup.sh                     (creates the lab environment, installs, activates)
#         EXTRAS=all source setup.sh          (equipment extras; default thorlabs,coolled,flir)
#         PYTHON=python3.12 source setup.sh   (a specific Python)
cd "$(dirname "${BASH_SOURCE[0]}")" || return 1
# --system-site-packages: the FLIR camera's Aravis bindings come from the system
[ -d lab ] || ${PYTHON:-python3} -m venv --system-site-packages lab || return 1
# Aravis built into /usr/local by equipment/packaging/fedora/install.sh
if [ -d /usr/local/lib64/girepository-1.0 ]; then
  case ":${GI_TYPELIB_PATH:-}:" in
    *:/usr/local/lib64/girepository-1.0:*) ;;
    *) export GI_TYPELIB_PATH="/usr/local/lib64/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}" ;;
  esac
fi
source lab/bin/activate \
  && pip install --upgrade pip \
  && pip install -e "./equipment[${EXTRAS:-thorlabs,coolled,flir}]" -e "./line-analysis[test]" \
  && mkdir -p data/input data/output \
  && echo "Ready: 'equipment' and 'analysis' are available in this terminal."
