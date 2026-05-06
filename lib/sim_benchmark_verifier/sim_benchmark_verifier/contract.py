"""Single source of truth for the verifier-container path contract.

These paths are protocol constants Harbor (and our own conventions) guarantee
inside the verifier container. Defining them in one place means test.sh stays
trivial — it doesn't carry magic strings or rediscover layout via realpath.

Mirror of harbor.models.trial.paths.EnvironmentPaths for the parts Harbor
defines; AGENT_RESULT is purely a sim-benchmark convention. Keep this module
manually in sync with Harbor if it ever changes its mount layout.
"""
from pathlib import PurePosixPath

TESTS_DIR    = PurePosixPath("/tests")            # Harbor: tests/ → /tests
KPIS_PATH    = TESTS_DIR / "kpis.json"            # ours: kpis.json sibling of test.sh
AGENT_RESULT = PurePosixPath("/tmp/agent/result.json")  # ours: agent writes its KPIs here
REWARD_OUT   = PurePosixPath("/logs/verifier/reward.json")  # Harbor: reward_json_path
