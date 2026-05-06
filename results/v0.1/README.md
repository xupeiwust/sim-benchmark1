# v0.1 MVP Results

This directory contains the release-facing result artifacts for the v0.1 MVP gate. The public benchmark release ships 36 public runnable tasks; the scored MVP gate is the 20-task LTspice circuit suite.

## Summary

| Run | Agent/model | Scope | Completed | Mean score | Status |
|---|---|---|---:|---:|---|
| `release-v0.1-ltspice20-oracle-20260503` | oracle | LTspice 20 MVP scored gate | 20/20 | 1.000 | passed |
| `release-v0.1-openfoam3-oracle-20260503` | oracle | OpenFOAM 3 oracle-available attempt | 0/3 | n/a | environment image unavailable |

OpenFOAM remains in the public catalog, but its base image/oracle packaging is not part of the v0.1 MVP scored gate.

## Files

- `summary.json`: machine-readable release summary.
- `ltspice20-oracle-20260503.csv`: per-case score table for the MVP gate.
- `ltspice20-oracle-20260503.json`: per-case score details, KPI values, and provenance verification diagnostics.

## LTspice 20 Per-Case Scores

| Case | Tier | Leakage | Score | Source verified |
|---|---|---:|---:|---|
| `bridge_rectifier_ripple` | M | 1 | 1.000 | 4/4 |
| `diff_amp` | M | 2 | 1.000 | 3/3 |
| `half_wave_rectifier` | S | 2 | 1.000 | 3/3 |
| `inv_amp` | M | 3 | 1.000 | 3/3 |
| `lc_lowpass_2nd` | M | 2 | 1.000 | 3/3 |
| `lc_resonator` | M | 2 | 1.000 | 3/3 |
| `noninv_amp` | M | 3 | 1.000 | 3/3 |
| `opamp_buffer` | S | 3 | 1.000 | 3/3 |
| `opamp_integrator` | M | 2 | 1.000 | 3/3 |
| `opamp_summer` | M | 2 | 1.000 | 3/3 |
| `rc_highpass_ac` | S | 3 | 1.000 | 3/3 |
| `rc_lowpass_ac` | M | 1 | 1.000 | 5/5 |
| `rc_pulse_response` | S | 3 | 1.000 | 3/3 |
| `rl_lowpass_ac` | S | 3 | 1.000 | 3/3 |
| `rl_step` | S | 3 | 1.000 | 3/3 |
| `rlc_bandpass` | S | 2 | 1.000 | 3/3 |
| `rlc_notch` | M | 1 | 1.000 | 4/4 |
| `rlc_step_overdamped` | M | 2 | 1.000 | 3/3 |
| `rlc_step_underdamped` | M | 2 | 1.000 | 3/3 |
| `sallen_key_lp` | M | 2 | 1.000 | 3/3 |

## Reproduction

```powershell
$env:DOCKER_HOST='npipe:////./pipe/docker_engine'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
harbor run -p cases/circuits --agent oracle --job-name release-v0.1-ltspice20-oracle -o jobs -n 4 --no-delete --force-build -y -q
```
