ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent builds its own mesh from
# scratch, and the only "data" the case carries is the ground-truth KPI
# values — which live in tests/kpis.json on the verifier side and never
# enter the agent's container.

WORKDIR /root/case
