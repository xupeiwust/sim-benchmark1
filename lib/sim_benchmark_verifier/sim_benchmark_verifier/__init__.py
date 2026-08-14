"""sim_benchmark_verifier — shared grader for solver-neutral CAE cases.

Every cases/<domain>/<id>/tests/test.sh invokes
`python -m sim_benchmark_verifier.score` with the path to its kpis.json.
All scoring logic lives here; each case contributes only a declarative
tests/kpis.json + an instruction.md + a Dockerfile.
"""

__version__ = "0.1.0"
