ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent builds plate mesh from
# scratch and post-processes the boundary-layer profile to find Re_theta
# stations. Reference Van Driest II Cf values live in tests/kpis.json on
# the verifier side.

WORKDIR /root/case
