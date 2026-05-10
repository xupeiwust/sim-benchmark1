#!/usr/bin/env bash
# Oracle entry point. solve.py writes /tmp/agent/result.json directly.
set -o pipefail
if [ -z "${WM_PROJECT_DIR:-}" ] && [ -f /usr/lib/openfoam/openfoam2412/etc/bashrc ]; then
    source /usr/lib/openfoam/openfoam2412/etc/bashrc
fi
exec python3 "$(dirname "$0")/solve.py"
