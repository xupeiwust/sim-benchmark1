#!/usr/bin/env bash
# Oracle entry point. solve.py writes /tmp/agent/result.json directly.
# Foundation v11 sources from /opt/openfoam11/etc/bashrc (NOT ESI's path).
set -o pipefail
if [ -z "${WM_PROJECT_DIR:-}" ] && [ -f /opt/openfoam11/etc/bashrc ]; then
    source /opt/openfoam11/etc/bashrc
fi
exec python3 "$(dirname "$0")/solve.py"
