#!/usr/bin/env bash
set -euo pipefail
HERE="$(dirname "$(realpath "$0")")"
command -v ccx >/dev/null
exec python3 "$HERE/verify.py"
