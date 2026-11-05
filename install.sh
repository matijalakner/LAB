#!/usr/bin/env bash
# Fedora: install everything for the lab equipment and the analysis.
# Options: see  ./install.sh --help  (equipment/packaging/fedora/install.sh)
exec "$(dirname "${BASH_SOURCE[0]}")/equipment/packaging/fedora/install.sh" "$@"
