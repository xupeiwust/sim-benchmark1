"""rescore.py — offline re-scorer using existing reward_detail.json data.

Most schema iterations don't need to re-run the LLM agent or the solver.
Tweaking pass_tol, physics_min/physics_max, or group weights only
needs the per-KPI **values** that the verifier already captured at trial
time. Those live in `<trial>/verifier/reward_detail.json` under
`kpi_detail.per_kpi.<name>.value`.

This tool reads frozen reward_detail.json + a new kpis.json spec, applies
the new physics_pass + band_pass + group weights to the existing values,
and writes a new reward.json (or prints to stdout). meta_score is carried
through unchanged.

Limitations:
- Cannot rescore KPIs that weren't scored at trial time (no value to
  rescore from). New KPIs added to the spec are flagged with
  `kpi_score: null` and `why: "needs full rescore — no historical value"`.
- Cannot re-verify provenance (source_verified is taken from the saved
  per_kpi entry — assumed still trusted).
- For the small set of changes that DO require re-extracting from
  workspace files (e.g., changing the `extract` pipeline of a KPI), use a
  full re-run; this lite tool will not save you.

Usage:
  python tools/rescore.py <trial_dir> --kpis <new-kpis.json>
  python tools/rescore.py <job_dir>   --kpis <new-kpis.json>      # all trials
  python tools/rescore.py <path>      --kpis <new-kpis.json> --print
  python tools/rescore.py <path>      --kpis <new-kpis.json> --diff
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the live verifier's formulae so rescore stays bit-identical to the
# original scorer when nothing is changed.
_LIB = Path(__file__).resolve().parents[1] / "lib" / "sim_benchmark_verifier"
sys.path.insert(0, str(_LIB))
from sim_benchmark_verifier.score import (  # noqa: E402
    W_META, W_KPI,
    _band_pass, _physics_pass, _validate_groups,
)


def _rescore_one_kpi(name: str, spec: dict, frozen: dict | None) -> dict:
    """Apply new spec to a previously-frozen per_kpi entry.

    `frozen` is the dict for this KPI from old reward_detail.kpi_detail.per_kpi
    (or None if the KPI wasn't scored at trial time — i.e., a new KPI added
    after the trial ran).
    """
    if frozen is None:
        return {
            "kpi_score":       None,
            "source_verified": None,
            "physics_pass":    None,
            "band_pass":       None,
            "why":             "needs full rescore — KPI absent from trial-time reward_detail",
        }

    source_verified = float(frozen.get("source_verified") or 0.0)
    value = frozen.get("value")

    # If trial-time provenance failed (source_verified=0), the KPI scored 0
    # then and still scores 0 now. We can't recover from that without a
    # full re-extract.
    if source_verified == 0.0 or value is None:
        return {
            "kpi_score":       0.0,
            "source_verified": source_verified,
            "physics_pass":    0.0,
            "band_pass":       0.0,
            "value":           value,
            "why":             frozen.get("why") or "trial-time source verification failed",
        }

    value = float(value)
    phys, phys_why = _physics_pass(spec, value)
    band = _band_pass(spec, value)
    score = source_verified * phys * band
    return {
        "value":           value,
        "kpi_score":       round(score, 4),
        "source_verified": source_verified,
        "physics_pass":    round(phys, 4),
        "physics_why":     phys_why,
        "band_pass":       round(band, 4),
        "extracted":       frozen.get("extracted"),
    }


def _rescore_groups(kpis_spec: dict, groups_spec: dict, frozen_per_kpi: dict) -> tuple[float, dict]:
    per_kpi: dict[str, dict] = {}
    for name, spec in kpis_spec.items():
        per_kpi[name] = _rescore_one_kpi(name, spec, frozen_per_kpi.get(name))

    per_group: dict[str, dict] = {}
    weighted_sum = 0.0
    for gname, gspec in groups_spec.items():
        weight = float(gspec["weight"])
        members = [n for n, s in kpis_spec.items() if s.get("group") == gname]
        if not members:
            per_group[gname] = {"weight": weight, "members": [], "group_score": 0.0,
                                "why": "no KPIs declared for this group"}
            continue
        # Treat null kpi_score (needs full rescore) as 0 for the group avg —
        # so adding a new KPI to the spec without re-running gets penalised
        # rather than silently boosting the group score.
        m_scores = [(per_kpi[n]["kpi_score"] or 0.0) for n in members]
        gscore = sum(m_scores) / len(m_scores)
        per_group[gname] = {
            "weight":      weight,
            "members":     members,
            "group_score": round(gscore, 4),
        }
        weighted_sum += weight * gscore
    return round(weighted_sum, 4), {"per_group": per_group, "per_kpi": per_kpi}


def rescore_trial(trial_dir: Path, new_kpis: dict) -> dict:
    """Return a new reward_detail-shaped dict for one trial."""
    rd_path = trial_dir / "verifier" / "reward_detail.json"
    if not rd_path.exists():
        return {"error": f"reward_detail.json not found at {rd_path}"}

    old = json.loads(rd_path.read_text(encoding="utf-8"))
    old_kpi_detail = old.get("kpi_detail", {}) or {}
    frozen_per_kpi = old_kpi_detail.get("per_kpi", {}) or {}

    kpis_spec = new_kpis.get("kpis", {}) or {}
    groups_spec = new_kpis.get("kpi_groups", {}) or {}

    spec_err = _validate_groups(groups_spec, kpis_spec)
    if spec_err:
        return {"error": f"new kpis.json invalid: {spec_err}"}

    # meta_score is carried through — we are not re-evaluating sim runs.
    meta_score = float(old.get("meta_score") or 0.0)
    meta_detail = old.get("meta_detail", {}) or {}

    new_kpi_score, new_kpi_detail = _rescore_groups(kpis_spec, groups_spec, frozen_per_kpi)
    final = round(W_META * meta_score + W_KPI * new_kpi_score, 4)

    return {
        "schema_version":  old.get("schema_version", "reward-v3"),
        "case_id":         old.get("case_id"),
        "weights":         {"meta": W_META, "kpi": W_KPI},
        "meta_score":      round(meta_score, 4),
        "meta_detail":     meta_detail,
        "kpi_score":       new_kpi_score,
        "kpi_detail":      new_kpi_detail,
        "final_score":     final,
        # Provenance: which spec was used + reference to the original reward.
        "rescored_from":   str(rd_path),
        "original_score":  old.get("final_score"),
    }


def _is_trial_dir(p: Path) -> bool:
    return (p / "verifier" / "reward_detail.json").exists()


def _print_diff(label: str, original: float | None, new: float) -> None:
    if original is None:
        print(f"  {label:<50}  →  {new:.4f}  (no prior)")
        return
    delta = new - original
    sign = "+" if delta >= 0 else ""
    print(f"  {label:<50}  {original:.4f}  →  {new:.4f}  ({sign}{delta:.4f})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    ap.add_argument("path", type=Path, help="trial dir or job dir")
    ap.add_argument("--kpis", type=Path, required=True, help="path to new kpis.json spec")
    ap.add_argument("--print", action="store_true", help="print full new reward_detail to stdout")
    ap.add_argument("--diff",  action="store_true", help="print one-line score diff per trial")
    ap.add_argument("--write", action="store_true",
                    help="WRITE the new reward.json + reward_detail.json in place "
                         "(default: dry-run, only summary)")
    args = ap.parse_args(argv)

    if not args.path.exists():
        print(f"path not found: {args.path}", file=sys.stderr)
        return 1
    if not args.kpis.is_file():
        print(f"--kpis not found: {args.kpis}", file=sys.stderr)
        return 1

    new_kpis = json.loads(args.kpis.read_text(encoding="utf-8"))

    trials: list[Path]
    if _is_trial_dir(args.path):
        trials = [args.path]
    else:
        trials = sorted(p for p in args.path.iterdir() if p.is_dir() and _is_trial_dir(p))
        if not trials:
            print(f"no trial dirs with reward_detail.json under: {args.path}", file=sys.stderr)
            return 1

    for trial in trials:
        new = rescore_trial(trial, new_kpis)
        if "error" in new:
            print(f"[{trial.name}] ERROR: {new['error']}", file=sys.stderr)
            continue

        if args.print:
            print(f"--- {trial.name} ---")
            print(json.dumps(new, indent=2))
        if args.diff:
            _print_diff(trial.name, new.get("original_score"), new["final_score"])
        if args.write:
            (trial / "verifier" / "reward.json").write_text(
                json.dumps({"score": new["final_score"]}, indent=2)
            )
            (trial / "verifier" / "reward_detail.json").write_text(
                json.dumps(new, indent=2)
            )
            print(f"wrote {trial}/verifier/reward{{,_detail}}.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
