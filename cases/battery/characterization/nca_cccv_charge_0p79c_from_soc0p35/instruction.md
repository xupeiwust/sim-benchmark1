# Constant-current / constant-voltage charge of a nickel-cobalt-aluminium / graphite cell

Determine how long it takes to recharge a partially discharged lithium-ion cell on a constant-current / constant-voltage schedule.

## Cell and operating point

| quantity | value |
|---|---|
| cell | a nickel-cobalt-aluminium / graphite cell |
| parameter set | `NCA_Kim2011` |
| initial state of charge | 35% |
| ambient temperature | 298.15 K |


## Protocol

Simulate a constant-current charge at 0.79C from 35% state of charge up to 4.2 V, followed by a constant-voltage hold at 4.2 V until the current falls to 8 mA.

Model the cell with a physics-based electrochemical model that resolves
transport in the electrolyte and in the particles. The transition from the
constant-current phase to the constant-voltage hold must come out of the
simulation reaching the voltage limit, not out of a prescribed time.

Represent each electrode by a **single representative particle**, while still
solving lithium transport in the electrolyte across the cell. (Resolving each
electrode through its thickness answers a slightly different question, so this
choice is part of the specification.)

Report the **total charge time in seconds — from the start of the constant-current phase to the end of the constant-voltage hold**.

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
3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The parameter set named above ships with the installed PyBaMM distribution
and can be loaded by that exact string.
