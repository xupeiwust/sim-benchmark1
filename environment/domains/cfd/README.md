# cfd-fullstack

Industrial CFD full flow. Forward port of the legacy `environment/base`.

| component | source | in CORE? |
|---|---|---|
| OpenFOAM ESI v2412 | base image | ✅ |
| Gmsh | apt | ✅ |
| meshio | pip | ✅ |
| pyvista | pip | ✅ |
| numpy / scipy / matplotlib | pip | ✅ |
| sim-plugin-openfoam | git | ✅ |
| + common harness | `_common` | ✅ |
| SU2 (compressible/adjoint) | binary | ⬜ optional |
| ParaView (pvbatch/pvpython) | apt | ⬜ optional (~1.5 GB) |

The CFD cases under `cases/cfd/fluids/` run on this image. Same OpenFOAM as
the legacy per-case images, plus the meshing/post stack a CFD engineer
actually uses.

## Verify after build

```bash
docker run --rm sim-benchmark-cfd-fullstack:latest bash -lc \
  'source /etc/profile; which simpleFoam; gmsh --version; \
   python3 -c "import meshio,pyvista; print(meshio.__version__)"; \
   sim --version 2>/dev/null || true; claude --version'
```

## Add a tool

Edit `tools.sh`. SU2 and ParaView are the most likely opt-ins.
