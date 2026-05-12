ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# No case-specific assets required: the agent constructs the
# Glauert-Goldschmied hump profile from the canonical NASA TMR
# coordinates (publicly distributed via tmbwg.github.io) and builds
# its own mesh. Greenblatt 2006 experimental reference values live
# in tests/kpis.json on the verifier side.

WORKDIR /root/case
