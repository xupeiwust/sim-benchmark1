ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/opencfd/openfoam-default:2412

USER root

COPY --from=sim-cli-src . /opt/sim-cli/
COPY --from=sim-skills-src . /opt/sim-skills/openfoam/
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip tmux procps curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --break-system-packages /opt/sim-cli/ asciinema


# Pre-install claude-code + claude-code-router + aiohttp for sim-benchmark
# harness (claude-code-router translates Anthropic requests for MiniMax;
# openai_usage_proxy.py needs aiohttp).
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz     | tar -xz -C /usr/local --strip-components=1     && npm config set registry https://registry.npmmirror.com     && npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router     && (pip3 install --no-cache-dir aiohttp || pip3 install --no-cache-dir --break-system-packages aiohttp)

WORKDIR /root/case

# Pre-install Node.js 20 + claude-code so ClaudeCodeCN works with allow_internet=false
RUN curl -fkSL https://npmmirror.com/mirrors/node/v20.19.0/node-v20.19.0-linux-x64.tar.gz         | tar -xz -C /usr/local --strip-components=1     && npm config set registry https://registry.npmmirror.com     && npm install -g @anthropic-ai/claude-code     && claude --version
