# Laminar flame speed of hydrogen/air at phi=1.12, 1.2 atm

Determine how fast a premixed laminar flame propagates into this unburned fuel/air mixture.

## Conditions

| quantity | value |
|---|---|
| fuel | hydrogen (H2 in the mechanism) |
| oxidizer | air, modelled as O2 : N2 = 1 : 3.76 by mole |
| equivalence ratio | 1.12 |
| unburned-gas temperature | 312 K |
| pressure | 1.2 atm |
| reaction mechanism | `h2o2.yaml` |

Consider a **freely propagating, one-dimensional, adiabatic premixed laminar
flame** in this mixture: a planar flame stabilised in a uniform incoming
stream of the unburned gas at the stated temperature and pressure.

Report the **unstretched laminar flame speed**, i.e. the velocity of the
unburned mixture entering the flame. Use the **mixture-averaged** transport
model (a multicomponent treatment gives a slightly different answer, so this
choice is part of the specification). Resolve the flame well enough that the
reported speed is grid-converged.

## What to produce

Work inside `/tmp/agent/submission/`. Three files are required:

1. **`run_case.py`** — a self-contained script that performs the calculation
   when run as `python run_case.py` from inside that directory. It must be
   re-runnable from a clean copy of the directory containing only your source
   files, and **it must finish within 900 seconds** — the evaluator
   re-runs it under exactly that limit, and a run that overruns is scored
   zero however good the physics. How much refinement you can afford is
   therefore part of the problem; this is stated so it is a constraint you
   can design against rather than one you discover afterwards.

   You may leave scratch directories behind — the evaluator copies only
   source files into a clean working copy and strips every numeric artifact
   before re-running, so nothing you leave can affect the score. There is no
   need to delete anything, and no need to run the driver a second time in
   place after verifying it elsewhere.

2. **`results.csv`** — the raw numerical output of the run, written by
   `run_case.py`, with a header row and these columns:
   - `grid_m` — position across the flame in metres
   - `T_K` — temperature in kelvin
   - `velocity_m_s` — axial velocity in metres per second

   Write every column at full numerical precision — do not round the values
   or format them to a fixed number of decimal places — and place the rows
   closely enough together that the quantity asked for above is resolved by
   the file itself. The reported result is read off this file and nothing
   else, so it can be no sharper than the spacing between the rows that
   determine it.
   For a speed read at the unburned edge of the profile, those are the rows
   nearest that edge.

3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The mechanism named above ships with the installed Cantera distribution and
can be loaded by that exact string.
