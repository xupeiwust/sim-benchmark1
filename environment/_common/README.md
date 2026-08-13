# environment/_common — shared harness across all per-domain images

`install_harness.sh` is the **domain-agnostic substrate** every
`environment/domains/<domain>/` image installs on top of its solver
toolchain. It is the single source of truth for:

- sim-cli-core (uniform runtime + authenticity anchor)
- sim-benchmark-verifier (the grader)
- sim-skills (solver playbooks)
- Node 20 + claude-code + claude-code-router (agent harness)
- the token-recovery proxy + ccr plugins
- the non-root `agent` user (UID 1200)

## Why a script, not a shared base image

Different domains need different OS roots — `cfd` must be
`FROM opencfd/openfoam-default:2412` (OpenFOAM is not apt-installable),
while `eda-digital` is `FROM ubuntu:22.04`. A single shared `FROM` can't
serve both. So the shared substrate is a **reusable install step**, not a
shared parent image. Each domain `FROM`s its natural OS root and calls
this script after its `tools.sh`.

This is what keeps the harness DRY: bump the sim-cli pin / Node version /
claude-code install **here**, and every domain inherits it on next build.

## How a domain Dockerfile uses it

```dockerfile
# (after FROM + USER root + the domain tools.sh block)
COPY lib/sim_benchmark_verifier /opt/sim-benchmark-verifier/
COPY tools/openai_usage_proxy.py /opt/openai_usage_proxy.py
COPY tools/ccr-plugins /opt/ccr-plugins/
COPY environment/_common/install_harness.sh /tmp/install_harness.sh
ARG SIM_CLI_REF=main
ARG SIM_SKILLS_REF=main
RUN SIM_CLI_REF=${SIM_CLI_REF} SIM_SKILLS_REF=${SIM_SKILLS_REF} \
        bash /tmp/install_harness.sh
USER agent
WORKDIR /tmp/agent
ENTRYPOINT []
```

Build context is the **repo root** so the `COPY lib/...` / `COPY tools/...`
paths resolve. See `environment/domains/build.sh`.

## Tunables (build-args → env)

| var | default | purpose |
|---|---|---|
| `SIM_CLI_REF` | `main` | git ref for sim-cli-core (pin a SHA for reproducibility) |
| `SIM_SKILLS_REF` | `main` | git ref for sim-skills |
| `PIP_INDEX_URL` | TUNA | pip mirror |
| `NPM_REGISTRY` | npmmirror | npm mirror |
| `NODE_TARBALL_URL` | npmmirror | Node 20 tarball |
| `GH_PROXY` | `gh-proxy.com/` | github proxy prefix for CN build hosts |
| `AGENT_UID` | `1200` | non-root agent uid (avoids openfoam=1100 collision) |

For international build hosts (GitHub Actions, Docker Desktop) pass
`--build-arg GH_PROXY= --build-arg PIP_INDEX_URL=https://pypi.org/simple
--build-arg NPM_REGISTRY=https://registry.npmjs.org` etc.

## Relationship to the legacy bases

`environment/base/` (OpenFOAM-anchored) and `environment/wine-base/`
(LTspice) predate this refactor and are kept for the 19 OpenFOAM + the
LTspice cases already referencing them. New work uses the per-domain
images. `cfd` is the forward port of `base`; over time the
OpenFOAM cases can migrate to it.
