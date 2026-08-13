# Cycle ageing of an NMC811 / graphite-silicon cell parameterised for degradation

Determine how much capacity a lithium-ion cell loses over a run of full cycles once its ageing mechanisms are active.

## Cell and operating point

| quantity | value |
|---|---|
| cell | an NMC811 / graphite-silicon cell parameterised for degradation |
| parameter set | `OKane2022` |
| initial state of charge | 100% |
| ambient temperature | 298.15 K |
| degradation mechanisms | SEI: solvent-diffusion limited |

## Protocol

Simulate twelve consecutive cycles, each a 1C discharge to 2.5 V followed by a 1C charge to 4.2 V and a constant-voltage hold at 4.2 V until the current falls to 50 mA, with solid-electrolyte-interphase growth active so the cell ages as it cycles.

Model the cell with a physics-based electrochemical model that includes the
degradation mechanisms named above, so that the capacity the cell delivers
changes from cycle to cycle because lithium is being consumed, not because a
fade curve was imposed.

Measure the capacity of each cycle as the charge delivered during that cycle's
discharge phase, and report the loss from the first cycle to the last.

Represent each electrode by a **single representative particle**, while still
solving lithium transport in the electrolyte across the cell. (Resolving each
electrode through its thickness answers a slightly different question, so this
choice is part of the specification.)

Report the **capacity fade in percent — the last cycle's discharge capacity relative to the first cycle's, expressed as a percentage loss**.

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
   - `current_A` — cell current in amperes, **positive when discharging**
   - `voltage_V` — terminal voltage in volts
3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The parameter set named above ships with the installed PyBaMM distribution
and can be loaded by that exact string.
