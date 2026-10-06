#!/usr/bin/env python3
"""Validate one range-fetched axial slice written by download.sh.

Usage: check_slice.py payload headers start end total name pins_file

Checks: the final HTTP response is 206 with Content-Range exactly
"bytes start-end/total" (total = pinned .raw size); the payload is exactly
1381*1381 bytes; the slice is not degenerate (see SLICE RULES below); and, when
the recipe's slice_sha256.tsv exists, the SHA-256 equals the pinned value.

SLICE RULES (shared verbatim with build and verify): at least 64 distinct
values, modal value at most 10% of voxels, no constant voxel row or column,
mean grey level within [72, 104] (interior aerogel slices sit near 85-90; the
end zones excluded by the 5% margin read 101-113).
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

SIDE = 1381
SLICE_BYTES = SIDE * SIDE
MIN_DISTINCT = 64
MAX_MODAL_FRACTION = 0.10
MEAN_RANGE = (72.0, 104.0)


def slice_problems(data: bytes) -> tuple[list[str], dict]:
    counts = [0] * 256
    for value in range(256):
        counts[value] = data.count(bytes((value,)))
    present = [v for v in range(256) if counts[v]]
    n = len(data)
    mean = sum(v * counts[v] for v in present) / n
    modal = max(counts)
    problems = []
    if len(present) < MIN_DISTINCT:
        problems.append(f"only {len(present)} distinct values")
    if modal > MAX_MODAL_FRACTION * n:
        problems.append(f"modal value covers {modal / n:.3f} of voxels")
    if not MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]:
        problems.append(f"mean {mean:.2f} outside {MEAN_RANGE}")
    for y in range(SIDE):
        row = data[y * SIDE:(y + 1) * SIDE]
        if row.count(row[:1]) == SIDE:
            problems.append(f"constant row {y}")
            break
    for x in range(SIDE):
        col = data[x::SIDE]
        if col.count(col[:1]) == SIDE:
            problems.append(f"constant column {x}")
            break
    stats = {"min": present[0], "max": present[-1], "mean": mean, "distinct": len(present),
             "modal_fraction": modal / n, "zeros": counts[0], "saturated": counts[255], "counts": counts}
    return problems, stats


def load_pins(path: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    if path and os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            fields = line.split()
            if fields and not fields[0].startswith("#"):
                pins[fields[0]] = fields[-1]
    return pins


def main() -> int:
    payload, headers, start, end, total, name, pins_file = sys.argv[1:8]
    start, end, total = int(start), int(end), int(total)
    text = open(headers, encoding="iso-8859-1").read()
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    final = blocks[-1] if blocks else ""
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    crange = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final,
                       flags=re.IGNORECASE | re.MULTILINE)
    if not status or status.group(1) != "206" or not crange:
        raise SystemExit(f"{name}: final response is not 206 with a Content-Range header")
    if tuple(map(int, crange.groups())) != (start, end, total):
        raise SystemExit(f"{name}: Content-Range {crange.groups()} != {(start, end, total)}")
    size = os.path.getsize(payload)
    if size != SLICE_BYTES or end - start + 1 != SLICE_BYTES:
        raise SystemExit(f"{name}: payload {size} bytes != {SLICE_BYTES}")
    data = open(payload, "rb").read()
    problems, stats = slice_problems(data)
    if problems:
        raise SystemExit(f"{name}: degenerate slice: {'; '.join(problems)}")
    digest = hashlib.sha256(data).hexdigest()
    pins = load_pins(pins_file)
    if pins:
        if name not in pins:
            raise SystemExit(f"{name}: no pinned sha256 in {pins_file}")
        if pins[name] != digest:
            raise SystemExit(f"{name}: sha256 {digest} != pinned {pins[name]}")
    print(f"slice_validation=ok {name} bytes={size} min={stats['min']} max={stats['max']} "
          f"mean={stats['mean']:.2f} distinct={stats['distinct']} modal={stats['modal_fraction']:.4f} "
          f"pinned={'yes' if pins else 'no'} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
