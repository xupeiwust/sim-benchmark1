"""lc_lowpass_2nd oracle - emit /tmp/agent/result.json from LTspice .meas log."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


LOG_PATH = Path("/root/case/lc_lowpass_2nd.log")


def latest_ltspice_run() -> dict:
    out = subprocess.check_output(["sim", "--json", "logs"], text=True)
    payload = json.loads(out)
    if isinstance(payload, dict):
        runs = payload.get("data", {}).get("runs") or payload.get("runs") or []
    else:
        runs = payload
    runs = [r for r in runs if r.get("solver") == "ltspice"]
    if not runs:
        raise RuntimeError("no ltspice run record yet")
    return runs[-1]


def _measure(measures: dict, name: str) -> float:
    return float(measures.get(name, {}).get("value"))


def _completed_source() -> dict:
    return {"kind": "ltspice_log", "path": str(LOG_PATH), "query": "completed"}


def _measure_source(name: str) -> dict:
    return {"kind": "ltspice_log", "path": str(LOG_PATH), "query": "measure", "measurement": name}


def main() -> int:
    rec = latest_ltspice_run()
    parsed = rec.get("parsed_output") or {}
    measures = parsed.get("measures") or {}
    errors = parsed.get("errors") or []

    gain_dc = _measure(measures, "gain_dc")
    f_3db = _measure(measures, "f_3db")
    sim_completed = 0 if errors else 1

    result = {
        "sim_completed": {
            "value": sim_completed,
            "source": _completed_source(),
        },
        "gain_dc": {
            "value": gain_dc,
            "source": _measure_source("gain_dc"),
        },
        "f_3db": {
            "value": f_3db,
            "source": _measure_source("f_3db"),
        },
    }

    out_path = Path("/tmp/agent/result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v["value"] for k, v in result.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
