"""Running a submission's own driver under the budget the case declared.

The two native evaluators (`native_cantera`, `native_pybamm`) re-execute the
agent's driver in a clean copy of its submission and score only what that
re-run produces. That re-run has a deadline -- `tests/spec.json`'s
`reproduction_timeout_s` -- and the deadline is a real gate: a submission whose
numbers land inside the tolerance band still scores 0.0 if its driver overruns.

Three things about that gate were true and none of them were visible (#88):

1. **The two ways it fails were one value.** A driver that overran and a driver
   that crashed both arrived as `clean_reproduction: fail`, distinguishable
   only by string-matching an exception class name inside a free-text `why`.
   `openfoam_interface` and `calculix_interface` had already split them into
   `reproduction_timeout` / `reproduction_failed`; the two tracks that produced
   every recorded reproduction failure had not. This module makes the split
   structural, under the same two names, so there is one vocabulary.

2. **Nothing measured the headroom.** Across 333 surviving passing records the
   keys are `exit_code`, `stdout_tail`, `stripped_files`,
   `stripped_submitted_artifacts` -- not one of them says how long the re-run
   took. The one measurement anybody has of how close this gate sits was read
   out of a container log by hand: 728 s of a 900 s budget on
   `c2h4_air_flame_speed_phi0p78_2p1atm_321k`, against a 15-21 s oracle. A
   budget can only be sized from what real submissions cost, so the cost is
   recorded on every run, pass or fail.

3. **A timeout wrote no log at all.** The log write sat after the call that
   raised, so the one failure mode with nothing else to look at also threw away
   the driver's partial output. It is now written on every path.

The deadline is also enforced against the process *group* on POSIX. A driver
that fans a grid-refinement sweep out over `multiprocessing` leaves its workers
running when only the direct child is signalled; they then compete for the
verifier container's remaining seconds with the scoring that has to finish
inside them. `csv_interface.run_entry_point` learned this on the CFD track,
where killing only the parent shell made a configured deadline read tens of
seconds long.

None of this moves the budget. Which submissions pass is unchanged; what
changes is that a failure says which of the two things happened, and a pass
says how much of the budget it needed.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

# The failure vocabulary, shared with `openfoam_interface` / `calculix_interface`.
TIMEOUT = "reproduction_timeout"
DRIVER_ERROR = "reproduction_failed"
DRIVER_MISSING = "driver_missing"
RESULTS_MISSING = "results_missing"

# How long to keep reading the pipes after signalling. Bounded on purpose: an
# orphan holding the write end must not be able to hang the verifier, which
# would cost the trial its `reward.json` and store it as `unmeasured` rather
# than as a score.
_DRAIN_S = 5.0


class ReproductionFailed(RuntimeError):
    """A reproduction that failed and says which way, in a field, not in prose.

    The message stays human-readable; `detail` is what a later reader can
    count. `Recorder.run` in both native evaluators merges it into the
    dimension, so `failure_kind` lands in `reward_detail.json` next to the
    numbers the attempt had already measured.
    """

    def __init__(self, message: str, *, failure_kind: str, **detail: Any):
        super().__init__(message)
        self.failure_kind = failure_kind
        self.detail: dict[str, Any] = {"failure_kind": failure_kind, **detail}


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    """Signal the child's whole process group where the platform has one."""
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), sig)
            return
    except (OSError, ProcessLookupError):
        return
    try:
        proc.kill()
    except OSError:
        pass


def _write_log(log_path: Path | None, command: str, exit_code: Any,
               stdout: str, stderr: str) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"$ {command}\nexit={exit_code}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n",
        encoding="utf-8",
    )


def run_driver(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: int,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Run `argv` in `cwd` under `timeout_s`, recording what it cost.

    Returns the run record on success. Raises `ReproductionFailed` with
    `failure_kind` = `reproduction_timeout` (overran) or `reproduction_failed`
    (exited non-zero); both carry the same cost fields the success path does,
    because a failure that measured something should not throw it away.
    """
    command = " ".join(argv)
    started = time.monotonic()
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        # Own session -> own process group -> the deadline binds the whole tree.
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr = _drain_after_deadline(proc)
    elapsed = round(time.monotonic() - started, 3)

    cost: dict[str, Any] = {
        "reproduction_wall_sec": elapsed,
        "reproduction_timeout_s": timeout_s,
        "reproduction_budget_used": round(elapsed / timeout_s, 3) if timeout_s > 0 else None,
    }
    _write_log(log_path, command, "timeout" if timed_out else proc.returncode, stdout, stderr)

    if timed_out:
        raise ReproductionFailed(
            f"{command} did not finish inside the {timeout_s}s reproduction budget",
            failure_kind=TIMEOUT,
            stderr_tail=(stderr or "").strip()[-400:],
            **cost,
        )
    if proc.returncode != 0:
        raise ReproductionFailed(
            f"{command} exited {proc.returncode}: {(stderr or '').strip()[:300]}",
            failure_kind=DRIVER_ERROR,
            exit_code=proc.returncode,
            stderr_tail=(stderr or "").strip()[-400:],
            **cost,
        )
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout or "",
        "stderr": stderr or "",
        **cost,
    }


def _drain_after_deadline(proc: subprocess.Popen) -> tuple[str, str]:
    """Stop the run and take whatever output is already there, without waiting."""
    _signal_group(proc, signal.SIGTERM)
    try:
        return proc.communicate(timeout=_DRAIN_S)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
    try:
        return proc.communicate(timeout=_DRAIN_S)
    except subprocess.TimeoutExpired:
        # Something outside the group still holds the write end. Reading further
        # would trade the whole trial for the tail of a log.
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        return "", ""
