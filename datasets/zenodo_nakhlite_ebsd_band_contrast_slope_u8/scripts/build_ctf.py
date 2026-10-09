#!/usr/bin/env python3
"""Build uint8 Band Contrast (BC) and Band Slope (BS) raster samples from the
10 pinned CHANNEL5 .ctf EBSD maps (local files only).

Each .ctf is streamed line by line. The header gives XCells, YCells, XStep,
YStep; the column-name line ("Phase X Y Bands Error Euler1 Euler2 Euler3 MAD
BC BS") gives the BC/BS/X/Y positions by name. Every data row is placed at
grid cell (round(Y/YStep), round(X/XStep)) of a YCells x XCells raster, so
the output is in raster order (row-major, x fastest) regardless of file
order. Every cell must be filled exactly once, every BC/BS must be a decimal
integer in 0..255 (no clamping), and the row count must equal XCells*YCells;
any violation is fatal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

DATASET_ID = "zenodo_nakhlite_ebsd_band_contrast_slope_u8"
SERIES = {"BC": "ebsd_band_contrast_u8", "BS": "ebsd_band_slope_u8"}


def fail(msg: str) -> None:
    raise SystemExit(f"BUILD FAIL: {msg}")


def read_maps(path: Path) -> list[dict]:
    maps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        map_id, key, size, md5, xc, yc, step = line.split("\t")
        maps.append({"map_id": map_id, "key": key, "size": int(size), "md5": md5,
                     "xcells": int(xc), "ycells": int(yc), "step": float(step)})
    return maps


def parse_ctf(path: Path, spec: dict) -> dict:
    header: dict[str, str] = {}
    extra: dict[str, str] = {}
    with path.open("rb") as fh:
        columns = None
        for raw in fh:
            cells = raw.decode("latin-1").rstrip("\r\n").split("\t")
            if cells[0] == "Phase" and "BC" in cells:
                columns = cells
                break
            if cells[0].startswith("Euler angles refer to"):
                rest = cells[1:]
                extra = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1, 2)}
            elif len(cells) >= 2:
                header.setdefault(cells[0], cells[1])
        if columns is None:
            fail(f"{path.name}: no column-name line")
        if extra.get("Device") != "0" or header.get("Author", "") != "":
            fail(f"{path.name}: not a legacy CHANNEL5 export (Device={extra.get('Device')!r}, Author={header.get('Author')!r})")
        xcells, ycells = int(header["XCells"]), int(header["YCells"])
        xstep, ystep = float(header["XStep"]), float(header["YStep"])
        if (xcells, ycells) != (spec["xcells"], spec["ycells"]):
            fail(f"{path.name}: grid {xcells}x{ycells} != pinned {spec['xcells']}x{spec['ycells']}")
        if abs(xstep - spec["step"]) > 1e-9 or abs(ystep - spec["step"]) > 1e-9:
            fail(f"{path.name}: step {xstep}/{ystep} != pinned {spec['step']}")
        ncols = len(columns)
        ix_, iy_, ibc, ibs = (columns.index(n) for n in ("X", "Y", "BC", "BS"))
        n = xcells * ycells
        bc = bytearray(n)
        bs = bytearray(n)
        filled = bytearray(n)
        rows = 0
        out_of_order = 0
        tol = 1e-3 * xstep
        for raw in fh:
            cells = raw.split(b"\t")
            if len(cells) != ncols:
                fail(f"{path.name}: data row {rows} has {len(cells)} fields, expected {ncols}")
            x = float(cells[ix_])
            y = float(cells[iy_])
            gx = round(x / xstep)
            gy = round(y / ystep)
            if abs(x - gx * xstep) > tol or abs(y - gy * ystep) > tol:
                fail(f"{path.name}: row {rows} X={x} Y={y} is off the {xstep} um lattice")
            if not (0 <= gx < xcells and 0 <= gy < ycells):
                fail(f"{path.name}: row {rows} X={x} Y={y} outside the {xcells}x{ycells} grid")
            k = gy * xcells + gx
            if filled[k]:
                fail(f"{path.name}: grid cell ({gy},{gx}) appears twice")
            filled[k] = 1
            if k != rows:
                out_of_order += 1
            vbc = cells[ibc].strip()
            vbs = cells[ibs].strip()
            if not (vbc.isdigit() and vbs.isdigit()):
                fail(f"{path.name}: row {rows} BC/BS not non-negative integers: {vbc!r}/{vbs!r}")
            a = int(vbc)
            b = int(vbs)
            if a > 255 or b > 255:
                fail(f"{path.name}: row {rows} BC/BS out of 0..255: {a}/{b}")
            bc[k] = a
            bs[k] = b
            rows += 1
    if rows != n:
        fail(f"{path.name}: {rows} data rows != XCells*YCells = {n}")
    if filled.count(0):
        fail(f"{path.name}: {filled.count(0)} grid cells never filled")
    return {"xcells": xcells, "ycells": ycells, "step_um": xstep, "rows": rows,
            "out_of_order_rows": out_of_order, "BC": bc, "BS": bs,
            "kv": extra.get("KV"), "tilt": extra.get("TiltAngle")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--maps", type=Path, required=True)
    args = ap.parse_args()
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    samples = root / "samples" / DATASET_ID
    index_dir = root / "index" / DATASET_ID
    filtered = root / "filtered" / DATASET_ID
    maps = read_maps(args.maps)
    if len(maps) != 10:
        fail(f"maps.tsv lists {len(maps)} maps, expected 10")
    for d in (samples, index_dir, filtered):
        d.mkdir(parents=True, exist_ok=True)
    for sid in SERIES.values():
        sdir = samples / sid
        sdir.mkdir(parents=True, exist_ok=True)
        for old in sdir.glob("*.bin"):
            old.unlink()

    index_rows: list[dict] = []
    stats: list[dict] = []
    for spec in maps:
        src = downloads / f"{spec['map_id']}.ctf"
        if not src.is_file():
            fail(f"missing local file {src}")
        if src.stat().st_size != spec["size"]:
            fail(f"{src.name}: size {src.stat().st_size} != pinned {spec['size']}")
        res = parse_ctf(src, spec)
        entry = {"map_id": spec["map_id"], "zenodo_key": spec["key"], "xcells": res["xcells"],
                 "ycells": res["ycells"], "step_um": res["step_um"], "rows": res["rows"],
                 "out_of_order_rows": res["out_of_order_rows"], "kv": res["kv"], "tilt": res["tilt"]}
        for field, sid in SERIES.items():
            data = bytes(res[field])
            counts = _histogram(data)
            distinct = sum(1 for c in counts if c)
            zero_frac = counts[0] / len(data)
            vmin = next(v for v in range(256) if counts[v])
            vmax = next(v for v in range(255, -1, -1) if counts[v])
            rel = Path("samples") / DATASET_ID / sid / f"{spec['map_id']}.bin"
            tmp = root / (str(rel) + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, root / rel)
            row = {
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": str(rel),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(data),
                "value_count": len(data),
                "map_id": spec["map_id"],
                "source_file": spec["key"],
                "source_field": field,
                "shape": [res["ycells"], res["xcells"]],
                "axes": ["scan_y", "scan_x"],
                "step_um": res["step_um"],
                "min": vmin,
                "max": vmax,
                "distinct_values": distinct,
                "zero_fraction": round(zero_frac, 6),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            index_rows.append(row)
            entry[f"{field}_min"], entry[f"{field}_max"] = vmin, vmax
            entry[f"{field}_distinct"], entry[f"{field}_zero_fraction"] = distinct, round(zero_frac, 6)
        stats.append(entry)
        print(f"map={spec['map_id']} grid={res['ycells']}x{res['xcells']} step={res['step_um']} rows={res['rows']} "
              f"out_of_order={res['out_of_order_rows']} BC={entry['BC_min']}..{entry['BC_max']} "
              f"zero={entry['BC_zero_fraction']:.4f} BS={entry['BS_min']}..{entry['BS_max']} "
              f"zero={entry['BS_zero_fraction']:.4f}", flush=True)

    index_rows.sort(key=lambda r: (r["series_id"], r["map_id"]))
    tmp = index_dir / "samples.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp, index_dir / "samples.jsonl")
    (filtered / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    for sid in SERIES.values():
        rows = [r for r in index_rows if r["series_id"] == sid]
        print(f"series={sid} samples={len(rows)} bytes={sum(r['sample_size_bytes'] for r in rows)}")
    return 0


def _histogram(data: bytes) -> list[int]:
    return [data.count(bytes([v])) for v in range(256)]


if __name__ == "__main__":
    sys.exit(main())
