#!/usr/bin/env bash
# combustion toolchain — chemical kinetics / combustion.
#
# CORE is Cantera plus the numeric/plotting stack the cases need. Cantera is
# a *library*, not a batch solver, so there is no external binary to install:
# the pip wheel is the whole toolchain. Reaction mechanisms ship inside the
# wheel (gri30, h2o2, nDodecane_Reitz, and the example_data mechanisms for
# ammonia and n-hexane), so no mechanism files are vendored and no network
# access is needed at trial time.
#
# Edit this file to add/remove tools (see environment/domains/README.md).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# apt is pointed at a fast mirror for this script only; see the snippet for why
# a lasting rewrite is a trap. No-op unless APT_MIRROR is set.
. /tmp/apt_mirror.sh

apt-get update
apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    python3 python3-pip python3-venv
rm -rf /var/lib/apt/lists/*

python3 -m pip install --no-cache-dir --upgrade pip || true
PIP_BSP=""; python3 -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages' && PIP_BSP="--break-system-packages"

# Cantera (BSD-3-Clause) + the numeric/plot stack. matplotlib is required:
# every case asks the agent to produce a figure alongside its numbers.
# Exact pins, not ranges: the version a ground truth was calibrated on is
# part of the environment, and `cantera>=3.1,<4` would let a rebuild land on
# 3.3 while VERSIONS.md and every kpis.json `oracle_provenance.cantera_version`
# still claimed 3.2.0. See environment/domains/cfd/tools.sh for the full note.
python3 -m pip install --no-cache-dir ${PIP_BSP} \
    "cantera==3.2.0" \
    "numpy==2.5.1" \
    "scipy==1.18.0" \
    "matplotlib==3.11.1" \
    "ruamel.yaml==0.19.1"

# Headless by default so a stray pyplot import cannot block on a display.
echo "MPLBACKEND=Agg" >> /etc/environment

python3 -c "import cantera, matplotlib; print('cantera', cantera.__version__)"
