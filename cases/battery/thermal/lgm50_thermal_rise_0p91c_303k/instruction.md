# Discharge with cell heating of an NMC811 / graphite-silicon cell parameterised for thermal coupling

Determine how hot a lithium-ion cell gets when it is discharged at a fixed rate down to its cut-off voltage.

## Cell and operating point

| quantity | value |
|---|---|
| cell | an NMC811 / graphite-silicon cell parameterised for thermal coupling |
| parameter set | `ORegan2022` |
| initial state of charge | 100% |
| ambient temperature | 303.15 K |


## Protocol

Simulate a constant-current discharge at 0.91C from a full charge, stopped when the terminal voltage first reaches 2.5 V, with the cell free to heat up.

Model the cell with a physics-based electrochemical model coupled to a
**lumped** thermal model: a single cell-averaged temperature, driven by the
irreversible and reversible heat generated inside the cell and cooled to the
ambient through the cell's surface. A spatially resolved thermal model answers
a different question and is not what is asked for here. Resolve the
discretisation well enough that the reported number is grid-converged.

Report the cell-averaged temperature, not a surface or hot-spot value.

Represent each electrode by a **single representative particle**, while still
solving lithium transport in the electrolyte across the cell. (Resolving each
electrode through its thickness answers a slightly different question, so this
choice is part of the specification.)

Report the **peak temperature rise in kelvin — the maximum cell-averaged temperature reached, minus the temperature at the start**.

## What to produce

Work inside `/tmp/agent/submission/`. Three files are required:

1. **`run_case.py`** — a self-contained script that performs the calculation
   when run as `python run_case.py` from inside that directory. It must be
   re-runnable from a clean copy of the directory containing only your source
   files, and **it must finish within 600 seconds** — the evaluator
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
   - `current_A` — cell current in amperes, **positive when discharging**
   - `voltage_V` — terminal voltage in volts
   - `temperature_K` — cell-averaged temperature in kelvin
3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The parameter set named above ships with the installed PyBaMM distribution
and can be loaded by that exact string.
