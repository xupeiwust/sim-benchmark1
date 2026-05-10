#!/usr/bin/env bash
# Oracle entry point. solve.py writes /tmp/agent/result.json directly
# (which tests/verify.py reads); this wrapper just sources the OpenFOAM
# environment and execs solve.py.
set -o pipefail  # no -u: OpenFOAM's etc/bashrc references unset vars internally
if [ -z "${WM_PROJECT_DIR:-}" ] && [ -f /usr/lib/openfoam/openfoam2412/etc/bashrc ]; then
    # shellcheck disable=SC1091
    source /usr/lib/openfoam/openfoam2412/etc/bashrc
fi
exec python3 "$(dirname "$0")/solve.py"
