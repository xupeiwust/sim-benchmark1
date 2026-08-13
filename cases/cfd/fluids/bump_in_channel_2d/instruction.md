# Task — NASA 2D bump-in-channel, turbulent drag

Compute the drag on a smooth bump in a channel and report its coefficient.

## The mesh is supplied

`constant/polyMesh/` is already in your working directory. It is NASA's own
grid for this case (14,080 cells, wall-resolved). **Use it as it is** — do not
regenerate, refine or coarsen it. The expected answer corresponds to this mesh.

## Geometry

Flat plate along the lower boundary over `0 ≤ x ≤ 1.5`, carrying a smooth bump

```
z(x) = 0.05 · sin⁴( πx/0.9 − π/3 )        for 0.3 ≤ x ≤ 1.2
z(x) = 0                                   elsewhere on the plate
```

Upstream of `x = 0` and downstream of `x = 1.5` the lower boundary is a slip
(symmetry) surface, so the boundary layer starts at the plate leading edge. The
domain runs from `x = −25` to `x = 26.5`, with a symmetry ceiling at `z = 5`.
The mesh is one cell deep; the spanwise planes are `empty`.

Patches, as named in the supplied mesh: `inlet`, `outlet`, `top`, `wall`
(the no-slip plate), `symLower`, `frontBack`.

## Flow conditions

| quantity | value |
|---|---|
| free-stream velocity | 1 (non-dimensional) |
| reference length | 1 |
| Reynolds number | 3 × 10⁶ |
| kinematic viscosity | 3.3333333 × 10⁻⁷ |
| turbulence model | **k-omega SST** |
| free-stream turbulence intensity | 0.077 % |
| free-stream eddy-viscosity ratio | 0.009 |

Treat the flow as incompressible and steady.

The turbulence model is part of the specification, not a choice — a different
closure gives a different answer.

## What to report

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, builds the mesh, solves, and
   writes `results.csv`. It must return non-zero on failure and **must finish
   within 2400 seconds** — the evaluator re-runs it under exactly that limit
   from a clean copy, and a run that overruns is scored zero however good the
   physics.

   You may leave the mesh, time directories and logs behind. The evaluator
   strips every generated artefact — including `results.csv` itself — before
   re-running, so nothing you leave can affect the score.

2. **`results.csv`** — written by `Allrun` into the submission root, with a
   header row and one data row:

   | column | meaning |
   |---|---|
   | `cd_total` | total drag coefficient on the bump |

   The format, with placeholders that are not the answer:

   ```
   cd_total
   1.0
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` in the submission
   root, as for any reproducible case.

## Environment

OpenFOAM is installed; source its environment before use. Any solver on the
machine is acceptable — how you drive it is your business.
