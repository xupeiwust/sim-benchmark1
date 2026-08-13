# Spatial accuracy of a plane-channel solution — laminar 2D Poiseuille flow

Fully developed laminar flow between parallel plates has a closed-form velocity
profile, so the discretisation error of a numerical solution can be measured
exactly rather than estimated. Your task is to measure it, and to demonstrate
what order of spatial accuracy your discretisation actually achieves.

## The problem

Steady, incompressible, laminar flow in a straight two-dimensional channel.

- Channel full gap `D=1`, walls at `y=+-0.5`, length `30`; use a
  one-cell-thick 2D slab with `empty` spanwise faces.
- `nu=0.01`; steady incompressible laminar flow.
- Drive the flow with a fixed inlet-to-outlet kinematic-pressure difference;
  velocity is zero-gradient at inlet/outlet and no-slip at both plates.
  Size the pressure difference so the fully developed bulk mean velocity is
  close to 1, which keeps the channel Reynolds number well inside the laminar
  range.
- Far from the ends the flow is fully developed, and there the exact solution is

  ```
  u(y) = (3/2) * u_mean * (1 - (2*y/D)^2)
  v(y) = 0
  ```

  where `u_mean` is the bulk mean velocity of that same profile. The difference
  between your computed profile and this one is discretisation error.

## What to measure

Solve the same problem on **three uniform grids of 60x20, 120x40 and 240x80
cells** (streamwise x wall-normal), and for each report the error in the fully
developed velocity profile.

Take the station `x=20`, which is fully developed for this channel. At that
station let `u_j` be the streamwise velocity at the centre of each cell in the
wall-normal column and `y_j` the ordinate of that cell centre, for
`j = 1 ... n_y`, where `n_y` is 20, 40 or 80. Then:

- the bulk mean velocity of that column,

  ```
  u_mean = (1/D) * trapezoidal integral of u over y from -D/2 to +D/2
  ```

  taking `u = 0` at both walls, which no-slip makes exact;

- the grid-normalised L2 norm of the error in the **normalised** profile,

  ```
  l2_error = sqrt( ( sum over j of ( u_j/u_mean - (3/2)*(1 - (2*y_j/D)^2) )^2 ) / n_y )
  ```

- and the wall-normal spacing `h = D / n_y`.

The scored quantity is the **observed order of accuracy**: the slope of
`log(l2_error)` against `log(h)` across the three grids. A discretisation that
is genuinely second-order in space will show a slope near 2; one that is not,
will not.

The observed order is a property of your discretisation rather than of the
operating point, so getting it right requires the scheme, the boundary
treatment, the station being genuinely fully developed, and the convergence of
each individual solve to be right together. In particular, **each solve has to
be converged far enough that the remaining iteration error is small compared
with the discretisation error being measured** — otherwise the three numbers
describe your stopping criterion instead of your scheme. Stopping every grid at
the same fixed iteration count, without checking that, is the usual way to
produce a confident and wrong slope here.

## What to produce

Work inside `/tmp/agent/submission/`. Required:

1. **`Allrun`** — a non-interactive script that, from a clean copy of the
   directory containing only your source files, builds every mesh, runs every
   solve, computes the errors and writes `grid_convergence.csv`. It must return
   non-zero on failure and **must finish within 2400 seconds** — the evaluator
   re-runs it under exactly that limit from a clean copy, and a run that
   overruns is scored zero however good the physics.

   You may leave meshes, time directories and logs behind. The evaluator strips
   every generated artefact — including `grid_convergence.csv` itself — before
   re-running, so nothing you leave can affect the score and there is no need to
   clean up afterwards.

2. **`grid_convergence.csv`** — written by `Allrun` into the submission root,
   with a header row and exactly these columns, one row per grid:

   | column | meaning |
   |---|---|
   | `n_cells_wall_normal` | 20, 40 or 80 |
   | `h` | `D / n_cells_wall_normal` |
   | `l2_error` | the norm defined above; dimensionless |

   The format, with placeholder numbers that are not the answer:

   ```
   n_cells_wall_normal,h,l2_error
   20,0.05,1.0
   40,0.025,0.9
   80,0.0125,0.8
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` must exist in the
   submission root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 with NumPy is available. How you mesh, discretise, converge and extract
is yours to decide.
