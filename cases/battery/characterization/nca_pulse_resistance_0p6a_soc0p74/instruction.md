# Pulse resistance measurement of a nickel-cobalt-aluminium / graphite cell

Determine the resistance a lithium-ion cell presents to a short discharge pulse applied from rest.

## Cell and operating point

| quantity | value |
|---|---|
| cell | a nickel-cobalt-aluminium / graphite cell |
| parameter set | `NCA_Kim2011` |
| initial state of charge | 74% |
| ambient temperature | 298.15 K |


## Protocol

Simulate a 15 second, 0.6 A discharge pulse applied from rest at 74% state of charge, preceded by a 400 second rest and followed by a 600 second relaxation.

Model the cell with a physics-based electrochemical model that resolves
transport in the electrolyte and in the particles, so that the voltage step at
the start of the pulse is produced by the model rather than imposed.

The quantity asked for is the **instantaneous** pulse resistance: the voltage
step across the current step at the beginning of the pulse, divided by the
size of that current step. It is not the resistance inferred from the end of
the pulse, which also contains diffusion.

Represent each electrode by a **single representative particle**, while still
solving lithium transport in the electrolyte across the cell. (Resolving each
electrode through its thickness answers a slightly different question, so this
choice is part of the specification.)

Report the **pulse resistance in ohms**.

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
