# sim-benchmark-wine-base — shared image for Windows-only solvers via wine
#
# Mirrors environment/base/Dockerfile but the foundation is bare Ubuntu +
# wine instead of an OpenFOAM image. Each case under cases/<solver>/ that
# needs a Windows-native binary (LTspice, Flotherm, future tools) installs
# the binary on top of this base.
#
# Single canonical target — runs on any Linux host (paratera, rserver,
# Docker Desktop on Win/Mac via WSL2/HyperKit). No Windows host required.
#
# ---------------------------------------------------------------------------
# Default build (international networks, e.g. Docker Desktop, GitHub Actions):
#   docker build -t sim-benchmark-wine-base environment/wine-base/
#
# CN networks where dl.winehq.org / github.com is slow or blocked
# (e.g. paratera, rserver). Pass build-args to swap mirrors:
#   docker build -t sim-benchmark-wine-base \
#     --build-arg WINEHQ_KEY_URL=https://mirrors.ustc.edu.cn/wine-builds/winehq.key \
#     --build-arg WINEHQ_POOL_BASE=https://mirrors.cernet.edu.cn/wine-builds \
#     environment/wine-base/
#
# Pin to a specific sim-cli / sim-skills commit for reproducibility:
#   docker build ... --build-arg SIM_CLI_REF=<sha> --build-arg SIM_SKILLS_REF=<sha>
# ---------------------------------------------------------------------------

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    WINEDEBUG=-all \
    WINEPREFIX=/root/.wine \
    SIM_SKILLS_ROOT=/opt/sim-skills

USER root

# -- OS layer: bootstrap apt + WineHQ via CN-friendly mirrors ------------
# Distro-shipped wine on ubuntu 22.04 is 6.x — too old for LTspice 26
# (missing GetProcessGroupAffinity + api-ms-win-core-fibers-l1-1-2.dll
# from Win10+ API set, makes LTspice.exe load fail with c000007b).
# WineHQ ships current wine staging.
#
# Mirror layout (paratera/rserver can't reach dl.winehq.org):
# - Key: USTC (has winehq.key, but its .deb pool returns 404)
# - Pool/index: cernet (redirects to TUNA, has full file set)
ARG WINEHQ_KEY_URL=http://dl.winehq.org/wine-builds/winehq.key
ARG WINEHQ_POOL_BASE=http://dl.winehq.org/wine-builds
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && mkdir -pm755 /etc/apt/keyrings && \
    curl -fsSL ${WINEHQ_KEY_URL} -o /etc/apt/keyrings/winehq-archive.key && \
    printf 'Types: deb\nURIs: %s/ubuntu\nSuites: jammy\nComponents: main\nArchitectures: amd64 i386\nSigned-By: /etc/apt/keyrings/winehq-archive.key\n' "${WINEHQ_POOL_BASE}" \
        > /etc/apt/sources.list.d/winehq.sources && \
    apt-get update && apt-get install -y --install-recommends \
        winehq-stable \
        winetricks xvfb \
        wget git cabextract unzip jq \
        python3-pip python3-venv \
        build-essential \
        tmux procps \
    && rm -rf /var/lib/apt/lists/*

# -- bootstrap a wine prefix once (avoids first-run prompts at trial time)
# Skip wine-mono / wine-gecko: these are .NET / HTML render layers that
# wineboot otherwise tries to download from dl.winehq.org, which is
# unreachable from CN-region build hosts and hangs indefinitely. LTspice
# doesn't need either, so disable them via DLL overrides for this step.
RUN WINEDLLOVERRIDES="mscoree=,mshtml=" xvfb-run -a wineboot --init || true

# -- LTspice 64-bit (silent install via msiexec) -------------------------
# v0: shipped in wine-base because LTspice is the first user. When a
# second Win-only solver lands (Flotherm), split this into a child
# image (sim-benchmark-ltspice-base FROM sim-benchmark-wine-base).
RUN wget -q --no-check-certificate https://ltspice.analog.com/software/LTspice64.msi -O /tmp/lt.msi && \
    xvfb-run -a wine msiexec /i /tmp/lt.msi /quiet /norestart && \
    rm /tmp/lt.msi

# -- prime wine + LTspice (the trick from aanas-sayed/docker-ltspice) ---
# Critical: LTspice 26 batch hangs at 3% CPU on wine if wine's internal
# services (winebth, shell32) try to create X windows during their
# first-run init. Workaround: run LTspice once WITHOUT a display so
# those services fail-fast and complete their init. Subsequent
# invocations don't re-init, so they work normally. Without this, our
# v9 build sat at 3% CPU for 5 min until `timeout 300` killed it.
# Borrowed from https://github.com/aanas-sayed/docker-ltspice/blob/main/entrypoint.sh
RUN unset DISPLAY && \
    wine "/root/.wine/drive_c/Program Files/ADI/LTspice/LTspice.exe" -b 2>/dev/null || true && \
    wineserver --wait 2>/dev/null || true

# -- pre-bake telemetry-consent (skip first-launch dialog) ---------------
# LTspice 26 pops "Anonymously Share LTspice Usage Data" on first run
# and waits for a click before doing ANYTHING (including -b batch).
# In a headless container nobody clicks, so batch silently no-ops.
# Persisting CaptureAnalytics=false lets LTspice skip the dialog.
RUN APPDATA_DIR='/root/.wine/drive_c/users/root/Application Data' && \
    mkdir -p "$APPDATA_DIR" && \
    printf '[Options]\nUUID=00000000000000000001\nCaptureAnalytics=false\n' \
        > "$APPDATA_DIR/LTspice.ini"

# -- wine wrapper script ------------------------------------------------
# sim_ltspice.runner.run_net does `subprocess.run([install.exe, ...])`
# directly on Linux without prepending `wine`, so we expose a Linux
# executable that wraps wine + the real .exe.
#
# Two tricks bundled here, both required:
#   1. Prime LTspice once with no DISPLAY so wine internal services
#      (winebth, shell32) fail-fast their X-window creation. The init
#      state of those services is NOT persisted across container starts
#      via WINEPREFIX alone — it's a wineserver-process-local thing —
#      so the prime has to happen at runtime, every container start.
#   2. Run the actual command via xvfb-run -a so LTspice has a display
#      for whatever GUI bits it touches even in -b mode.
#
# Trick #1 borrowed from https://github.com/aanas-sayed/docker-ltspice/blob/main/entrypoint.sh
RUN printf '%s\n' \
    '#!/bin/bash' \
    '# Translate Linux paths → Windows Z: paths. LTspice 26 on wine' \
    '# silently no-ops on Linux paths (no .log/.raw produced) but works' \
    '# on `Z:\\path\\to\\file.net`. sim-ltspice runner passes script.as_posix()' \
    '# which is Linux-style; convert here so the library does not need patching.' \
    'args=()' \
    'for a in "$@"; do' \
    '    if [[ "$a" == /* && -e "$a" ]]; then' \
    '        args+=("$(winepath -w "$a")")' \
    '    else' \
    '        args+=("$a")' \
    '    fi' \
    'done' \
    '# Prime once: LTspice -b with no .net + no DISPLAY makes wine internal' \
    '# services (winebth, shell32) fail-fast their X-window creation.' \
    'if [ ! -f /tmp/.wine-primed ]; then' \
    '    DISPLAY= wine "/root/.wine/drive_c/Program Files/ADI/LTspice/LTspice.exe" -b 2>/dev/null || true' \
    '    wineserver --wait 2>/dev/null || true' \
    '    touch /tmp/.wine-primed' \
    'fi' \
    'exec xvfb-run -a wine "/root/.wine/drive_c/Program Files/ADI/LTspice/LTspice.exe" "${args[@]}"' \
    > /usr/local/bin/wine-ltspice && \
    chmod +x /usr/local/bin/wine-ltspice
ENV SIM_LTSPICE_EXE=/usr/local/bin/wine-ltspice

# -- pip CN mirror + recent pip (PyPI direct is too slow from rserver;
#    distro pip is too old to honour pyproject.toml [project].name) ------
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip install --no-cache-dir --upgrade pip

# -- sim-cli (the uniform runtime + authenticity anchor) -----------------
# Install from public GitHub. Pin to a ref via build-arg for reproducibility.
ARG SIM_CLI_REF=main
RUN pip install --no-cache-dir \
        "sim-cli-core @ git+https://github.com/svd-ai-lab/sim-cli@${SIM_CLI_REF}"

# -- sim-ltspice (Python API for LTspice; sim-cli driver delegates here) -
RUN pip install --no-cache-dir sim-plugin-ltspice

# -- sim-benchmark-verifier (the grader library) -------------------------
COPY lib/sim_benchmark_verifier /opt/sim-benchmark-verifier/
RUN pip install --no-cache-dir /opt/sim-benchmark-verifier

# -- sim-skills (solver playbooks) ---------------------------------------
ARG SIM_SKILLS_REF=main
RUN git clone --depth 1 --branch ${SIM_SKILLS_REF} \
        https://github.com/svd-ai-lab/sim-skills.git /opt/sim-skills \
    && rm -rf /opt/sim-skills/.git

# -- Node + claude-code + ccr (parity with environment/base for OpenFOAM) -
# Pre-bake to skip the ~60 s install at every trial start. Same npm
# mirror as the OpenFOAM base. URLs inlined so ARG/ENV ordering doesn't
# bite us across the multi-stage RUN.
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz \
        | tar -xz -C /usr/local --strip-components=1 \
    && npm config set registry https://registry.npmmirror.com \
    && npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router \
    && claude --version

# -- token-recovery proxy + ccr custom transformers ----------------------
# Source files copied from build context; agent_harness spawns the proxy
# at trial time and registers the minimax-system-merge transformer in
# ccr config when the upstream is MiniMax-OpenAI (which rejects mid-
# conversation system messages with error 2013).
COPY tools/openai_usage_proxy.py /opt/openai_usage_proxy.py
COPY tools/ccr-plugins /opt/ccr-plugins/
RUN pip install --no-cache-dir aiohttp

# -- environment contract (read by agents + grader) ----------------------
ENV SIM_DIR=/logs/agent/sim-cli
WORKDIR /root/case
