# Domain-image version manifest

> The **single source of truth** for what toolchain version each domain image
> ships. Generated/verified 2026-06-06 from the live built images.

## The rule: versions live in the environment, not the case

A case declares **which environment** it needs (its `docker_image` = a domain
image NAME) — it does **not** pin a version. The **version is an
environment-layer concern**, recorded here and pinned by the
`environment/domains/<d>/Dockerfile` + `tools.sh` at a given repo commit.

**Reproducibility coordinate = the git commit.** `environment/` (Dockerfiles +
this manifest) and `cases/` are versioned together: to reproduce a case's
ground truth, check out the commit, rebuild the domain image from its pinned
Dockerfile, run. There is no per-case version tag to maintain — bumping a
toolchain is one environment-layer change, not a sweep over hundreds of cases.

Consequences:
- Case `docker_image` stays `sim-benchmark-<domain>-fullstack:latest`. `:latest`
  is acceptable **because the real pin is the git-committed Dockerfile + this
  manifest**, not the mutable tag. (When images are pushed to a registry —
  `project_sim_benchmark_registry_pending` — `:latest` becomes an immutable
  `:<date>`/digest, repointed in one env-layer pass, still not per-case.)
- The case picks the **environment identity** (which image: `cfd`
  vs a future `cfd-foundation`; `eda-analog` vs `eda-analog-wine`) —
  that's a toolchain *choice*, legitimately the case's business. The *version
  within* that environment is this manifest's business.
- Each case's `tests/kpis.json` → `oracle_provenance.<solver>_version` must
  match the row below — the human cross-check that a GT was calibrated on the
  version the environment actually ships.

## Manifest (verified 2026-06-06)

Shared in every Linux fullstack image: **sim-cli-core 0.3.7**, the
`sim_benchmark_verifier` grader (git, current — study gate + multi-solver
anti-cheat baked 2026-06-06), claude-code **and codex** (both baked, so no agent
installs itself at trial time and no trial depends on the host's network).

**The base image column names a tag; the pin is the digest in the Dockerfile.**
A tag is mutable however specific it looks: `python:3.12-slim-bookworm`
resolved to Debian 12 on one host and to a trixie-based image on another the
same day. The phase-1 domains therefore pin `FROM <tag>@sha256:<digest>`, and
`tools/check_image_versions.py` fails any base that is not digest-pinned. Read
the digest from the Dockerfile, not from here — one place, and it is the one
the build uses.

**Two hosts must hold the same image bytes, not merely the same versions.** The
verifier is COPYed into the image, so two hosts can agree on every pinned
package and still score differently — they did. Build once and relay
(`docker save | gzip -1` via the tailnet relay), rather than building
separately; `check_image_versions.py` prints an evaluator fingerprint for
comparing hosts.

| domain image (`:latest`) | base image | core solver(s) + version | meshing / aux |
|---|---|---|---|
| `cfd-fullstack` | `opencfd/openfoam-default:2412` | **OpenFOAM ESI v2412** (`simpleFoam`/`pimpleFoam`/`interFoam`/`buoyantFoam`) | gmsh 4.12.1, python 3.12.3 |
| `fem-fullstack` | (debian) | **CalculiX `ccx` 2.17** | gmsh 4.8.4 |
| `eda-analog-fullstack` | `sim-benchmark-base` | **ngspice 36** | — |
| `eda-analog-wine-fullstack` | `sim-benchmark-wine-base` | **LTspice** (via `wine-ltspice` launcher, wine substrate) | — |
| `eda-digital-fullstack` | `sim-benchmark-base` | **Verilator 5.049** (rev v5.048-26-g25d4827bd), **Icarus Verilog 14.0** (s20251012) | — |
| `eda-digital-asic-fullstack` | `eda-digital-fullstack` | **ORFS** commit `902652c1` (2024-12-15) with **OpenROAD** `f7f634f886` AND **Yosys** `0.47` (`647d61dd9`) BOTH source-built from the ORFS-pinned submodules (the matched pair — a mismatched Yosys mis-synthesizes ASAP7), **KLayout 0.30.9** (klayout.de `.deb`; apt's 0.26.2 segfaults on the ASAP7 GDS merge), **riscv32 GNU** `2026.06.06`, **Spike** (riscv-isa-sim master), CoreMark + riscv-tests | **ASAP7** (default) PDK |
| `cad-fullstack` | `sim-benchmark-base` | **CadQuery 2.7.0** (OpenCascade) | gmsh 4.8.4 |
| `robotics-sim-fullstack` | `sim-benchmark-base` | **MuJoCo 3.9.0** | — |
| `combustion-fullstack` | `python:3.12-slim-bookworm` | **Cantera 3.2.0** (reaction networks, 0-D reactors, 1-D flames) | mechanisms ship inside the wheel: GRI-Mech 3.0, H2/O2 submech, Alzueta 2023 NH3/CO/H2, Reitz n-dodecane, NUIG 2015 n-hexane (1268 species) |
| `battery-fullstack` | `python:3.12-slim-bookworm` | **PyBaMM 26.7.1.0** (DFN / SPMe / SPM, lumped thermal, SEI + plating degradation; default CasADi solver) | parameter sets ship inside the wheel: Chen2020, Marquis2019, Ecker2015, Prada2013, Mohtat2020, OKane2022, ORegan2022, NCA_Kim2011, Ai2020 |

Cross-domain composed images (union of the two domains' toolchains):

| cross image (`:latest`) | toolchain |
|---|---|
| `cad-fem-fullstack` | CadQuery 2.7.0 + CalculiX 2.17 + gmsh 4.8.4 |
| `cad-cfd-fullstack` | CadQuery 2.7.0 + OpenFOAM ESI v2412 |
| `eda-mixed-signal-fullstack` | ngspice 36 + Icarus Verilog 14.0 |

(Commercial multi-physics suites COMSOL / Simulink are Path-B, not images here.)

## Bumping a toolchain version (the only way it changes)

A version bump is a deliberate, reviewed environment-layer event — never a
silent `:latest` rebuild:

1. Edit `environment/domains/<d>/{Dockerfile,tools.sh}` (new base tag / pinned
   apt/pip version).
2. Rebuild: `environment/domains/build.sh <d>`.
3. **Re-run that domain's oracles** (`solution/solve.sh` for every case on the
   image) and confirm each GT still holds within tolerance — or re-calibrate
   `kpis.json` and bump `oracle_provenance.<solver>_version`.
4. Update the row in this manifest + the verified-date.
5. Commit env + cases + manifest together. That commit is the new version.

This is exactly the discipline that the 2026-06-06 baked-verifier drift
violated (all images had silently fallen behind the verifier; the study gate
no-op'd on Harbor). Had this manifest existed with a recorded verifier sha, the
lag would have been visible.

## Dockerfile reproducibility (the foundation)

A tag is only as honest as its Dockerfile is deterministic. Pin where it
matters: base images by tag/digest (done — e.g. `openfoam-default:2412`); the
`apt`/`pip` layers (gmsh, numpy, sim-cli-core, the verifier) should pin
versions so re-building a commit's Dockerfile yields the same toolchain.
**Known gap to close**: several `tools.sh` `apt`/`pip` lines are unpinned and
can float on rebuild — pin them so a manifest row is guaranteed reproducible.

## Pending

- **Registry push** (`project_sim_benchmark_registry_pending`): once images are
  pushed, replace `:latest` with immutable `:<version>` tags in one env-layer
  pass; cases still reference by name.
- **`openfoam/` → `cfd/` — DONE 2026-06-07.** 8 modern neutral-v0.3
  cases migrated to `cases/cfd/fluids/` (repointed to
  `cfd-fullstack`, `solver` flipped `neutral`→`openfoam` to activate
  the artifact anti-cheat, oracle artifacts land under `/tmp/agent/case`, base
  overlay dropped); 2 superseded dash-duplicates deleted; 9 legacy v1-schema
  cases archived to `cases/_pending/openfoam-legacy/` (revive-on-upgrade).
  **GT re-validated 2026-06-07** — all 8 oracles re-run on
  `sim-benchmark-cfd-fullstack:latest` (OpenFOAM ESI v2412) with the
  activated openfoam artifact anti-cheat: **8/8 pass, all solver_evidence=True**
  (7× score 1.0; flatplate 0.9973, the ~0.27% cf decay quantifying the
  v2412-vs-CFL3D/FUN3D cross-code spread → version-robust). Each case's
  `kpis.json` carries a `revalidation_2026_06_07` stamp;
  `tools/rserver_oracle_cfd.sh` reproduces the run. (Note: the naca0012
  alpha-sweep container needs `PER_CASE_TIMEOUT` > 1h — it scored 1.0 but hit
  the cap at teardown after solve+score completed.) **`cfd-foundation`**: the lone Foundation
  `foamRun` case (`cavity-re100-foundation-v11`, now archived) would need either
  a port to a classic ESI solver or a separate `cfd-foundation-fullstack`
  image row above — defer until a real demand for Foundation-specific physics.
- **`tools.sh` version pins**: close the Dockerfile-reproducibility gap above.
