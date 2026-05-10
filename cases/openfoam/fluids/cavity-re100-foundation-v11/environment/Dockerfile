ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/openfoam/openfoam11-paraview510:latest

USER root

# Override the upstream image's ENTRYPOINT (which runs /entry.sh and exits).
# Harbor's compose passes `command: [sh, -c, sleep infinity]`; with the
# upstream entrypoint in the way, /entry.sh would exec first and the
# container would exit immediately.
ENTRYPOINT []

# NOTE: this case INTENTIONALLY skips sim-cli installation. The Foundation
# v11 image ships Python 3.8.10, but sim-cli requires Python ≥ 3.10.
# Our oracle (solve.py) drives OpenFOAM directly via plain subprocess —
# sim-cli is not needed at the runtime level here. An LLM-agent run that
# wanted sim-cli inside this image would first need to install Python 3.10
# (e.g. via the deadsnakes PPA) — deferred until we actually need it.

# tmux + procps + asciinema are needed so Harbor's tmux-based runner can
# record an asciinema cast of the agent session inside this container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tmux procps python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install asciinema


# Pre-install claude-code + claude-code-router + aiohttp for sim-benchmark
# harness (claude-code-router translates Anthropic requests for MiniMax;
# openai_usage_proxy.py needs aiohttp).
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz     | tar -xz -C /usr/local --strip-components=1     && npm config set registry https://registry.npmmirror.com     && npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router     && (pip3 install --no-cache-dir aiohttp || pip3 install --no-cache-dir --break-system-packages aiohttp)

WORKDIR /root/case

# Pre-install Node.js 20 + claude-code so ClaudeCodeCN works with allow_internet=false
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz         | tar -xz -C /usr/local --strip-components=1     && npm config set registry https://registry.npmmirror.com     && npm install -g @anthropic-ai/claude-code     && claude --version
