# Task — a flame-speed setup that does not meet the resolution requirement

`run_case.py` in your working directory computes the laminar burning velocity
of a premixed methane/air flame. It runs to completion without error, the
solver reports success, and it writes a results file and a figure.

**It does not meet the requirement stated under "The requirement" below.**
Bring it up to that requirement and report the burning velocity that comes out
of the setup that does.

## The operating point

| quantity | value |
|---|---|
| fuel | methane (CH4 in the mechanism) |
| oxidizer | air, modelled as O2 : N2 = 1 : 3.76 by mole |
| equivalence ratio | 1.07 |
| unburned-gas temperature | 312 K |
| pressure | 1.2 atm |
| reaction mechanism | `gri30.yaml` |

The flame is **freely propagating, one-dimensional, adiabatic and premixed**:
a planar flame stabilised in a uniform incoming stream of the unburned gas at
the stated temperature and pressure. The reported quantity is the
**unstretched laminar burning velocity**, i.e. the velocity of the unburned
mixture entering the flame. Use the **mixture-averaged** transport model (a
multicomponent treatment gives a slightly different answer, so this choice is
part of the specification).

None of the above may be changed to move the answer — the operating point,
the fuel, the oxidizer composition, the mechanism and the transport model are
what is being asked about. Everything else about how the calculation is set up
and resolved is yours to choose.

## The requirement

The burning velocity you report has to have **stopped moving under further
resolution**, and you have to show that from your own runs rather than assert
it. Concretely, the table you submit must satisfy all four of these:

1. it holds **at least 3 rows**, each at a different resolution;
2. the finest row resolves the flame with **at least twice** as many grid
   points as the coarsest row;
3. **each of the last two refinement steps** changes the burning velocity by
   **no more than 2%** — one small step is not enough, because a value can
   stop moving for a single step without having converged;
4. the burning velocity you report agrees with the **finest** row of the table
   to within **2%** — the table has to be about the run you are reporting.

Nothing here says which setting to change to satisfy it, and that is
deliberate: how you resolve the flame is one of the free choices above.

## What to produce

Work inside `/tmp/agent/submission/`. Four files are required:

1. **`run_case.py`** — a self-contained script that performs the whole
   calculation, including every row of the table, when run as
   `python run_case.py` from inside that directory. It must be re-runnable
   from a clean copy of the directory containing only your source files, and
   **it must finish within 900 seconds** — the evaluator re-runs it under
   exactly that limit, and a run that overruns is scored zero however good the
   physics. How much refinement you can afford is therefore part of the
   problem; this is stated so it is a constraint you can design against rather
   than one you discover afterwards.

   You may leave scratch directories behind — the evaluator copies only source
   files into a clean working copy and strips every numeric artifact before
   re-running, so nothing you leave can affect the score. There is no need to
   delete anything, and no need to run the driver a second time in place after
   verifying it elsewhere.

2. **`results.csv`** — the raw numerical output of the run you are reporting,
   written by `run_case.py`, with a header row and these columns:
   - `grid_m` — position across the flame in metres
   - `T_K` — temperature in kelvin
   - `velocity_m_s` — axial velocity in metres per second

   Write every column at full numerical precision — do not round the values or
   format them to a fixed number of decimal places — and place the rows closely
   enough together that the quantity asked for above is resolved by the file
   itself. The reported result is read off this file and nothing else, so it
   can be no sharper than the spacing between the rows that determine it. For a
   speed read at the unburned edge of the profile, those are the rows nearest
   that edge.

3. **`grid_independence.csv`** — the table the requirement above is judged on,
   also written by `run_case.py`, with a header row and these columns:
   - `n_grid_points` — how many grid points that solution ended up with
   - `flame_speed_cm_s` — the burning velocity from that solution, in
     centimetres per second

   One row per resolution, in any order. `n_grid_points` is an outcome of the
   run, not a setting you are asked to declare: whatever you did to resolve the
   flame more finely, report the grid the solver actually ended on.

4. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

Run the script yourself and leave its output in that directory. The evaluator
also re-runs `run_case.py` from a clean copy and takes both files from *its*
own run, so nothing is gained by hand-editing either of them.

## Environment

The mechanism named above ships with the installed Cantera distribution and can
be loaded by that exact string. Python 3, Cantera, NumPy and Matplotlib are
installed.

## Analytical-shortcut notice

There is no closed form for a laminar burning velocity — it depends on the full
kinetic mechanism, the transport model and the flame structure, so it can only
come from a solve. Nor is there one for the answer to the requirement above:
where a solution of *this* mixture stops moving under refinement is a property
of this mixture that has to be measured, and a recalled number cannot supply
the table that demonstrates it.
