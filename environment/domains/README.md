# environment/domains — per-domain fullstack images

One image per **engineering work domain**, not per tool. A CFD engineer
lives in OpenFOAM + Gmsh + ParaView + Python all day; those constitute one
indivisible "mental unit" and therefore one image. This replaces the old
per-tool image sprawl (`verilator-base` → `verilator-runner`, etc.) which
grew O(N) with tools and couldn't express multi-tool tasks (e.g. an EDA
RTL→GDS chain needs 6 tools at once).

See `docs/benchmark_methodology.zh.md` §4 for the rationale.

## The images

| image | OS root | core toolchain | covers |
|---|---|---|---|
| `eda-digital-fullstack` | ubuntu:22.04 | oss-cad-suite (Yosys+Verilator+Icarus+nextpnr+GTKWave) + cocotb | RTL design / synthesis / simulation / verification |
| `eda-digital-asic-fullstack` | FROM eda-digital | + OpenROAD + ORFS/**ASAP7** + KLayout + Spike + riscv-gnu + CoreMark | full RTL→GDSII: PPA (Fmax/area/power) + signoff (WNS≥0, DRC=0) + RISC-V CPU |
| `eda-analog-fullstack` | ubuntu:22.04 | ngspice + KiCad CLI + PySpice + scikit-rf | analog / PCB / filters / power |
| `cfd-fullstack` | opencfd/openfoam-default:2412 | OpenFOAM + Gmsh + meshio + pyvista (+SU2 opt) | industrial CFD full flow |
| `fem-fullstack` | ubuntu:22.04 | CalculiX + scikit-fem + OpenSeesPy + FiPy + Gmsh (Elmer/code_aster/sfepy opt) | structural / thermal / modal FEM |
| `cad-fullstack` | ubuntu:22.04 | FreeCAD + CadQuery + OpenCascade + Gmsh + trimesh | parametric modeling / assembly / geometry |
| `robotics-sim-fullstack` | osrf/ros:humble-desktop | ROS2 + Gazebo + MuJoCo | robot sim / control / perception |
| `combustion-fullstack` | python:3.12-slim | Cantera (+ numpy/scipy/matplotlib) | chemical kinetics / ignition / laminar flames |
| `battery-fullstack` | python:3.12-slim | PyBaMM (+ numpy/scipy/pandas/matplotlib) | lithium-ion cell electrochemistry / rate performance / thermal / ageing |

These images are open-source only. License-locked **commercial** solvers
(COMSOL / Fluent / Cadence) stay on Path B (Windows-native, not Docker —
see below). Note LTspice is **free but Windows-only** — that's a *substrate*
issue, not a license one; see the next section.

## Execution substrate (Linux / wine / Windows) — orthogonal to domain

A domain says *what tools*; the **substrate** says *what OS they run on*.
These are independent axes. The 6 images above all chose the **Linux-native**
substrate, but that's not the only one:

| substrate | for tools that are… | how | examples |
|---|---|---|---|
| **Linux-native** | apt/pip/tarball-installable on Linux | the default 6 images | yosys, verilator, ngspice, OpenFOAM, CalculiX, FreeCAD, ROS, MuJoCo |
| **Linux + wine** | **free but Windows-only**, and wine-compatible | `FROM sim-benchmark-wine-base` (ubuntu + wine, harness baked) + the domain's Linux tools.sh on top | **LTspice** |
| **Windows-native (Path B)** | need *real* Windows (GUI coupling / license / won't wine) | local Windows trial runner — **not Docker, not Harbor** | COMSOL, Fluent, Mechanical |

Key points:

- The common harness (`_common/install_harness.sh`) is Debian/Ubuntu-apt
  based, so it works unchanged on the **wine** substrate too (wine-base is
  ubuntu:22.04 + wine). A wine-rooted domain image is therefore the same
  pattern, just a different `FROM`.
- This axis mainly bites **eda-analog**: ngspice is Linux-native but LTspice
  is Windows-only-via-wine. So eda-analog ships **two substrate variants**
  (see `eda-analog/README.md`):
  - `eda-analog-fullstack` — Linux-native, light (ngspice + Python RF). Default.
  - `eda-analog-wine-fullstack` — `FROM wine-base`, the **full** analog domain:
    LTspice (wine) **and** ngspice (Linux) in one image. Build with
    `build.sh eda-analog --wine`.
- The other five domains are Linux-clean (no Windows-only open-source tool
  in their core), so they need no wine variant today. If a future domain
  pulls in a Windows-only-but-wine-able tool, give it a `Dockerfile.wine`
  the same way.
- **Path B is deliberately outside this Docker scheme** — license-locked
  commercial solvers don't containerize cleanly and aren't on Harbor
  (the COMSOL track is private Path B for exactly this reason).

## Anatomy of a domain dir

```
environment/domains/<domain>/
├── Dockerfile     # FROM <os-root> + tools.sh block + common-harness block
├── tools.sh       # THE TOOLCHAIN — this is the extension interface (see below)
└── README.md      # what's in it, what's optional, how to verify
```

The Dockerfile is ~identical across domains: it differs only in the `FROM`
line and the `COPY .../tools.sh` line. Everything domain-specific lives in
`tools.sh`. Everything shared lives in `environment/_common/install_harness.sh`.

## ★ Extension interface — how to add a tool

**Adding a tool to an existing domain:** edit that domain's `tools.sh`.
Each `tools.sh` has two clearly delimited sections:

```bash
# ===================== CORE (reliable; always built) =====================
#   apt / tarball installs that build deterministically on a clean host.

# ===================== OPTIONAL (heavy/finicky; opt-in) ==================
#   Commented blocks with install instructions. Uncomment + rebuild to
#   enable. Kept out of CORE because they're large, slow, or fragile
#   (need GPU, build from source, ppa flakiness, etc.).
```

Add to CORE if the install is a clean apt/pip/tarball; add to OPTIONAL
(commented, with a one-line "why optional") otherwise. Rebuild the one
image; no other domain is affected.

**Adding a whole new domain:** copy any `<domain>/` dir, swap the `FROM`
line + `tools.sh` toolchain, add a row to the table above, and to
`build.sh`'s `KNOWN` list. The common harness wires itself in
automatically.

## Build

```bash
# from repo root (build context must be repo root for the COPY paths)
environment/domains/build.sh eda-digital                 # CN mirrors (default)
environment/domains/build.sh eda-digital --intl          # international mirrors
environment/domains/build.sh eda-digital --sim-cli-ref <sha>   # pin sim-cli
environment/domains/build.sh all                         # build every domain (heavy!)
```

Images are tagged `sim-benchmark-<domain>-fullstack:latest`.

## Build cost note

These images are large (3–10 GB each; robotics-sim with ROS desktop is the
heaviest). On a disk-constrained host build only the domains you need.
`cfd` reuses the ~2.5 GB OpenFOAM layer already on most hosts.

## Two layers: domain base + per-task overlay

The 6 domain images are **not** a fixed menu that must contain every tool a
task could want. The real environment is task-dependent — but the resolution
is **not** "build each task from scratch" (that's the per-tool sprawl we
removed). It's two layers:

```
sim-benchmark-<domain>-fullstack       ← LAYER 1: pre-built, pulled.
        ▲  FROM                           Heavy + amortized: substrate +
        │                                 harness + CORE domain toolchain.
cases/<...>/environment/Dockerfile      ← LAYER 2: per-task overlay.
                                          Thin: FROM the domain image +
                                          the one extra tool / fixture this
                                          task needs. Builds in seconds
                                          because the domain layer is cached.
```

- **Most tasks** use the domain image as-is — zero extra build (e.g. the
  `pwm_generator_8bit` case: CORE `verilator` is enough, no overlay).
- **A task needing an OPTIONAL tool** (OpenROAD, KiCad, Elmer, SU2, …) ships
  a thin `environment/Dockerfile`: `FROM sim-benchmark-<domain>-fullstack` +
  `RUN <install that one tool>`. Seconds, not minutes — only the extra tool
  builds; the domain base is a cached pull.

This is exactly the Harbor task contract (each task has an
`environment/Dockerfile` that's `FROM <base>` + task setup) — the existing
OpenFOAM/LTspice cases already do `FROM base` + case assets. The domain
images just upgrade that `base` from "one solver" to "the domain's full
toolchain".

### CORE / OPTIONAL maps onto the two layers

- **CORE** (in `tools.sh`) → baked into the domain image (Layer 1). Tools
  ~every task in the domain uses.
- **OPTIONAL** (commented in `tools.sh`) → a snippet a task's overlay pulls
  in (Layer 2). Niche tools.
- **Frequency promotes OPTIONAL → CORE**: if many tasks start needing an
  OPTIONAL tool, move it to CORE and rebuild the domain image once
  (re-amortized) — same "frequency is a signal" rule as cross-domain combos.

### Worked overlay sample

`cases/eda-digital/digital_logic/gcd_rtl2gds_timing/environment/Dockerfile`
is a real per-task overlay: `FROM sim-benchmark-eda-digital-fullstack` +
OpenROAD (the OPTIONAL tool that case needs for RTL→GDS). Derived from
demand record `docs/demand_sources/records/demand-eda-openroad-timing-001.yaml`.

## Cross-domain tasks

Some tasks span two domains — geometry→FEM (CAD+FEM), fluid-structure
interaction (CFD+FEM), mixed-signal co-sim (EDA digital+analog), electro-
thermal (EDA+FEM). The per-domain split is an optimization for the common
case (most tasks live in one domain); it does **not** block cross-domain
work, because each `tools.sh` is a standalone install script — composing
two is just running both.

### Composition pattern

A cross-domain image picks **one OS root** and runs **both** domains'
`tools.sh`, then the common harness once. Worked samples live in
[`_cross/`](_cross/):

- `cad-fem` — two ubuntu-rooted domains,叠 directly
- `cad-cfd` — different roots → pick the harder-to-relocate one (OpenFOAM)
  and run the other's tools.sh on top
- `eda-mixed-signal` — eda-digital + eda-analog (digital RTL + analog SPICE
  co-sim); same ubuntu root, identical mechanics to cad-fem. The runtime
  co-sim bridge is a case-level concern, not an image one.

```bash
environment/domains/build.sh cad-fem    # build.sh discovers _cross/<name>/
environment/domains/build.sh cad-cfd
environment/domains/build.sh eda-mixed-signal
```

### Decision rule — rebuild every time?

No. It depends on **frequency × conflict**:

| situation | approach | rebuilt each time? |
|---|---|---|
| **recurring** combo | it's really a new domain → promote to a named `<name>/` image, build + push **once**, pull like the 6 | no — pull |
| **one-off** combo | compose at build (`_cross/<combo>/`, ~5–15 min) | yes, but see below |
| toolchains **genuinely conflict** (python / syslib version clash) | per-tool venv isolation, or two containers sharing a volume | n/a |

So the 6 base domains and any *recurring* combo are build-once → registry →
`docker pull`. Only **genuine one-offs** pay a fresh build, and even that is
cheapened two ways:

- **`COPY --from`** for tarball-style tools installed under `/opt` (e.g.
  oss-cad-suite): `COPY --from=sim-benchmark-eda-digital-fullstack:latest
  /opt/oss-cad-suite /opt/oss-cad-suite` — skips the 678 MB re-download.
  (apt-scattered packages across /usr·/etc·/var aren't relocatable this
  way; only /opt-contained tools are.)
- **layer cache**: on a host that already built the constituent domains,
  the apt/pip layers hit cache.

> Note: registry push isn't set up yet — currently even the 6 base images
> are rebuilt from Dockerfile rather than pulled. Standing up a registry
> (so build-once-pull-many actually holds) is a separate, tracked task.

### Frequency is a signal — and it's a separate axis from sampling

"Lives in `_cross/`" and "promoted to a named domain" are **independent**:
a combo is a `_cross/` sample because its two `tools.sh` compose cleanly;
it gets *promoted* only when it **recurs**. Any sample can be promoted
later. `eda-mixed-signal` is the strongest promote candidate (mixed-signal
co-sim is common); `electro-thermal` (EDA→FEM) and `fsi` (CFD+FEM) are
further candidates not yet sampled. See [`_cross/README.md`](_cross/README.md).
