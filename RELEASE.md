# sim-benchmark v0.1 MVP Release

This is the minimum viable public release plan for sim-benchmark. The release
is benchmark-first: the asset is the task suite, deterministic verifier, oracle
scoring path, and reproducible run contract. sim-cli and solver-specific skills
remain useful infrastructure, but they are not the public headline.

## Release Scope

v0.1 publishes 36 public runnable simulation tasks:

| Domain | Tasks | Oracle status |
|---|---:|---|
| LTspice circuits | 20 | 20 available |
| OpenFOAM fluids | 16 | 3 available, 13 deferred |
| Total | 36 | 23 available, 13 deferred |

The MVP scored release view is the 20 LTspice tasks. They are fully
oracle-verified on the current Windows Docker Desktop setup and exercise the
new structured `ltspice_log` provenance path.

The 16 OpenFOAM tasks remain public runnable tasks in the catalog. For v0.1,
their no-token oracle status is explicitly split from their public task status.
The three OpenFOAM oracle-available tasks still require a publishable
`svd-ai-lab/sim-benchmark-base:latest` image before they can be used in the
default release gate.

## Release Gate

Required before tagging v0.1:

```powershell
$env:DOCKER_HOST='npipe:////./pipe/docker_engine'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'

python -m pytest lib\sim_benchmark_verifier\tests --basetemp .pytest-tmp
python tools\v19_static_validate.py
harbor run -p cases/circuits --agent oracle --job-name release-v0.1-ltspice20-oracle -o jobs -n 4 --no-delete --force-build -y -q
```

Optional, after the OpenFOAM base image is built or published:

```powershell
harbor run -p cases/fluids --agent oracle `
  -i flatplate_zpg_subsonic `
  -i lid_driven_cavity_re100 `
  -i lid_driven_cavity_re1000 `
  --job-name release-v0.1-openfoam3-oracle -o jobs -n 3 --no-delete --force-build -y -q
```

Optional one-model reference run:

```powershell
$env:MINIMAX_API_KEY = [Environment]::GetEnvironmentVariable('MINIMAX_API_KEY','User')
harbor run -c configs\release-v0.1-ltspice20-minimax-m27.yaml -y -q --force-build
```

## Latest Local Gate

Run date: 2026-05-03, Asia/Shanghai.

| Gate | Result | Notes |
|---|---:|---|
| LTspice 20 oracle | 20/20, mean 1.000 | Release artifacts in `results\v0.1\` |
| OpenFOAM 3 oracle | 0/3 executed | Docker build failed before solver start because `docker.io/svd-ai-lab/sim-benchmark-base:latest` is not pullable locally |

The OpenFOAM failure is an image availability/release packaging issue, not a
task verifier or solver-result failure. v0.1 can ship with OpenFOAM cases in
the public catalog while limiting the MVP scored table to LTspice 20.

Release result artifacts:

- `results\v0.1\summary.json`
- `results\v0.1\ltspice20-oracle-20260503.csv`
- `results\v0.1\ltspice20-oracle-20260503.json`
- `results\v0.1\README.md`

## Local Dependency Snapshot

The local Docker build-context copies were refreshed from sibling repos before
this release handoff:

| Component | Snapshot |
|---|---|
| `sim-cli` | `431cc27` / `sim-cli-core 0.3.3` |
| `sim-skills` | `a32e99e` |
| `sim-plugin-ltspice` | `d9d60da` / `sim-plugin-ltspice 0.2.3` |
| `sim-ltspice` | `9db6bd9` |

These copies are local build inputs for the LTspice full image. The public
benchmark repo should either document the expected sibling checkout layout or
replace local copies with pinned package installs before publishing prebuilt
images.

## Public Website Surface

Create a dedicated benchmark page on https://svdailab.com/ for launch. The
page should include:

- benchmark positioning: industrial simulation agent benchmark
- v0.1 scope: 36 public runnable tasks
- MVP scored scope: 20 LTspice oracle-verified tasks
- OpenFOAM status: 16 public tasks, with base image/oracle packaging still in progress
- a small results table and links to the public repo, case catalog, schema, and reproduction guide

## Release Blockers

- Publish or document the OpenFOAM base image path if OpenFOAM oracle tasks are
  included in the default scored gate.
- Run at least one complete model reference run if a model leaderboard row is
  desired on day one.
- Split/copy the cleaned benchmark assets into the dedicated public benchmark
  repository.

## Non-Blockers

- Running a broad multi-model leaderboard.
- Finishing all 13 deferred OpenFOAM no-token oracles.
- Renaming historical v19 configs.
- Making sim-cli usage a scoring requirement.
