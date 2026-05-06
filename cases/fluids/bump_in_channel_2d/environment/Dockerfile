ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent generates the bump
# profile from the closed-form sin^4 expression and builds its own mesh.
# Reference CFL3D-SA values live in tests/kpis.json on the verifier side.

WORKDIR /root/case
