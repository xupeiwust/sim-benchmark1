ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent reproduces the geometry
# from the description in instruction.md (or, optionally, from the
# reference GMSH script `geometry_and_mesh.geo` shipped under
# vv-sources/) and builds its own mesh + solver setup. Reference
# experimental Cf values (Schulein 2004 optical, via SU2 V&V) live in
# tests/kpis.json on the verifier side.

WORKDIR /root/case
