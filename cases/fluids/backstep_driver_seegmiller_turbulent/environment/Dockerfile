ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: agent generates the channel mesh
# directly from the geometry spec in instruction.md. Driver-Seegmiller
# 1985 reference values live in tests/kpis.json on the verifier side.

WORKDIR /root/case
