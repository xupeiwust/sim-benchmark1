# Largest constant charge current a cell can take without overheating

A pack designer has to choose the constant-current stage of a fast-charge
profile. Push more current and the charge finishes sooner; push too much and
the cell exceeds the temperature its warranty is written against. Find where
that boundary sits.

## Cell and operating point

| quantity | value |
|---|---|
| cell | a nickel-manganese-cobalt / graphite cylindrical cell |
| parameter set | `Chen2020` |
| initial state of charge | 20% |
| ambient temperature | 298.15 K |

## The charge protocol

Charge at a **constant current** until the terminal voltage reaches **4.2 V**,
then **hold 4.2 V** until the current falls to **250 mA**.

Model the cell with a physics-based electrochemical model — one that resolves
lithium transport in the electrolyte and in the active-material particles, so
that the heat generation comes out of the transport solution rather than out of
a fitted resistance. Represent each electrode by a **single representative
particle**, while still solving lithium transport in the electrolyte across the
cell.

Couple it to a **lumped thermal model** — one temperature for the whole cell,
heated by the electrochemical losses and cooled to ambient. The temperature
this case is written about is that **volume-averaged cell temperature**.

Resolve the discretisation well enough that the reported numbers are
grid-converged.

## The requirement, and what to report

**The volume-averaged cell temperature must not exceed 318.15 K at any point
during the charge.**

The charger in this design can deliver a constant current anywhere between
**1.0 A and 10.0 A**; outside that range is not a design option, so the answer
lies inside it.

Report:

1. **`i_charge_max_a`** — the largest constant current, in amperes, for which
   the whole protocol above stays within the temperature requirement.
2. **`charge_time_at_limit_s`** — the total duration of the charge, in seconds,
   when it is run at that current: from the start of the constant-current stage
   to the moment the current falls to 250 mA.

Report the current to a resolution fine enough that a further refinement of
your search would not move it by more than a few parts in a thousand. (For
scale, and as a formatting example only: a value like `0.5` would be far below
anything this charger can deliver, and `40` far above it.)

## What to produce

Work inside `/tmp/agent/submission/`. Three files are required:

1. **`run_case.py`** — a self-contained script that performs the whole
   calculation, **including the search**, when run as `python run_case.py` from
   inside that directory. It must be re-runnable from a clean copy of the
   directory containing only your source files, and **it must finish within 900
   seconds** — the evaluator re-runs it under exactly that limit, and a run that
   overruns is scored zero however good the physics. How much refinement you can
   afford is therefore part of the problem; this is stated so it is a constraint
   you can design against rather than one you discover afterwards.

   Note what this means for how the answer is produced: the evaluator strips
   every numeric artifact — `results.csv` included — and re-runs this script, so
   a current written into the file by hand reproduces nothing. The script has to
   find it.

   You may leave scratch directories behind — the evaluator copies only source
   files into a clean working copy, so nothing you leave can affect the score.

2. **`results.csv`** — the raw numerical output, written by `run_case.py`, of
   the charge **run at the current you report**, with a header row and these
   columns:
   - `time_s` — time in seconds, increasing from 0
   - `current_A` — cell current in amperes, **positive when discharging** (so a
     charge is negative)
   - `voltage_V` — terminal voltage in volts
   - `temperature_K` — volume-averaged cell temperature in kelvin
   - `i_charge_max_a` — the current you are reporting, repeated on every row

3. **a figure** — an image file (`.png` is fine) plotting your result, of the
   kind you would put in a report.

## Environment

The parameter set named above ships with the installed PyBaMM distribution and
can be loaded by that exact string.
