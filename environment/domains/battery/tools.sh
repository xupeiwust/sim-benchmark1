#!/usr/bin/env bash
# battery toolchain — lithium-ion cell electrochemistry.
#
# CORE is PyBaMM plus the numeric/plotting stack the cases need. Like Cantera,
# PyBaMM is a *library*, not a batch solver: there is no external binary to
# install and the pip wheel is the whole toolchain. Parameter sets (Chen2020,
# Marquis2019, Ai2020, OKane2022, ...) ship inside the wheel as Python
# modules, so no data files are vendored and no network access is needed at
# trial time.
#
# `pybamm[all]` is deliberately NOT used: it drags in plotting/jupyter extras
# and the optional JAX backend. The base wheel already carries both solvers the
# oracles need — CasADi and IDAKLU — so no extra is required; the oracles use
# IDAKLU, which is what PyBaMM's own thermal examples use.
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

# PyBaMM (BSD-3-Clause) + the numeric/plot stack. matplotlib is required:
# every case asks the agent to produce a figure alongside its numbers.
#
# PyBaMM is pinned exactly, not floated: every case's gt_value is what this
# version's parameter sets and solver predict, and the OCV-envelope gate is
# calibrated against this version's stoichiometry limits. A minor bump can move
# both, so it is an environment-layer event that re-runs this domain's oracles
# (environment/domains/VERSIONS.md, "Bumping a toolchain version").
# Exact pins, not ranges -- pybamm was already pinned; the rest were not, so a
# rebuild silently moved numpy/scipy under a calibrated ground truth. See
# environment/domains/cfd/tools.sh for why this matters.
python3 -m pip install --no-cache-dir ${PIP_BSP} \
    "pybamm==26.7.1.0" \
    "numpy==2.5.1" \
    "scipy==1.17.1" \
    "pandas==3.0.5" \
    "matplotlib==3.11.1"

# Headless by default so a stray pyplot import cannot block on a display.
echo "MPLBACKEND=Agg" >> /etc/environment

python3 -c "import pybamm, matplotlib; print('pybamm', pybamm.__version__)"
