# sim-benchmark-base — shared image for all solver-neutral cases
#
# Every cases/<domain>/<id>/environment/Dockerfile should do:
#     ARG BASE_REGISTRY=docker.io
#     FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest
#     # case-specific assets only
#     COPY assets /opt/vv/<case>/
#
# Providing a multi-solver environment so that the agent can genuinely
# pick any installed solver at trial time (solver-neutral benchmark).

ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/opencfd/openfoam-default:2412

USER root

# -- OS layer: need curl+tar+ca-certs before any downstream install ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tar gzip git python3-pip python3-venv \
        tmux procps build-essential \
    && rm -rf /var/lib/apt/lists/*

# -- sim-cli (the uniform runtime + authenticity anchor) ---------------
# Pinned by commit SHA — never track main.
ARG SIM_CLI_REF=main
RUN pip install --no-cache-dir --break-system-packages \
        "sim-cli @ git+https://github.com/svd-ai-lab/sim-cli@${SIM_CLI_REF}" \
        asciinema

# -- sim-benchmark-verifier (the grader library) -----------------------
# Installed from a path COPY so dev iteration doesn't hit the registry.
COPY lib/sim_benchmark_verifier /opt/sim-benchmark-verifier/
RUN pip install --no-cache-dir --break-system-packages -e /opt/sim-benchmark-verifier

# -- sim-skills (solver playbooks) -------------------------------------
ARG SIM_SKILLS_REF=main
RUN git clone --depth 1 --branch ${SIM_SKILLS_REF} \
        https://github.com/svd-ai-lab/sim-skills.git /opt/sim-skills \
    && rm -rf /opt/sim-skills/.git

# -- extra open-source solvers + meshing tools -------------------------
# OpenFOAM is already provided by the base image (ESI v2412).
# Add SU2, CalculiX, Gmsh via apt where available.
RUN apt-get update && apt-get install -y --no-install-recommends \
        calculix-ccx gmsh \
    && rm -rf /var/lib/apt/lists/* \
    && which ccx gmsh || true   # installed paths vary across distros

# SU2: no apt package on Ubuntu 22.04; fetch a pre-built tarball.
# (Skipped for v0; SU2 support added incrementally if benchmark cases need it.)

# -- Node + Claude Code (only needed for ClaudeCode agent harness) -----
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz \
        | tar -xz -C /usr/local --strip-components=1 \
    && npm config set registry https://registry.npmmirror.com \
    && npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router \
    && claude --version

# -- environment contract (read by agents & grader) --------------------
ENV SIM_SKILLS_ROOT=/opt/sim-skills
ENV SIM_DIR=/logs/agent/sim-cli
# SIM_CASE_DIR is set per-trial by the case's own Dockerfile or Harbor.

WORKDIR /root/case
