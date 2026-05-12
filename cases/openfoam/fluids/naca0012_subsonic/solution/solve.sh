#!/usr/bin/env bash
# Oracle entry for naca0012_subsonic.
set -euo pipefail

HERE="$(dirname "$(realpath "$0")")"
CASE_RUN="/root/case"

mkdir -p "$CASE_RUN"
cp -r "$HERE/case"/. "$CASE_RUN/"
cp "$HERE/gen_airfoil_stl.py"  "$CASE_RUN/gen_airfoil_stl.py"

export ORACLE_CASE="$CASE_RUN"
export ORACLE_HERE="$HERE"

exec sim run --solver openfoam "$HERE/solve_inner.py"
