#!/usr/bin/env python3
"""Semantic check of a downloaded CHANNEL5 .ctf header (used by download.sh).

Reads only the header block (up to the column-name line) and checks that the
file is a legacy Oxford HKL CHANNEL5 export ("Channel Text File", Device 0,
20 kV, 70 deg tilt, no AZtec author tag), that XCells/YCells/XStep/YStep
match the pinned values, and that BC and BS columns are present. Also checks
that the final data row sits at the last grid cell, which together with the
pinned size and md5 rejects truncated or reordered payloads.

Usage: check_ctf_header.py <file.ctf> <xcells> <ycells> <step_um>
"""
from __future__ import annotations

import sys


def fail(msg: str) -> None:
    raise SystemExit(f"HEADER FAIL: {msg}")


def main() -> int:
    path, xcells, ycells, step = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
    header: dict[str, str] = {}
    extra: dict[str, str] = {}
    columns: list[str] | None = None
    first = None
    with open(path, "rb") as fh:
        for n, raw in enumerate(fh):
            line = raw.decode("latin-1").rstrip("\r\n")
            if first is None:
                first = line
            cells = line.split("\t")
            if cells[0] == "Phase" and "BC" in cells:
                columns = cells
                break
            if cells[0].startswith("Euler angles refer to"):
                rest = cells[1:]
                extra = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1, 2)}
            elif len(cells) >= 2:
                header.setdefault(cells[0], cells[1])
            if n > 500:
                fail("no 'Phase ... BC BS' column line within the first 500 lines")
        tail_start = max(0, fh.seek(0, 2) - 4096)
        fh.seek(tail_start)
        tail = fh.read().decode("latin-1").rstrip("\r\n").split("\n")[-1].rstrip("\r")
    if first != "Channel Text File":
        fail(f"first line {first!r} is not 'Channel Text File'")
    if columns is None:
        fail("column header line not found")
    for name in ("Phase", "X", "Y", "BC", "BS"):
        if columns.count(name) != 1:
            fail(f"column {name!r} occurs {columns.count(name)} times in {columns!r}")
    if header.get("Author", "") != "":
        fail(f"Author tag {header.get('Author')!r} (AZtec exports are excluded)")
    if extra.get("Device") != "0":
        fail(f"Device {extra.get('Device')!r} != '0' (legacy CHANNEL5 maps only)")
    if abs(float(extra.get("KV", "nan")) - 20.0) > 0.01:
        fail(f"KV {extra.get('KV')!r} != 20")
    if abs(float(extra.get("TiltAngle", "nan")) - 70.0) > 1e-6:
        fail(f"TiltAngle {extra.get('TiltAngle')!r} != 70")
    if header.get("JobMode") != "Grid":
        fail(f"JobMode {header.get('JobMode')!r} != Grid")
    if int(header.get("XCells", -1)) != xcells or int(header.get("YCells", -1)) != ycells:
        fail(f"grid {header.get('XCells')}x{header.get('YCells')} != pinned {xcells}x{ycells}")
    for key in ("XStep", "YStep"):
        if abs(float(header.get(key, "nan")) - step) > 1e-9:
            fail(f"{key} {header.get(key)!r} != pinned {step}")
    tcells = tail.split("\t")
    if len(tcells) != len(columns):
        fail(f"last line has {len(tcells)} fields, expected {len(columns)}")
    tx = float(tcells[columns.index("X")])
    ty = float(tcells[columns.index("Y")])
    if round(tx / step) != xcells - 1 or round(ty / step) != ycells - 1:
        fail(f"last row at X={tx} Y={ty} is not the last grid cell")
    print(f"header_validation=ok file={path.rsplit('/', 1)[-1]} grid={xcells}x{ycells} step_um={step} "
          f"device=0 kv={extra.get('KV')} tilt={extra.get('TiltAngle')} columns={'/'.join(columns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
