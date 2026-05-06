ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent constructs the
# axisymmetric circular-arc bump (chord c=0.2032 m, t/c=0.094) wrapped
# around the 0.1524 m-diameter cylinder from scratch and meshes it as
# a 5-deg wedge (or 2D r-z plane) at its discretion. Bachalo & Johnson
# 1986 / TMR reference values live in tests/kpis.json on the verifier
# side and are never exposed to the agent.

WORKDIR /root/case
