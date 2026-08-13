# Ignition delay of methanol/air at 1583 K and 6.8 atm

Determine how long a premixed fuel/air mixture takes to autoignite after being brought instantaneously to the stated conditions.

## Conditions

| quantity | value |
|---|---|
| fuel | methanol (CH3OH in the mechanism) |
| oxidizer | air, modelled as O2 : N2 = 1 : 3.76 by mole |
| equivalence ratio | 0.66 |
| initial temperature | 1583 K |
| pressure | 6.8 atm |
| reaction mechanism | `gri30.yaml` |

Treat the mixture as a spatially uniform, **constant-volume, adiabatic**
system: it is a closed reactor of fixed volume with no heat loss, initially
at the stated temperature and pressure, whose composition then evolves under
the chemistry of the given mechanism.

Report the **ignition delay time**, defined as the time at which the rate of
temperature rise dT/dt reaches its maximum. Integrate past ignition until
dT/dt has fallen below 0.1% of the maximum value it reached, so the trace
covers the whole event and the relaxation after it.

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
   - `time_s` — time in seconds, increasing from 0
   - `T_K` — temperature in kelvin
   - `P_Pa` — pressure in pascal

   Write every column at full numerical precision — do not round the values
   or format them to a fixed number of decimal places — and place the rows
   closely enough together that the quantity asked for above is resolved by
   the file itself. The reported result is read off this file and nothing
   else, so it can be no sharper than the spacing between the rows that
   determine it.
   For a delay defined by the dT/dt maximum, those are the rows on either
   side of that maximum.

3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The mechanism named above ships with the installed Cantera distribution and
can be loaded by that exact string.
