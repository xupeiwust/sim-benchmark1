This case runs on its domain image unmodified and ships no fixtures.

This file exists so the directory is not empty: Harbor requires an
`environment/` to recognise a task at all, and hashes an empty one as the
`docker_image` string, which gives every fixture-less case in a track the
same container identity.

case: packaging/thermomechanical/pkg25d_warpage_tim41um_k9p8_h24500
