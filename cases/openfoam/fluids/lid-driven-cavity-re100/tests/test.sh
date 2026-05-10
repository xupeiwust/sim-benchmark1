#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier
python3 "$(dirname "$0")/verify.py"
