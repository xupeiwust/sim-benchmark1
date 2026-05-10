ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/openfoam/openfoam10-paraview510:latest

USER root

# Mount the sim-skills OpenFOAM playbook (17 reference docs), matching the
# 8 original cases' setup. Regime-parity for apples-to-apples model comparisons.
COPY --from=sim-skills-src . /opt/sim-skills/openfoam/

# Override upstream entrypoint (would exec /entry.sh and exit); Harbor
# needs the container to idle via `sleep infinity`.
ENTRYPOINT []

# terminus-2 needs tmux + asciinema; verify.py needs python3.
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
