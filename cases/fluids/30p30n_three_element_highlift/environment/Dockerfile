ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# Bundle the SU2 V&V 30P30N mesh family (L1-L5) so the agent has a
# canonical JAXA APC-IV configuration-F geometry available offline.
# Source: https://github.com/su2code/VandV (rans/30p30n/) — five
# refinement levels, gzipped SU2 unstructured meshes.
#
# Cell counts (post-gunzip):
#   L1 coarse        ~0.3 M
#   L2 medium        ~0.6 M
#   L3 fine          ~1.4 M
#   L4 extra-fine    ~3.0 M
#   L5 super-fine    ~5.6 M
#
# Reference experimental CL/CD/Cp values (JAXA-SP-18-008 / SU2 V&V
# plots) live in tests/kpis.json on the verifier side and are NOT
# exposed to the agent's container.
COPY --chown=root:root vv-meshes/30p30n/2D_L1_coarse_r1.su2.gz       /opt/vv/30p30n/2D_L1_coarse_r1.su2.gz
COPY --chown=root:root vv-meshes/30p30n/2D_L2_medium_r1.su2.gz       /opt/vv/30p30n/2D_L2_medium_r1.su2.gz
COPY --chown=root:root vv-meshes/30p30n/2D_L3_fine_r1.su2.gz         /opt/vv/30p30n/2D_L3_fine_r1.su2.gz
COPY --chown=root:root vv-meshes/30p30n/2D_L4_extra-fine_r1.su2.gz   /opt/vv/30p30n/2D_L4_extra-fine_r1.su2.gz
COPY --chown=root:root vv-meshes/30p30n/2D_L5_super-fine_r1.su2.gz   /opt/vv/30p30n/2D_L5_super-fine_r1.su2.gz
COPY --chown=root:root vv-meshes/30p30n/README.md                    /opt/vv/30p30n/README.md

WORKDIR /root/case
