#!/usr/bin/env bash
# Oracle entry point. solve.py writes /tmp/agent/result.json directly;
# this wrapper just sources the OpenFOAM env and execs solve.py.
set -o pipefail
if [ -z "${WM_PROJECT_DIR:-}" ] && [ -f /opt/openfoam10/etc/bashrc ]; then
    # shellcheck disable=SC1091
    source /opt/openfoam10/etc/bashrc
fi
exec python3 "$(dirname "$0")/solve.py"
