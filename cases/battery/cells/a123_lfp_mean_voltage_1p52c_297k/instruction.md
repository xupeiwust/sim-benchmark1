# Rate capability of a lithium-iron-phosphate / graphite cylindrical cell

Determine how much of a lithium-ion cell's deliverable capacity is lost when it is discharged faster.

## Cell and operating point

| quantity | value |
|---|---|
| cell | a lithium-iron-phosphate / graphite cylindrical cell |
| parameter set | `Prada2013` |
| initial state of charge | 100% |
| ambient temperature | 297.15 K |


## Protocol

Simulate two constant-current discharges from a full charge, the first at 0.5C and the second at 1.52C, each stopped when the terminal voltage first reaches 2.0 V, with a constant-current constant-voltage recharge to 3.6 V between them.

Model the cell with a physics-based electrochemical model — one that resolves
lithium transport in the electrolyte and in the active-material particles, so
that the rate dependence of the delivered capacity comes out of the transport
solution rather than out of a fitted resistance.

Both discharges and the recharge between them belong to **one run**, written to
one output file, so the second discharge starts from the state the recharge
left the cell in. Resolve the discretisation well enough that the reported
number is grid-converged.

Resolve each electrode **through its thickness**, so that reaction rate,
potential and lithium concentration vary across the electrode rather than only
within a single representative particle. (Collapsing each electrode onto one
representative particle answers a slightly different question, so this choice
is part of the specification.)

Report the **rate capacity loss in per cent — the charge delivered by the first (lower-rate) discharge minus the charge delivered by the second (higher-rate) one, divided by the first**.

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
