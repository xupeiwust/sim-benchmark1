ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent constructs the ONERA M6
# wing from the Schmitt-Charpin AGARD AR-138 parameters listed in
# instruction.md (root/tip chord, semi-span, sweep, ONERA D section)
# and builds its own mesh. Reference experimental + NASA TMR force /
# Cp values live in tests/kpis.json on the verifier side and never
# enter the agent's container.

WORKDIR /root/case
