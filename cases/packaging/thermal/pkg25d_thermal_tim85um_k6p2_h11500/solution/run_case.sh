#!/usr/bin/env bash
# Re-runs the analysis from the files beside this script and rewrites results.csv.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
exec python3 pkg25d.py 1.0
