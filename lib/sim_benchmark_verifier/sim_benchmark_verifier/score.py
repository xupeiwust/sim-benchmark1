"""KPI-only grader for solver-neutral benchmark cases (schema reward-v3).

    final_score = kpi_score

The grader was originally two-layered (0.10 meta + 0.90 KPI) where the meta
layer required at least one successful `sim run` record. That gate has been
demoted to diagnostic-only (still computed and emitted into reward_detail.json
under `meta_detail`, but it carries zero weight in `final_score`). The reason:
the `with-sim-cli vs without-sim-cli` comparison study (configs/v19{a,b})
needs the without-sim-cli container to be able to score above zero — so
sim-cli usage cannot be gated. KPI source-verification (file_extract /
sim_run_stdout / sim_run_kpi) is still enforced per-KPI inside the KPI layer.

Layer 1 — meta (DIAGNOSTIC ONLY, weight = 0):
    meta_score = 0.5 · exec_ok + 0.5 · process_ok
    exec_ok    = at least one `kind=run` record in `sim --json logs`
    process_ok = at least one of those has ok=True
    (Carried in reward_detail.json so we can still tell, post-hoc, whether
    the agent used sim-cli at all — useful for the comparison study.)

Layer 2 — kpi (group-weighted accuracy, weight = 1.0):
    Each KPI in kpis.json belongs to a `group`; group weights sum to 1.
    Per-KPI score = source_verified · physics_pass · T_decay
        source_verified — agent's claim survives a re-extract from the
                          declared source (file / sim run stdout / sim
                          run parsed_output)
        physics_pass    — predicted value lies in [physics_min, physics_max]
        T_decay         — linear decay between T_good and T_bad relative to
                          gt_value (0 outside T_bad, 1 inside T_good)
    Group score = mean of member KPI scores. Missing KPI in result.json
    contributes 0 (not "exclude").
    kpi_score = sum(group.weight · group.score) over groups.

Reward layout:
    reward.json (Harbor contract — ONE key):
        {"score": <final_score>}
    reward_detail.json (everything):
        schema_version, meta_score + breakdown, kpi_score + per-group +
        per-KPI breakdown (value, kpi_score, source_verified, physics_pass,
        T_decay, why), final_score, runtime_detail.

KPI groups + provenance both live in `tests/kpis.json` (same Harbor mount).
result.json is agent-written at /tmp/agent/result.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────
# Layer 1 — meta gate
# ──────────────────────────────────────────────────────────────────────

def _query_sim_history() -> list[dict]:
    """Query sim-cli's run history via the public `sim --json logs` API.

    Decoupled from sim-cli's internal storage layout. Raises RuntimeError
    if sim-cli is unreachable or output is unparseable.

    Note: older sim-cli versions accepted a `--all` flag; current versions
    return the full list when `logs` is invoked with no positional target.
    """
    try:
        result = subprocess.run(
            ["sim", "--json", "logs"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"sim CLI not on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("sim --json logs timed out (>10s)") from e
    if result.returncode != 0:
        raise RuntimeError(
            f"sim --json logs exited {result.returncode}: "
            f"{result.stderr.strip()[:200]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"sim --json logs output not JSON: {e}") from e


def meta_check(_query=None) -> tuple[float, dict]:
    """Return (meta_score, detail).

    meta_score = 0.5 · exec_ok + 0.5 · process_ok
    """
    if _query is None:
        _query = _query_sim_history
    try:
        records = _query()
    except RuntimeError as e:
        return 0.0, {
            "exec_ok": 0.0, "process_ok": 0.0,
            "n_runs": 0, "n_ok_runs": 0,
            "why": str(e),
        }
    # Older sim-cli tagged each record with `kind: "run"` (vs e.g. "session");
    # the current schema dropped `kind` since `run` is the only record type
    # `sim --json logs` returns. Accept either: explicit kind=="run" OR
    # missing kind (new schema). Same for ok-ness: older used `ok: True`,
    # current uses `exit_code: 0`.
    runs = [r for r in records if r.get("kind", "run") == "run"]
    ok_runs = [
        r for r in runs
        if r.get("ok") is True or r.get("exit_code") == 0
    ]
    exec_ok    = 1.0 if runs else 0.0
    process_ok = 1.0 if ok_runs else 0.0
    detail = {
        "exec_ok":    exec_ok,
        "process_ok": process_ok,
        "n_runs":     len(runs),
        "n_ok_runs":  len(ok_runs),
        # Solver wall — sim records each run's duration_ms; cost_meter reads
        # this to populate compute.solver_wall_seconds (vs agent.wall_seconds
        # which includes LLM thinking + tool latency). Per-run map kept for
        # finer "which sim run was the expensive one" attribution.
        "total_solver_ms":     sum(int(r.get("duration_ms") or 0) for r in runs),
        "per_run_duration_ms": {str(r.get("run_id")): r.get("duration_ms") for r in runs},
        "solvers":    sorted({r.get("solver") for r in runs if r.get("solver")}),
        "records":    runs,  # carried for KPI provenance lookups
    }
    if not runs:
        detail["why"] = "no `sim run` records in sim-cli history"
    elif not ok_runs:
        detail["why"] = "no run record has ok=True"
    return 0.5 * exec_ok + 0.5 * process_ok, detail


# ──────────────────────────────────────────────────────────────────────
# Layer 2 — KPI scoring
# ──────────────────────────────────────────────────────────────────────

def _tgood_tbad_decay(err: float, t_good: float, t_bad: float) -> float:
    """Linear decay: err ≤ T_good → 1; err ≥ T_bad → 0; linear between."""
    if err <= t_good:
        return 1.0
    if err >= t_bad:
        return 0.0
    return (t_bad - err) / (t_bad - t_good)


def _physics_pass(spec: dict, pred: float) -> tuple[float, str]:
    if not math.isfinite(pred):
        return 0.0, f"pred {pred} is not finite"
    pmin = spec.get("physics_min")
    pmax = spec.get("physics_max")
    if pmin is not None and pred < float(pmin):
        return 0.0, f"pred {pred} < physics_min {pmin}"
    if pmax is not None and pred > float(pmax):
        return 0.0, f"pred {pred} > physics_max {pmax}"
    return 1.0, "ok"


def _t_decay(spec: dict, pred: float) -> float:
    gt = float(spec["gt_value"])
    err = abs(pred - gt)
    return _tgood_tbad_decay(err, float(spec["T_good"]), float(spec["T_bad"]))


def _score_one_kpi(name: str, spec: dict, claim, sim_records: list[dict]) -> dict:
    """Per-KPI score = source_verified · physics_pass · T_decay (each 0–1)."""
    from .provenance import verify_source

    if claim is None:
        return {
            "kpi_score":       0.0,
            "source_verified": 0.0,
            "physics_pass":    0.0,
            "t_decay":         0.0,
            "why":             "KPI absent from result.json",
        }
    pv = verify_source(claim, sim_records)
    if not pv.ok:
        return {
            "kpi_score":       0.0,
            "source_verified": 0.0,
            "physics_pass":    0.0,
            "t_decay":         0.0,
            "value":           claim.get("value") if isinstance(claim, dict) else None,
            "why":             f"source verification failed: {pv.why}",
        }
    value = float(claim["value"])
    phys, phys_why = _physics_pass(spec, value)
    decay = _t_decay(spec, value)
    score = phys * decay  # source already verified (=1)
    return {
        "value":           value,
        "kpi_score":       round(score, 4),
        "source_verified": 1.0,
        "physics_pass":    round(phys, 4),
        "physics_why":     phys_why,
        "t_decay":         round(decay, 4),
        "extracted":       pv.extracted,
    }


def _score_groups(kpis_spec: dict, groups_spec: dict, result: dict, sim_records: list[dict]) -> tuple[float, dict]:
    """Run each KPI through verification + scoring; aggregate by group.

    Group score = unweighted mean of its member KPI scores. The missing-from-
    `kpis.json` case is rejected at the spec layer; a member declared in
    spec but absent from result.json scores 0 (penalising "skipped a stage").
    """
    from .failure_class import annotate_per_kpi

    per_kpi: dict[str, dict] = {}
    for name, spec in kpis_spec.items():
        per_kpi[name] = _score_one_kpi(name, spec, result.get(name), sim_records)

    # Annotate each per-KPI dict with a stable failure_class enum so
    # downstream tooling can group "physics fails" vs "paperwork fails"
    # vs "agent didn't even claim the KPI" without re-parsing free text.
    failure_class_counts = annotate_per_kpi(per_kpi, result)

    per_group: dict[str, dict] = {}
    weighted_sum = 0.0
    for gname, gspec in groups_spec.items():
        weight = float(gspec["weight"])
        members = [n for n, s in kpis_spec.items() if s.get("group") == gname]
        if not members:
            per_group[gname] = {"weight": weight, "members": [], "group_score": 0.0, "why": "no KPIs declared for this group"}
            continue
        m_scores = [per_kpi[n]["kpi_score"] for n in members]
        gscore = sum(m_scores) / len(m_scores)
        per_group[gname] = {
            "weight":      weight,
            "members":     members,
            "group_score": round(gscore, 4),
        }
        weighted_sum += weight * gscore
    return round(weighted_sum, 4), {
        "per_group": per_group,
        "per_kpi": per_kpi,
        "failure_class_counts": failure_class_counts,
    }


# ──────────────────────────────────────────────────────────────────────
# Aggregation + CLI
# ──────────────────────────────────────────────────────────────────────

# Meta layer is diagnostic-only since 2026-04-29 — see module docstring.
# The previous (0.10, 0.90) split is preserved in git for reference.
W_META = 0.0
W_KPI  = 1.0


def _validate_groups(groups_spec: dict, kpis_spec: dict) -> str | None:
    if not groups_spec:
        return "kpis.json has no `kpi_groups`"
    total = sum(float(g.get("weight", 0)) for g in groups_spec.values())
    if abs(total - 1.0) > 1e-6:
        return f"kpi_groups weights sum to {total} (must be 1.0)"
    if not kpis_spec:
        return "kpis.json has no `kpis`"
    for name, spec in kpis_spec.items():
        g = spec.get("group")
        if g not in groups_spec:
            return f"kpi {name!r} declares group {g!r} which is not in kpi_groups"
    for gname, gspec in groups_spec.items():
        weight = float(gspec.get("weight", 0))
        members = [name for name, spec in kpis_spec.items() if spec.get("group") == gname]
        if weight > 0 and not members:
            return f"kpi_group {gname!r} has positive weight but no KPIs"
    return None


def main(argv: list[str] | None = None) -> int:
    from .contract import KPIS_PATH, AGENT_RESULT, REWARD_OUT
    ap = argparse.ArgumentParser(description="sim-benchmark solver-neutral grader (v3)")
    ap.add_argument("--kpis", type=Path, default=Path(KPIS_PATH),
                    help=f"Path to kpis.json (default: {KPIS_PATH})")
    ap.add_argument("--result", type=Path, default=Path(AGENT_RESULT),
                    help=f"Agent's result.json (default: {AGENT_RESULT})")
    ap.add_argument("--reward-out", type=Path, default=Path(REWARD_OUT),
                    help=f"Output reward.json path (default: {REWARD_OUT})")
    args = ap.parse_args(argv)

    spec = json.loads(args.kpis.read_text(encoding="utf-8"))
    kpis_spec = spec.get("kpis", {})
    groups_spec = spec.get("kpi_groups", {})

    spec_err = _validate_groups(groups_spec, kpis_spec)
    if spec_err:
        # Hard fail — the case is malformed; refuse to score.
        out = {"score": 0.0}
        args.reward_out.parent.mkdir(parents=True, exist_ok=True)
        args.reward_out.write_text(json.dumps(out, indent=2))
        args.reward_out.with_name("reward_detail.json").write_text(
            json.dumps({"schema_version": "reward-v3", "error": spec_err}, indent=2)
        )
        return 1

    # Meta layer
    meta_score, meta_detail = meta_check()
    sim_records = meta_detail.pop("records", [])

    # Result.json (may be missing — every KPI then scores 0 with "absent")
    result_obj: dict = {}
    result_err: str | None = None
    if args.result.is_file():
        try:
            result_obj = json.loads(args.result.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            result_err = f"result.json invalid JSON: {e}"
    else:
        result_err = f"result.json not found at {args.result}"

    # KPI layer
    if result_err:
        kpi_score = 0.0
        kpi_detail = {"why": result_err}
    else:
        kpi_score, kpi_detail = _score_groups(kpis_spec, groups_spec, result_obj, sim_records)

    final = round(W_META * meta_score + W_KPI * kpi_score, 4)

    # Harbor contract: reward.json has exactly one key.
    args.reward_out.parent.mkdir(parents=True, exist_ok=True)
    args.reward_out.write_text(json.dumps({"score": final}, indent=2))

    detail = {
        "schema_version": "reward-v3.1",
        "case_id":        spec.get("case_id", args.kpis.parent.name),
        "weights":        {"meta": W_META, "kpi": W_KPI},
        "meta_score":     round(meta_score, 4),
        "meta_detail":    meta_detail,
        "kpi_score":      kpi_score,
        "kpi_detail":     kpi_detail,
        "final_score":    final,
    }
    args.reward_out.with_name("reward_detail.json").write_text(
        json.dumps(detail, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
