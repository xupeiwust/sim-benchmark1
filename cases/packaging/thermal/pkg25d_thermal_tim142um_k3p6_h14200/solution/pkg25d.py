#!/usr/bin/env python3
"""Reference solution for the 2.5D-package thermal / thermo-mechanical family.

Builds a structured hex mesh over the package stack, writes CalculiX decks,
runs them, and reduces the result to the case's declared output interface.

This is the ORACLE. It is one legal way to answer the task, not the required
one: the prompt fixes the geometry, the material data, the loads and the
`results.csv` surface, and leaves mesh, element technology and solver to the
answerer. Nothing here is read by the verifier.

Units are SI throughout (m, W, Pa, K-differences), except that temperature is
carried in degrees Celsius -- steady conduction and film convection are both
invariant under the offset, and the thermal-strain reference is stated in the
task as 25 degC, so working in Celsius removes one conversion.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MM = 1.0e-3


# ── the package: geometry that every case in the family shares ───────────────
#
# Written once here and restated verbatim in each `instruction.md`. Values are
# millimetres, matching the prompt; they are scaled to metres at mesh time.

SUBSTRATE = {"x": (0.0, 52.0), "y": (0.0, 34.0)}
INTERPOSER = {"x": (4.0, 48.0), "y": (5.0, 29.0)}

DIES = {
    # in-plane footprint of each die, absolute millimetres
    "hbm_w": {"x": (5.6, 16.6), "y": (11.5, 22.5)},
    "asic": {"x": (18.6, 32.6), "y": (9.0, 25.0)},
    "hbm_e": {"x": (35.8, 46.8), "y": (11.5, 22.5)},
}

# A compute block inside the logic die carrying a disproportionate share of its
# power. This is what the case is actually about: a uniformly-heated die is a
# one-dimensional stack anyone can estimate by adding resistances in series, and
# the lateral conduction that decides how much of the ASIC's heat arrives at the
# HBM only exists because the source is concentrated.
ASIC_HOTSPOT = {"x": (22.0, 29.2), "y": (12.8, 21.2)}
ASIC_HOTSPOT_POWER_FRACTION = 0.50

# z stack, bottom to top. `tim` is the only thickness a case may move.
STACK = [
    ("substrate", 1.200),
    ("c4", 0.080),
    ("interposer", 0.100),
    ("ubump", 0.025),
    ("die", 0.750),
    ("tim", None),          # per-case
    ("lid", 1.500),
]

# k in W/m/K (a 3-tuple is orthotropic kxx,kyy,kzz), E in Pa, nu, alpha in 1/K.
MATERIALS = {
    "substrate": {"k": (22.0, 22.0, 0.65), "E": 24.0e9, "nu": 0.20, "alpha": 16.0e-6},
    "c4": {"k": 0.58, "E": 12.0e9, "nu": 0.30, "alpha": 25.0e-6},
    "interposer": {"k": 118.0, "E": 165.0e9, "nu": 0.22, "alpha": 2.6e-6},
    "ubump": {"k": 1.35, "E": 14.0e9, "nu": 0.30, "alpha": 27.0e-6},
    "silicon": {"k": 118.0, "E": 165.0e9, "nu": 0.22, "alpha": 2.6e-6},
    "gapfill": {"k": 0.80, "E": 16.0e9, "nu": 0.28, "alpha": 12.0e-6},
    "tim": {"k": None, "E": 0.020e9, "nu": 0.40, "alpha": 150.0e-6},
    "lid": {"k": 385.0, "E": 117.0e9, "nu": 0.34, "alpha": 17.0e-6},
}

T_AMBIENT_C = 25.0
H_BOARD = 14.0          # W/m^2/K on the substrate underside
T_STRESSFREE_C = 25.0

# Through-thickness element counts. In-plane spacing is the one knob the grid
# study moves; the z counts follow it only through `refine`.
Z_DIVISIONS = {
    "substrate": 4, "c4": 1, "interposer": 2,
    "ubump": 1, "die": 3, "tim": 1, "lid": 4,
}


@dataclass
class Case:
    case_id: str
    tim_thickness_mm: float
    tim_conductivity: float
    h_lid: float
    p_asic_w: float
    p_hbm_w_w: float
    p_hbm_e_w: float

    @classmethod
    def load(cls, path: Path) -> Case:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__})


# ── mesh ─────────────────────────────────────────────────────────────────────

def _grade(lo: float, hi: float, target: float) -> list[float]:
    """Uniform subdivision of one interval, at least one cell, honouring `target`."""
    n = max(1, int(math.ceil((hi - lo) / target - 1e-9)))
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def _axis(breaks: list[float], target: float) -> list[float]:
    out = [breaks[0]]
    for lo, hi in zip(breaks, breaks[1:]):
        out.extend(_grade(lo, hi, target)[1:])
    return out


class Mesh:
    """Tensor-product hex mesh whose planes land on every material boundary.

    Elements outside the interposer footprint exist only in the substrate
    layer, so the node grid is full but the element list is not; unused nodes
    are dropped rather than emitted, because a node carrying no element leaves
    a zero row in the static system.
    """

    def __init__(self, case: Case, h_inplane: float, refine: int = 1):
        z_names = [name for name, _ in STACK]
        z_thick = {
            name: (case.tim_thickness_mm if name == "tim" else t)
            for name, t in STACK
        }

        xb = sorted({
            *SUBSTRATE["x"], *INTERPOSER["x"], *ASIC_HOTSPOT["x"],
            *[v for d in DIES.values() for v in d["x"]],
        })
        yb = sorted({
            *SUBSTRATE["y"], *INTERPOSER["y"], *ASIC_HOTSPOT["y"],
            *[v for d in DIES.values() for v in d["y"]],
        })
        self.xs = _axis(xb, h_inplane)
        self.ys = _axis(yb, h_inplane)

        self.zs = [0.0]
        self.layer_of_k: list[str] = []
        z = 0.0
        for name in z_names:
            n = max(1, Z_DIVISIONS[name] * refine)
            t = z_thick[name]
            for i in range(n):
                self.zs.append(z + t * (i + 1) / n)
                self.layer_of_k.append(name)
            z += t

        self.nx, self.ny, self.nz = len(self.xs), len(self.ys), len(self.zs)
        self._build()

    # node ids are 1-based and stay on the full lattice; CalculiX accepts gaps
    def nid(self, i: int, j: int, k: int) -> int:
        return 1 + i + j * self.nx + k * self.nx * self.ny

    def _build(self) -> None:
        self.elements: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
        self.el_centroid: dict[int, tuple[float, float, float]] = {}
        self.el_volume: dict[int, float] = {}
        self.used_nodes: set[int] = set()
        self.lid_top: list[int] = []
        self.substrate_bottom: list[int] = []

        eid = 0
        for k in range(self.nz - 1):
            layer = self.layer_of_k[k]
            zc = 0.5 * (self.zs[k] + self.zs[k + 1])
            dz = self.zs[k + 1] - self.zs[k]
            for j in range(self.ny - 1):
                yc = 0.5 * (self.ys[j] + self.ys[j + 1])
                dy = self.ys[j + 1] - self.ys[j]
                for i in range(self.nx - 1):
                    xc = 0.5 * (self.xs[i] + self.xs[i + 1])
                    dx = self.xs[i + 1] - self.xs[i]
                    region = self._region(layer, xc, yc)
                    if region is None:
                        continue
                    eid += 1
                    n = (
                        self.nid(i, j, k), self.nid(i + 1, j, k),
                        self.nid(i + 1, j + 1, k), self.nid(i, j + 1, k),
                        self.nid(i, j, k + 1), self.nid(i + 1, j, k + 1),
                        self.nid(i + 1, j + 1, k + 1), self.nid(i, j + 1, k + 1),
                    )
                    self.elements.setdefault(region, []).append((eid, n))
                    self.el_centroid[eid] = (xc, yc, zc)
                    self.el_volume[eid] = dx * dy * dz * MM ** 3
                    self.used_nodes.update(n)
                    if layer == "lid" and k == self.nz - 2:
                        self.lid_top.append(eid)
                    if layer == "substrate" and k == 0:
                        self.substrate_bottom.append(eid)

    @staticmethod
    def _inside(box: dict, x: float, y: float) -> bool:
        return box["x"][0] < x < box["x"][1] and box["y"][0] < y < box["y"][1]

    def _region(self, layer: str, x: float, y: float) -> str | None:
        """Which element set a cell centre falls in, or None if it is outside."""
        if layer == "substrate":
            return "substrate" if self._inside(SUBSTRATE, x, y) else None
        if not self._inside(INTERPOSER, x, y):
            return None            # nothing above the substrate overhangs
        if layer != "die":
            return layer
        if self._inside(ASIC_HOTSPOT, x, y):
            return "asic_hot"
        for name, box in DIES.items():
            if self._inside(box, x, y):
                return name
        return "gapfill"

    # node sets used by the reductions
    def nodes_in(self, *regions: str) -> list[int]:
        return sorted({
            n for region in regions
            for _, conn in self.elements.get(region, ())
            for n in conn
        })

    def bottom_face_nodes(self) -> list[int]:
        return sorted(
            self.nid(i, j, 0)
            for j in range(self.ny) for i in range(self.nx)
            if self.nid(i, j, 0) in self.used_nodes
        )

    def interposer_under_asic(self) -> list[int]:
        box = DIES["asic"]
        return [
            eid for eid, _ in self.elements["interposer"]
            if self._inside(box, *self.el_centroid[eid][:2])
        ]


# ── CalculiX decks ───────────────────────────────────────────────────────────

MATERIAL_OF_REGION = {
    "substrate": "substrate", "c4": "c4", "interposer": "interposer",
    "ubump": "ubump", "asic": "silicon", "asic_hot": "silicon",
    "hbm_w": "silicon", "hbm_e": "silicon",
    "gapfill": "gapfill", "tim": "tim", "lid": "lid",
}


def _emit_mesh(mesh: Mesh, etype: str) -> list[str]:
    out = ["*NODE, NSET=NALL"]
    for nid in sorted(mesh.used_nodes):
        k, rem = divmod(nid - 1, mesh.nx * mesh.ny)
        j, i = divmod(rem, mesh.nx)
        out.append(
            f"{nid}, {mesh.xs[i] * MM:.9e}, {mesh.ys[j] * MM:.9e}, {mesh.zs[k] * MM:.9e}"
        )
    for region, elems in mesh.elements.items():
        out.append(f"*ELEMENT, TYPE={etype}, ELSET=E{region.upper()}")
        for eid, conn in elems:
            out.append(f"{eid}, " + ", ".join(str(n) for n in conn))
    return out


def _set(keyword: str, name: str, ids: list[int]) -> list[str]:
    """One `*ELSET` / `*NSET` block.

    No trailing comma on a continued line: CalculiX splits a data line on
    commas and converts every field, so the empty field an Abaqus-style
    continuation comma leaves behind reads as entity 0 and the deck is
    rejected for referring to something that was never defined.
    """
    out = [f"*{keyword}, {keyword}={name}"]
    for i in range(0, len(ids), 8):
        out.append(", ".join(str(e) for e in ids[i:i + 8]))
    return out


def _elset(name: str, ids: list[int]) -> list[str]:
    return _set("ELSET", name, ids)


def _nset(name: str, ids: list[int]) -> list[str]:
    return _set("NSET", name, ids)


def thermal_deck(mesh: Mesh, case: Case) -> str:
    lines = ["*HEADING", f"{case.case_id} steady conduction"]
    lines += _emit_mesh(mesh, "C3D8")

    for region in mesh.elements:
        mat = MATERIAL_OF_REGION[region]
        props = MATERIALS[mat]
        k = case.tim_conductivity if mat == "tim" else props["k"]
        lines.append(f"*MATERIAL, NAME=M{region.upper()}")
        if isinstance(k, tuple):
            lines += ["*CONDUCTIVITY, TYPE=ORTHO", f"{k[0]}, {k[1]}, {k[2]}"]
        else:
            lines += ["*CONDUCTIVITY", f"{k}"]
        lines.append(
            f"*SOLID SECTION, ELSET=E{region.upper()}, MATERIAL=M{region.upper()}"
        )

    lines += _elset("ELIDTOP", mesh.lid_top)
    lines += _elset("ESUBBOT", mesh.substrate_bottom)
    for die in DIES:
        regions = ("asic", "asic_hot") if die == "asic" else (die,)
        lines += _nset(f"N{die.upper()}", mesh.nodes_in(*regions))

    lines += ["*INITIAL CONDITIONS, TYPE=TEMPERATURE", f"NALL, {T_AMBIENT_C}"]
    lines += ["*STEP", "*HEAT TRANSFER, STEADY STATE"]

    lines.append("*DFLUX")
    f = ASIC_HOTSPOT_POWER_FRACTION
    for region, power in (
        ("asic_hot", case.p_asic_w * f), ("asic", case.p_asic_w * (1.0 - f)),
        ("hbm_w", case.p_hbm_w_w), ("hbm_e", case.p_hbm_e_w),
    ):
        volume = sum(mesh.el_volume[e] for e, _ in mesh.elements[region])
        lines.append(f"E{region.upper()}, BF, {power / volume:.9e}")

    lines += [
        "*FILM",
        f"ELIDTOP, F2, {T_AMBIENT_C}, {case.h_lid}",
        f"ESUBBOT, F1, {T_AMBIENT_C}, {H_BOARD}",
    ]
    for die in DIES:
        lines += [f"*NODE PRINT, NSET=N{die.upper()}", "NT"]
    lines += ["*NODE PRINT, NSET=NALL", "NT", "*END STEP", ""]
    return "\n".join(lines)


def static_deck(mesh: Mesh, temperatures: dict[int, float], etype: str) -> str:
    lines = ["*HEADING", "thermal-strain response at the steady operating field"]
    lines += _emit_mesh(mesh, etype)

    for region in mesh.elements:
        mat = MATERIAL_OF_REGION[region]
        props = MATERIALS[mat]
        lines.append(f"*MATERIAL, NAME=M{region.upper()}")
        lines += ["*ELASTIC", f"{props['E']:.6e}, {props['nu']}"]
        lines += [f"*EXPANSION, ZERO={T_STRESSFREE_C}", f"{props['alpha']:.6e}"]
        lines.append(
            f"*SOLID SECTION, ELSET=E{region.upper()}, MATERIAL=M{region.upper()}"
        )

    bottom = mesh.bottom_face_nodes()
    lines += _nset("NBOT", bottom)
    lines += _elset("EINTASIC", mesh.interposer_under_asic())

    # 3-2-1 rigid-body suppression on three corners of the substrate underside.
    # Statically determinate, so it adds no stress; the warpage reduction takes
    # out the residual rigid rotation by best-fit plane anyway.
    corners = _corner_nodes(mesh, bottom)
    lines += ["*BOUNDARY",
              f"{corners['origin']}, 1, 3, 0.0",
              f"{corners['x']}, 2, 3, 0.0",
              f"{corners['y']}, 3, 3, 0.0"]

    lines += ["*INITIAL CONDITIONS, TYPE=TEMPERATURE", f"NALL, {T_STRESSFREE_C}"]
    lines += ["*STEP", "*STATIC", "*TEMPERATURE"]
    for nid in sorted(mesh.used_nodes):
        lines.append(f"{nid}, {temperatures[nid]:.6f}")
    lines += ["*NODE PRINT, NSET=NBOT", "U"]
    lines += ["*EL PRINT, ELSET=EINTASIC", "S", "*END STEP", ""]
    return "\n".join(lines)


def _corner_nodes(mesh: Mesh, bottom: list[int]) -> dict[str, int]:
    def at(i: int, j: int) -> int:
        return mesh.nid(i, j, 0)
    return {"origin": at(0, 0), "x": at(mesh.nx - 1, 0), "y": at(0, mesh.ny - 1)}


# ── running and reading CalculiX ─────────────────────────────────────────────

def run_ccx(job: Path, threads: int = 0) -> None:
    env = None
    if threads:
        import os
        env = {**os.environ, "OMP_NUM_THREADS": str(threads)}
    # `-i` takes the job name, not the file name: ccx appends `.inp` itself, so
    # passing `thermal.inp` sends it looking for `thermal.inp.inp`.
    proc = subprocess.run(
        ["ccx", "-i", job.stem], cwd=job.parent, env=env,
        capture_output=True, text=True,
    )
    (job.parent / f"{job.stem}.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or "*ERROR" in proc.stdout:
        raise SystemExit(
            f"ccx failed for {job.stem} (rc={proc.returncode}):\n"
            + proc.stdout[-4000:] + proc.stderr[-2000:]
        )


def read_dat_blocks(path: Path) -> list[tuple[str, list[list[float]]]]:
    """Split a CalculiX `.dat` into (header, rows) blocks.

    A block is a non-numeric caption line followed by whitespace-separated
    numeric rows. Reading it this way rather than by fixed column offsets is
    what keeps the parser working across ccx builds.
    """
    blocks: list[tuple[str, list[list[float]]]] = []
    header, rows = None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        try:
            row = [float(f) for f in fields]
        except ValueError:
            if header is not None and rows:
                blocks.append((header, rows))
            header, rows = stripped.lower(), []
            continue
        if header is not None:
            rows.append(row)
    if header is not None and rows:
        blocks.append((header, rows))
    return blocks


def _blocks_named(blocks, keyword: str, setname: str | None = None):
    for header, rows in blocks:
        if keyword in header and (setname is None or f"set {setname.lower()}" in header):
            yield rows


def die_max_temperature(dat: Path, die: str) -> float:
    for rows in _blocks_named(read_dat_blocks(dat), "temperature", f"N{die.upper()}"):
        return max(r[1] for r in rows)
    raise SystemExit(f"no temperature block for N{die.upper()} in {dat}")


def all_temperatures(dat: Path) -> dict[int, float]:
    for rows in _blocks_named(read_dat_blocks(dat), "temperature", "NALL"):
        return {int(r[0]): r[1] for r in rows}
    raise SystemExit(f"no NALL temperature block in {dat}")


def warpage_um(dat: Path, mesh: Mesh) -> float:
    """Coplanarity of the substrate underside: peak-to-valley about a best-fit plane.

    Raw max(uz) - min(uz) is not the quantity -- it is not invariant under the
    rigid rotation the 3-2-1 restraint leaves free, so two correct runs that
    pinned different corners would disagree. Removing the least-squares plane
    is what makes it a property of the deformation, and it is also how a
    shadow-moire measurement reports it.
    """
    rows = next(_blocks_named(read_dat_blocks(dat), "displacement", "NBOT"), None)
    if rows is None:
        raise SystemExit(f"no NBOT displacement block in {dat}")
    coords = _node_coords(mesh)
    pts = [(*coords[int(r[0])][:2], r[3]) for r in rows]
    a, b, c = _fit_plane(pts)
    dev = [z - (a * x + b * y + c) for x, y, z in pts]
    return (max(dev) - min(dev)) * 1.0e6


def sigma_xx_mpa(dat: Path, mesh: Mesh) -> float:
    """Volume-average of sigma_xx over the interposer beneath the logic die.

    An average rather than a peak on purpose: the interposer is a thin stiff
    membrane between two much-more-expansive layers, so its in-plane stress is
    smooth in the interior and singular at the die corners. Averaging over a
    stated footprint is both the robust reduction (03 sec 0.5) and the number a
    packaging engineer actually quotes.
    """
    rows = next(_blocks_named(read_dat_blocks(dat), "stress", "EINTASIC"), None)
    if rows is None:
        raise SystemExit(f"no EINTASIC stress block in {dat}")
    per_element: dict[int, list[float]] = {}
    for r in rows:
        per_element.setdefault(int(r[0]), []).append(r[2])
    num = sum(mesh.el_volume[e] * (sum(v) / len(v)) for e, v in per_element.items())
    den = sum(mesh.el_volume[e] for e in per_element)
    return num / den / 1.0e6


def _node_coords(mesh: Mesh) -> dict[int, tuple[float, float, float]]:
    out = {}
    for nid in mesh.used_nodes:
        k, rem = divmod(nid - 1, mesh.nx * mesh.ny)
        j, i = divmod(rem, mesh.nx)
        out[nid] = (mesh.xs[i] * MM, mesh.ys[j] * MM, mesh.zs[k] * MM)
    return out


def _fit_plane(pts: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts); sz = sum(p[2] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); syy = sum(p[1] * p[1] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    sxz = sum(p[0] * p[2] for p in pts); syz = sum(p[1] * p[2] for p in pts)
    m = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    rhs = [sxz, syz, sz]
    return tuple(_solve3(m, rhs))


def _solve3(m: list[list[float]], b: list[float]) -> list[float]:
    a = [row[:] + [b[i]] for i, row in enumerate(m)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        for r in range(3):
            if r == col:
                continue
            f = a[r][col] / a[col][col]
            for c in range(col, 4):
                a[r][c] -= f * a[col][c]
    return [a[i][3] / a[i][i] for i in range(3)]


# ── the two reductions the family declares ───────────────────────────────────

def solve_thermal(case: Case, work: Path, h_inplane: float, refine: int = 1) -> dict:
    mesh = Mesh(case, h_inplane, refine)
    job = work / "thermal.inp"
    job.write_text(thermal_deck(mesh, case), encoding="utf-8")
    run_ccx(job)
    dat = work / "thermal.dat"
    return {
        "mesh": mesh,
        "dat": dat,
        "t_asic_max_c": die_max_temperature(dat, "asic"),
        "t_hbm_w_max_c": die_max_temperature(dat, "hbm_w"),
        "t_hbm_e_max_c": die_max_temperature(dat, "hbm_e"),
    }


def solve_thermomechanical(
    case: Case, work: Path, h_inplane: float, refine: int = 1, etype: str = "C3D8I"
) -> dict:
    thermal = solve_thermal(case, work, h_inplane, refine)
    mesh: Mesh = thermal["mesh"]
    temps = all_temperatures(thermal["dat"])
    job = work / "static.inp"
    job.write_text(static_deck(mesh, temps, etype), encoding="utf-8")
    run_ccx(job)
    dat = work / "static.dat"
    return {
        "t_asic_max_c": thermal["t_asic_max_c"],
        "warpage_um": warpage_um(dat, mesh),
        "sigma_xx_interposer_under_asic_mpa": sigma_xx_mpa(dat, mesh),
    }


def write_results(path: Path, values: dict, columns: list[str]) -> None:
    path.write_text(
        ",".join(columns) + "\n"
        + ",".join(f"{values[c]:.6f}" for c in columns) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    case = Case.load(here / "case.json")
    kind = json.loads((here / "case.json").read_text(encoding="utf-8"))["kind"]
    h = float(argv[1]) if len(argv) > 1 else 1.0
    work = here / "run"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    if kind == "thermal":
        result = solve_thermal(case, work, h)
        columns = ["t_asic_max_c", "t_hbm_w_max_c", "t_hbm_e_max_c"]
    else:
        result = solve_thermomechanical(case, work, h)
        columns = ["t_asic_max_c", "warpage_um", "sigma_xx_interposer_under_asic_mpa"]

    write_results(here / "results.csv", result, columns)
    print(json.dumps({c: result[c] for c in columns}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
