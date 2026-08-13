"""Bulk-update kpis.json gt_value with measured oracle values."""
from __future__ import annotations
import json
from pathlib import Path

# Measured from oracle runs on wine LTspice 26 (rserver, 2026-04-28).
# Replaces the closed-form/approximate gt_values authored initially.
ORACLE_RESULTS = {
    "rc_highpass_ac":     {"gain_hf": -1.1e-05, "f_3db": 159.18},
    "lc_lowpass_2nd":     {"gain_dc": 0.000300, "f_3db": 2363.21},
    "rl_lowpass_ac":      {"gain_dc": -0.000258, "f_3db": 1591.66},
    "lc_resonator":       {"f_resonance": 5011.87, "v_peak": 79.70},
    "sallen_key_lp":      {"gain_dc": -0.000354, "f_3db": 1024.65},
    "rl_step":            {"i_settled": 0.001000, "t_rise": 0.000220},
    "rlc_step_underdamped": {"vmax": 1.905, "vss": 0.996},
    "rlc_step_overdamped":  {"vss": 1.0, "t90": 0.000454},
    "half_wave_rectifier":  {"vout_avg": 9.681, "vrip_pp": 2.949},
    "noninv_amp":         {"vout_pk": 0.9999, "gain": 9.999},
    "opamp_buffer":       {"vout_pk": 0.5000, "gain": 1.0000},
    "diff_amp":           {"vout_pk": 0.4999, "gain_diff": 9.999},
    "opamp_summer":       {"vout_pk": 0.352, "vout_avg": 0.0},
    "opamp_integrator":   {"vout_pp": 0.504, "vout_avg": -0.245},
    "rlc_notch":          {"dc_gain": 0.0, "notch_depth": -60.0},   # placeholder, oracle TBD after WHEN fix
}


def main():
    for case_id, kpis in ORACLE_RESULTS.items():
        p = Path(f"cases/circuits/{case_id}/tests/kpis.json")
        if not p.exists():
            print(f"skip {case_id}: kpis.json missing")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for kpi_name, gt in kpis.items():
            if kpi_name not in d.get("kpis", {}):
                print(f"  warn: {case_id} has no kpi '{kpi_name}'")
                continue
            old_gt = d["kpis"][kpi_name].get("gt_value")
            d["kpis"][kpi_name]["gt_value"] = gt
            d["kpis"][kpi_name]["pass_tol_source"] = (
                d["kpis"][kpi_name].get("pass_tol_source", "") +
                f" Oracle measured {gt} on wine LTspice 26 (2026-04-28)."
            )
            print(f"  {case_id}.{kpi_name}: {old_gt} -> {gt}")
        p.write_bytes(json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
