# Spatial accuracy of a Navier–Stokes solver on the Kovasznay flow at Re = 40

Kovasznay's flow is a steady two-dimensional solution of the incompressible
Navier–Stokes equations for which a closed form is known, so the discretisation
error of a numerical solution can be measured exactly rather than estimated.
Your task is to measure it, and to demonstrate what order of spatial accuracy
your discretisation actually achieves.

## The problem

Steady, incompressible, laminar flow on the square domain
`0 <= x <= 1`, `-0.5 <= y <= 0.5`, treated as two-dimensional.

- `U_ref = 1`, `L = 1`, kinematic viscosity `nu = 0.025`, giving `Re = 40`.
- With `lam = Re/2 - sqrt(Re^2/4 + 4*pi^2)`, the exact solution is

  ```
  u(x,y) = 1 - exp(lam*x) * cos(2*pi*y)
  v(x,y) = (lam / (2*pi)) * exp(lam*x) * sin(2*pi*y)
  p(x,y) = (1 - exp(2*lam*x)) / 2          (up to an arbitrary gauge)
  ```

- Impose the exact `u` and `v` as Dirichlet conditions on all four sides of the
  domain. The interior is then determined, and the difference between your
  computed interior field and the exact one is discretisation error.

## What to measure

Solve the same problem on **three uniform grids of 20×20, 40×40 and 80×80
cells**, and for each report the grid-normalised L2 norm of the error in the
streamwise velocity over cell centres:

```
l2_error_u = sqrt( ( sum over cells of (u_computed - u_exact)^2 ) / n_cells )
```

with `u_exact` evaluated at the cell centre, and `h = 1 / n_cells_per_side`.

Two numbers are scored: the **observed order of accuracy**, the slope of
`log(l2_error_u)` against `log(h)` across the three grids, and the **error on
the finest grid**. A discretisation that is genuinely second-order in space will
show a slope near 2; one that is not, will not.

The observed order is a property of your discretisation rather than of the
operating point, so getting it right requires the scheme, the boundary treatment
and the convergence of each individual solve to be right together. In
particular, each solve has to be converged far enough that the remaining
iteration error is small compared with the discretisation error being measured —
otherwise the three numbers describe your stopping criterion instead of your
scheme.

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
   | `n_cells_per_side` | 20, 40 or 80 |
   | `h` | `1 / n_cells_per_side` |
   | `l2_error_u` | the norm defined above |

   The format, with placeholder numbers that are not the answer:

   ```
   n_cells_per_side,h,l2_error_u
   20,0.05,1.0
   40,0.025,0.5
   80,0.0125,0.25
   ```

3. The case inputs themselves: `0/`, `constant/` and `system/` must exist in the
   submission root, as for any reproducible case.

## Environment

OpenFOAM ESI v2412 is installed and its environment is available on the shell.
Python 3 with NumPy is available.

How you impose the analytical boundary condition, generate the meshes, choose
the discretisation and compute the norm is yours to decide.
