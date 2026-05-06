# sim-benchmark-base — shared Docker image for solver-neutral cases

Every `cases/<domain>/<id>/environment/Dockerfile` should `FROM` this
image and add only **case-specific assets** on top. The base layer
provides:

| component | version / source |
|---|---|
| OpenFOAM | ESI v2412 (from `opencfd/openfoam-default:2412`) |
| CalculiX | distro package `calculix-ccx` |
| Gmsh     | distro package `gmsh` |
| sim-cli  | pinned by `SIM_CLI_REF` build arg (default `main`) |
| sim-skills | pinned by `SIM_SKILLS_REF` build arg (default `main`) |
| sim-benchmark-verifier | `lib/sim_benchmark_verifier/` from this repo, editable install |
| Node 20 + claude-code + ccr | for ClaudeCode agent harness |

## Environment variables exported by the base

| var | default | purpose |
|---|---|---|
| `SIM_SKILLS_ROOT` | `/opt/sim-skills` | where solver playbooks live |
| `SIM_DIR` | `/logs/agent/sim-cli` | where sim-cli writes run records (RunStore) |
| `SIM_CASE_DIR` | (case Dockerfile sets it) | where the current case's `assets/` tree lives |

## Minimal per-case Dockerfile

```dockerfile
ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# case-specific assets go under SIM_CASE_DIR/assets/
ENV SIM_CASE_DIR=/opt/vv/flatplate_zpg_subsonic
COPY assets ${SIM_CASE_DIR}/assets/
```

## Build

```bash
# from sim-benchmark/ repo root (so the COPY path hits lib/)
docker build -f environment/base/Dockerfile -t sim-benchmark-base:latest .
```

## Non-goals

- No commercial solvers (Fluent / CFX / Abaqus / STAR-CCM+). License
  walls; deferred to a separate `sim-benchmark-base-commercial` track.
- No SU2 in v0.1 — apt has no package; adding a tarball install is
  tracked but deferred until at least one case actually uses it.
