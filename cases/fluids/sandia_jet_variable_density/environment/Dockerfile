ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# Sandia variable-density propane-air jet has no geometry file the agent
# needs at trial time — the case is fully defined by D = 5.26 mm + the
# inlet conditions stated in instruction.md. Reference experimental
# values live verifier-side in tests/kpis.json and are NOT exposed to
# the agent's container.

WORKDIR /root/case
