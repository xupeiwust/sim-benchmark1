ARG BASE_REGISTRY=docker.io
FROM ${BASE_REGISTRY}/svd-ai-lab/sim-benchmark-base:latest

# DSMA-661 airfoil coordinates: bake the digitised profile into the
# image so the agent does not need network access at trial time. Two
# columns: x/c y/c. Source: NASA TMR DSMA-661 entry.
RUN mkdir -p /opt/vv/dsma661 && \
    curl -fsSL -o /opt/vv/dsma661/airfoil_coords.dat \
      'https://turbmodels.larc.nasa.gov/Other_DPW/dsma661/dsma661.txt' \
    || echo 'NOTE: airfoil_coords.dat fetch failed at build time; rebuild with internet.' >&2

WORKDIR /root/case
