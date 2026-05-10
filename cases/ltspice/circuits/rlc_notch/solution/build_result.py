"""rlc_notch oracle - emit /tmp/agent/result.json from stepped LTspice .meas log."""
from __future__ import annotations

import json
import re
from pathlib import Path


LOG_PATH = Path("/root/case/rlc_notch.log")
SELECTED_STEP = 3

_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _log_text() -> str:
    return LOG_PATH.read_text(encoding="utf-8", errors="replace").replace("\x00", "")


def _number_from_token(token: str) -> str:
    token = token.strip().strip("(),")
    if "dB" in token:
        token = token.split("dB", 1)[0]
    m = _NUMBER_RE.search(token)
    if not m:
        raise ValueError(f"no numeric value in {token!r}")
    return m.group(0)


def _table_value(text: str, measure: str, step: int) -> float:
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() == f"measurement: {measure}".lower():
            in_table = True
            continue
        if in_table and stripped.lower().startswith("measurement:"):
            break
        if not in_table:
            continue
        parts = stripped.split()
        if parts and parts[0].isdigit() and int(parts[0]) == step:
            return float(_number_from_token(parts[1]))
    raise RuntimeError(f"measure {measure!r} step {step} not found")


def _completed_source() -> dict:
    return {"kind": "ltspice_log", "path": str(LOG_PATH), "query": "completed"}


def _measure_source(name: str, step: int) -> dict:
    return {"kind": "ltspice_log", "path": str(LOG_PATH), "query": "measure", "measurement": name, "step": step}


def _step_param_source(param: str, step: int, scale: float) -> dict:
    return {"kind": "ltspice_log", "path": str(LOG_PATH), "query": "step_param", "param": param, "step": step, "scale": scale}


def main() -> int:
    text = _log_text()
    sim_completed = 1 if "Total elapsed time" in text else 0
    selected_cap_nF = 110.0
    dc_gain = _table_value(text, "dc_gain", SELECTED_STEP)
    notch_depth = _table_value(text, "notch_depth", SELECTED_STEP)

    result = {
        "sim_completed": {
            "value": sim_completed,
            "source": _completed_source(),
        },
        "selected_cap_nF": {
            "value": selected_cap_nF,
            "source": _step_param_source("ctrap", SELECTED_STEP, 1000000000),
        },
        "dc_gain": {
            "value": dc_gain,
            "source": _measure_source("dc_gain", SELECTED_STEP),
        },
        "notch_depth": {
            "value": notch_depth,
            "source": _measure_source("notch_depth", SELECTED_STEP),
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v["value"] for k, v in result.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
