# Reproducing our results

Three paths, in order of increasing cost.

## Path A — pull prebuilt image from GHCR (recommended, fast)

Every case's environment is built by
`.github/workflows/push-case-images.yaml` on every push to main and
published at
`ghcr.io/svd-ai-lab/sim-benchmark/<solver>-<case-slug>:latest` (also
tagged with the immutable commit SHA).

```bash
pip install harbor                                                    # needs Python 3.12+
git clone https://github.com/svd-ai-lab/sim-benchmark && cd sim-benchmark

# If the GHCR package is still private, authenticate once:
# echo $GITHUB_TOKEN | docker login ghcr.io -u <username> --password-stdin

# Run the oracle. --ek docker_image=... tells Harbor to pull prebuilt
# instead of building locally. Expect Mean: 0.981 ± 0.0005.
harbor run -p cases/fluids/lid_driven_cavity_re100 \
    --agent oracle \
    --ek docker_image=ghcr.io/svd-ai-lab/sim-benchmark/openfoam-lid-driven-cavity-re100:latest
```

## Path B — build from source (paranoid / from-scratch verification)

Requires Docker, Python 3.12+, and GitHub access. Per `SCHEMA.md §9`:

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git /tmp/sim-cli-clone
git -C /tmp/sim-cli-clone checkout $(grep '^ref' SCHEMA.md | head -1 | awk '{print $3}')

# (CN dev hosts only — daemon's registry-mirrors are set elsewhere for us)
docker pull docker.1panel.live/opencfd/openfoam-default:2412
docker tag  docker.1panel.live/opencfd/openfoam-default:2412 opencfd/openfoam-default:2412

harbor run -p cases/fluids/lid_driven_cavity_re100 --agent oracle
```

The prebuilt image (Path A) and a from-source build (Path B) produce
bit-wise equivalent OpenFOAM runs because the Dockerfile pins every layer
input. Differences in the floating-point tail (< 1e-5) are expected and
absorbed by the `kpi_accurate` tolerance.

## Path C — run a real LLM agent (Harbor's terminus-2)

```bash
# Any OpenAI-compatible endpoint. Paratera example:
export OPENAI_API_KEY=sk-...

harbor run -c configs/paratera/kimi-cavity-re100.yaml
# reproduces the cavity-re100 / Kimi-K2.5 row in LEADERBOARD.md
```

For the full 5-model × 8-case matrix, use
`configs/paratera/full-matrix.yaml` plus the `v11-matrix.yaml` and
`dambreak-parallel.yaml` side configs — paths + key rotation documented
at the top of each YAML. Aggregate the three job directories with
`python3 tools/aggregate_leaderboard.py <dirs>`.

## Regional mirrors / registry overrides

Our `docker-compose.yaml` defaults to `docker.1panel.live` (a CN mirror
of Docker Hub). Outside CN, override to `docker.io`:

```bash
# Edit cases/_template/environment/docker-compose.yaml (and any case's
# environment/docker-compose.yaml) to set:
#     BASE_REGISTRY: docker.io
# Or pass it per-run:
harbor run --ek build.args.BASE_REGISTRY=docker.io ...
```
