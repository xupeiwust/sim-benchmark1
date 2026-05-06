#!/usr/bin/env python3
"""
openfoam_field_kpi.py — verifier-side KPI extractor.

First principle (schema v8):
  The agent's job is to produce a valid OpenFOAM simulation state on disk.
  The verifier's job is to read that state and compute the KPI itself.
  result.json is at most a hint — never a source of truth for the KPI value.

Usage in a per-case verify.py:

    from openfoam_field_kpi import find_case, latest_time_dir, compute_kpi

    KPIS = [
        {"name": "max_U_magnitude", "field": "U", "agg": "max_magnitude",
         "gt": 3.871,  "range": 10.0,   "weight": 0.6},
        {"name": "max_p",           "field": "p", "agg": "max",
         "gt": 317.78, "range": 1000.0, "weight": 0.4},
    ]

    case = find_case()
    t    = latest_time_dir(case)
    for spec in KPIS:
        pred = compute_kpi(t / spec["field"], spec["agg"])
        ...

Aggregation operators:
  scalars: max, min, mean, sum
  vectors: max_magnitude, min_magnitude, mean_magnitude
"""

from __future__ import annotations

import math
import re
import struct
from pathlib import Path
from typing import Iterable

STANDARD_FIELDS = {
    "U", "p", "T", "k", "omega", "epsilon", "nut", "nuTilda",
    "alpha.water", "rho", "phi", "p_rgh", "h", "e",
}


def find_case(roots: Iterable[Path] | None = None) -> Path | None:
    """Locate the OpenFOAM case directory: a dir containing constant/polyMesh/."""
    if roots is None:
        roots = [Path("/root/case"), Path("/tmp"), Path("/app"), Path.cwd()]
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = [root]
        for depth in range(3):
            new = []
            for c in candidates:
                if c in seen:
                    continue
                seen.add(c)
                if (c / "constant" / "polyMesh").is_dir():
                    return c
                try:
                    new.extend(p for p in c.iterdir() if p.is_dir())
                except (PermissionError, OSError):
                    pass
            candidates = new
            if not candidates:
                break
    return None


def latest_time_dir(case: Path, exclude_zero: bool = True) -> Path | None:
    """Return the directory whose name is the largest float (the latest write)."""
    times = []
    for p in case.iterdir():
        if not p.is_dir():
            continue
        try:
            t = float(p.name)
        except ValueError:
            continue
        if exclude_zero and t == 0.0:
            continue
        times.append((t, p))
    if not times:
        # Fall back to including zero
        for p in case.iterdir():
            if p.is_dir():
                try:
                    times.append((float(p.name), p))
                except ValueError:
                    pass
    if not times:
        return None
    return max(times, key=lambda x: x[0])[1]


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _is_binary_format(text: str) -> bool:
    """Check if the FoamFile header specifies binary format."""
    m = re.search(r'format\s+binary', text)
    return m is not None


def _parse_binary_internal_scalar(data: bytes, header_end_pos: int, count: int) -> list[float]:
    """Parse a binary nonuniform List<scalar> internalField."""
    # Find the line with just '(' after the header
    search_start = header_end_pos
    paren_pos = data.find(b'(', search_start)
    if paren_pos == -1:
        return []
    
    # Binary data starts after the newline following the '('
    blob_start = paren_pos + 1
    # Skip newline after '(' if present
    if blob_start < len(data) and data[blob_start:blob_start+1] == b'\n':
        blob_start += 1
    elif blob_start < len(data) and data[blob_start:blob_start+1] == b'\r':
        blob_start += 1
        if blob_start < len(data) and data[blob_start:blob_start+1] == b'\n':
            blob_start += 1
    
    element_size = 8  # 8 bytes per double
    blob_end = blob_start + count * element_size
    if blob_end > len(data):
        return []
    
    blob = data[blob_start:blob_end]
    return list(struct.unpack(f'<{count}d', blob))


def _parse_binary_internal_vector(data: bytes, header_end_pos: int, count: int) -> list[tuple[float, float, float]]:
    """Parse a binary nonuniform List<vector> internalField."""
    # Find the line with just '(' after the header
    search_start = header_end_pos
    paren_pos = data.find(b'(', search_start)
    if paren_pos == -1:
        return []
    
    # Binary data starts after the newline following the '('
    blob_start = paren_pos + 1
    # Skip newline after '(' if present
    if blob_start < len(data) and data[blob_start:blob_start+1] == b'\n':
        blob_start += 1
    elif blob_start < len(data) and data[blob_start:blob_start+1] == b'\r':
        blob_start += 1
        if blob_start < len(data) and data[blob_start:blob_start+1] == b'\n':
            blob_start += 1
    
    # Vector: 3 doubles per element = 24 bytes
    element_size = 24
    blob_end = blob_start + count * element_size
    if blob_end > len(data):
        return []
    
    blob = data[blob_start:blob_end]
    doubles = struct.unpack(f'<{count * 3}d', blob)
    return [(doubles[i], doubles[i+1], doubles[i+2]) for i in range(0, len(doubles), 3)]


def _parse_internal_scalar(text: str) -> list[float]:
    """Parse a scalar internalField (uniform or nonuniform List<scalar>)."""
    m = re.search(rf"internalField\s+uniform\s+({_NUM})", text)
    if m:
        return [float(m.group(1))]
    m = re.search(
        r"internalField\s+nonuniform\s+List<scalar>\s*\d*\s*\((.*?)\)\s*;",
        text, re.DOTALL,
    )
    if not m:
        return []
    return [float(x) for x in re.findall(_NUM, m.group(1))]


def _parse_internal_vector(text: str) -> list[tuple[float, float, float]]:
    """Parse a vector internalField (uniform or nonuniform List<vector>)."""
    m = re.search(
        rf"internalField\s+uniform\s+\(\s*({_NUM})\s+({_NUM})\s+({_NUM})\s*\)",
        text,
    )
    if m:
        return [(float(m.group(1)), float(m.group(2)), float(m.group(3)))]
    m = re.search(
        r"internalField\s+nonuniform\s+List<vector>\s*\d*\s*\((.*?)\)\s*;",
        text, re.DOTALL,
    )
    if not m:
        return []
    out: list[tuple[float, float, float]] = []
    for vm in re.finditer(rf"\(\s*({_NUM})\s+({_NUM})\s+({_NUM})\s*\)", m.group(1)):
        out.append((float(vm.group(1)), float(vm.group(2)), float(vm.group(3))))
    return out


def _detect_class(text: str) -> str:
    m = re.search(r"class\s+(\w+)\s*;", text)
    return m.group(1) if m else ""


def _detect_field_type_and_count(text: str) -> tuple[str, int | None]:
    """Detect field type (scalar/vector) and count for nonuniform fields."""
    # Check for vector first
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)", text)
    if m:
        return "vector", int(m.group(1))
    
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)", text)
    if m:
        return "scalar", int(m.group(1))
    
    # Check uniform
    if re.search(r"internalField\s+uniform", text):
        # Determine type from class or content
        if "vector" in text.lower():
            return "vector", 1
        return "scalar", 1
    
    return "unknown", None


def compute_kpi(field_file: Path, agg: str) -> float | None:
    """Return aggregated KPI from a single OpenFOAM field file."""
    if not field_file.is_file():
        return None
    try:
        data = field_file.read_bytes()
    except OSError:
        return None
    
    # Find the ASCII header portion - decode until we hit the binary blob or EOF
    # The header ends at the start of internalField content
    # We'll try to decode the beginning as ASCII to find format and class
    
    # Find internalField start position in bytes
    internal_field_pos = data.find(b'internalField')
    if internal_field_pos == -1:
        return None
    
    # Decode the header portion (up to internalField + some context)
    header_bytes = data[:internal_field_pos + 200]
    try:
        header_text = header_bytes.decode('ascii', errors='replace')
    except Exception:
        return None
    
    # Check format
    is_binary = _is_binary_format(header_text)
    cls = _detect_class(header_text)
    
    # Detect field type and count
    field_type, count = _detect_field_type_and_count(header_text)
    
    if is_binary and count is not None:
        # Binary format handling
        # header_end_pos is where the count line ends (after the newline after count)
        # We need to find the position of the count line and then the '(' line
        
        # Find the position right after the "List<type>" line
        # Look for the count number in the binary data
        list_type_match = re.search(r'List<(scalar|vector)>', header_text)
        if not list_type_match:
            return None
        
        type_name = list_type_match.group(1)
        
        # Find where the count value is in the binary data
        # Search for the pattern: List<type>\nCOUNT\n(
        # We need to find the count in the binary data
        type_str = f'List<{type_name}>'.encode()
        type_pos = data.find(type_str, internal_field_pos)
        if type_pos == -1:
            return None
        
        # Find newline after List<type>
        newline_after_type = data.find(b'\n', type_pos)
        if newline_after_type == -1:
            return None
        
        # Find the count number (next line)
        count_start = newline_after_type + 1
        count_end = data.find(b'\n', count_start)
        if count_end == -1:
            return None
        
        try:
            count_val = int(data[count_start:count_end].strip())
        except ValueError:
            return None
        
        # Find the '(' line
        paren_search_start = count_end
        paren_pos = data.find(b'(', paren_search_start)
        if paren_pos == -1:
            return None
        
        header_end_pos = paren_pos
        
        if type_name == 'scalar':
            vals = _parse_binary_internal_scalar(data, header_end_pos, count_val)
        elif type_name == 'vector':
            vals = _parse_binary_internal_vector(data, header_end_pos, count_val)
        else:
            return None
        
        if not vals:
            return None
        
        if type_name == 'vector':
            mags = [math.sqrt(x*x + y*y + z*z) for x, y, z in vals]
            return _aggregate_scalar(mags, agg.replace("_magnitude", ""))
        
        return _aggregate_scalar(vals, agg)
    
    else:
        # ASCII format - use existing logic
        try:
            text = data.decode('ascii', errors='replace')
        except Exception:
            return None
        
        is_vector = "Vector" in cls or agg.endswith("_magnitude")
        if is_vector:
            vals = _parse_internal_vector(text)
            if not vals:
                return None
            mags = [math.sqrt(x*x + y*y + z*z) for x, y, z in vals]
            return _aggregate_scalar(mags, agg.replace("_magnitude", ""))

        vals = _parse_internal_scalar(text)
        if not vals:
            return None
        return _aggregate_scalar(vals, agg)


def _aggregate_scalar(values: list[float], op: str) -> float | None:
    values = [v for v in values if math.isfinite(v)]
    if not values:
        return None
    if op in ("max", ""):
        return max(values)
    if op == "min":
        return min(values)
    if op == "mean":
        return sum(values) / len(values)
    if op == "sum":
        return sum(values)
    if op == "abs_max":
        return max(abs(v) for v in values)
    raise ValueError(f"unknown aggregation: {op!r}")


def authenticity_check(case: Path | None) -> tuple[float, str]:
    """Confirm the case directory shows real solver work."""
    if case is None:
        return 0.0, "no case dir with constant/polyMesh found"
    t = latest_time_dir(case, exclude_zero=True)
    if t is None:
        return 0.0, f"case={case} has no time dir > 0"
    fields = [f.name for f in t.iterdir() if f.is_file() and f.name in STANDARD_FIELDS]
    if not fields:
        return 0.0, f"case={case} t={t.name} has no standard field files"
    return 1.0, f"ok: case={case} t={t.name} fields={fields[:5]}"


def kpi_accuracy(pred: float, gt: float, rng: float) -> float:
    denom = max(abs(gt), rng * 0.01)
    return max(0.0, min(1.0, 1.0 - abs(pred - gt) / denom))