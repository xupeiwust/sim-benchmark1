ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: agent generates NACA 4412 surface
# from the closed-form 4-digit formula (max camber 4% at x/c=0.4, max
# thickness 12%) and builds its own mesh. Coles-Wadcock 1979 reference
# values live in tests/kpis.json on the verifier side.

WORKDIR /root/case
