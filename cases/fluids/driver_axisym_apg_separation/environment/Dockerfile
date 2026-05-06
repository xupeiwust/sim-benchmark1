ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: agent constructs the axisymmetric
# diverging-fairing geometry to match the experimental Cp distribution.
# Driver 1991 reference values live in tests/kpis.json on the verifier
# side.

WORKDIR /root/case
