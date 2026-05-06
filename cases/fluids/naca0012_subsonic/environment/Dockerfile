ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent generates the airfoil
# coordinates from the closed-form 4-digit formula and builds its own
# mesh. Reference Ladson force data lives in tests/kpis.json on the
# verifier side and never enters the agent's container.

WORKDIR /root/case
