#!/usr/bin/env python3
"""Independently re-derive and check the BC/BS raster samples.

Does not import the build script. For every pinned map it re-checks the
local .ctf size and md5, re-parses the file with its own line parser
(header keys, column positions by name, integer grid indices recovered from
X/Y), rebuilds the expected BC and BS rasters, and byte-compares them with
the emitted samples. It then checks the sample index fields, recomputes
per-sample statistics (min, max, distinct values, zero share), rejects
constant or degenerate samples, and checks the manifest series totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

DATASET_ID = "zenodo_nakhlite_ebsd_band_contrast_slope_u8"
FIELD_SERIES = (("BC", "ebsd_band_contrast_u8"), ("BS", "ebsd_band_slope_u8"))
MIN_DISTINCT = 16
MAX_ZERO_FRACTION = 0.8
FIXED = {"dataset_id": DATASET_ID, "numeric_kind": "uint", "bit_width": 8,
         "endianness": "little", "element_size_bytes": 1}


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def rederive(path: Path, xcells: int, ycells: int, step: float) -> tuple[bytearray, bytearray]:
    """Return (BC, BS) rasters, row-major YCells x XCells."""
    with path.open("r", encoding="latin-1", newline="") as fh:
        first = fh.readline().strip()
        if first != "Channel Text File":
            fail(f"{path.name}: first line {first!r}")
        hdr: dict[str, str] = {}
        cols: list[str] = []
        for line in fh:
            parts = line.strip("\r\n").split("\t")
            if parts[0] == "Phase" and "BS" in parts:
                cols = parts
                break
            if parts[0].startswith("Euler angles"):
                for i in range(1, len(parts) - 1, 2):
                    hdr["@" + parts[i]] = parts[i + 1]
            elif len(parts) > 1 and parts[0] not in hdr:
                hdr[parts[0]] = parts[1]
        if not cols:
            fail(f"{path.name}: no column line")
        if hdr.get("@Device") != "0" or hdr.get("Author") != "":
            fail(f"{path.name}: Device {hdr.get('@Device')!r} Author {hdr.get('Author')!r}")
        if int(hdr["XCells"]) != xcells or int(hdr["YCells"]) != ycells:
            fail(f"{path.name}: header grid {hdr['XCells']}x{hdr['YCells']} != {xcells}x{ycells}")
        if float(hdr["XStep"]) != step or float(hdr["YStep"]) != step:
            fail(f"{path.name}: header step {hdr['XStep']}/{hdr['YStep']} != {step}")
        pos = {name: cols.index(name) for name in ("X", "Y", "BC", "BS")}
        width = len(cols)
        total = xcells * ycells
        bc = bytearray(total)
        bs = bytearray(total)
        seen = bytearray(total)
        count = 0
        for line in fh:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != width:
                fail(f"{path.name}: row {count} has {len(parts)} fields")
            gx = int(round(float(parts[pos["X"]]) / step))
            gy = int(round(float(parts[pos["Y"]]) / step))
            if gx < 0 or gy < 0 or gx >= xcells or gy >= ycells:
                fail(f"{path.name}: row {count} outside grid")
            cell = gx + gy * xcells
            if seen[cell]:
                fail(f"{path.name}: duplicate grid cell {gy},{gx}")
            seen[cell] = 1
            sa, sb = parts[pos["BC"]], parts[pos["BS"]]
            if not (sa.isdigit() and sb.isdigit()) or int(sa) > 255 or int(sb) > 255:
                fail(f"{path.name}: row {count} BC/BS {parts[pos['BC']]!r}/{parts[pos['BS']]!r} not in 0..255")
            bc[cell] = int(sa)
            bs[cell] = int(sb)
            count += 1
    if count != total:
        fail(f"{path.name}: {count} rows != {total}")
    if 0 in seen:
        fail(f"{path.name}: unfilled grid cells")
    return bc, bs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--maps", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"

    specs = []
    for line in args.maps.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            f = line.split("\t")
            specs.append((f[0], f[1], int(f[2]), f[3], int(f[4]), int(f[5]), float(f[6])))
    if len(specs) != 10:
        fail(f"expected 10 pinned maps, got {len(specs)}")

    if not index_path.is_file():
        fail(f"missing index {index_path}")
    rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_key = {}
    for r in rows:
        key = (r.get("series_id"), r.get("map_id"))
        if key in by_key:
            fail(f"duplicate index row {key}")
        by_key[key] = r
    if len(rows) != 2 * len(specs):
        fail(f"index has {len(rows)} rows, expected {2 * len(specs)}")

    totals = {sid: [0, 0] for _, sid in FIELD_SERIES}
    agg = hashlib.sha256()
    for map_id, key, size, md5, xcells, ycells, step in specs:
        src = downloads / f"{map_id}.ctf"
        if not src.is_file() or src.stat().st_size != size:
            fail(f"{src}: missing or wrong size")
        if md5_file(src) != md5:
            fail(f"{src.name}: md5 mismatch with pinned {md5}")
        expected = dict(zip(("BC", "BS"), rederive(src, xcells, ycells, step)))
        report = [f"map={map_id}", f"grid={ycells}x{xcells}"]
        for field, sid in FIELD_SERIES:
            row = by_key.get((sid, map_id))
            if row is None:
                fail(f"no index row for {sid}/{map_id}")
            for k, v in FIXED.items():
                if row.get(k) != v:
                    fail(f"{sid}/{map_id}: index {k}={row.get(k)!r} != {v!r}")
            rel = f"samples/{DATASET_ID}/{sid}/{map_id}.bin"
            if row.get("sample_path") != rel:
                fail(f"{sid}/{map_id}: sample_path {row.get('sample_path')!r} != {rel!r}")
            data = (root / rel).read_bytes()
            want = bytes(expected[field])
            if data != want:
                fail(f"{sid}/{map_id}: sample bytes differ from re-derived {field} raster")
            n = len(data)
            if row.get("sample_size_bytes") != n or row.get("value_count") != n or n != xcells * ycells:
                fail(f"{sid}/{map_id}: size fields {row.get('sample_size_bytes')}/{row.get('value_count')} vs {n}")
            if row.get("sha256") != hashlib.sha256(data).hexdigest():
                fail(f"{sid}/{map_id}: sha256 mismatch")
            present = sorted(set(data))
            zero = data.count(0) / n
            if len(present) < MIN_DISTINCT:
                fail(f"{sid}/{map_id}: only {len(present)} distinct values (degenerate)")
            if zero > MAX_ZERO_FRACTION:
                fail(f"{sid}/{map_id}: zero (unindexed) share {zero:.3f} > {MAX_ZERO_FRACTION}")
            if row.get("min") != present[0] or row.get("max") != present[-1] or row.get("distinct_values") != len(present):
                fail(f"{sid}/{map_id}: index min/max/distinct disagree with data")
            if abs(row.get("zero_fraction", -1) - zero) > 1e-6:
                fail(f"{sid}/{map_id}: index zero_fraction disagrees")
            nonzero = [v for v in data if v]
            top = max(data.count(v) for v in present[1:]) if len(present) > 1 else n
            report.append(f"{field}={present[0]}..{present[-1]} distinct={len(present)} zero={zero:.4f} "
                          f"nonzero_mean={sum(nonzero) / max(1, len(nonzero)):.2f} top_nonzero_share={top / n:.4f}")
            totals[sid][0] += 1
            totals[sid][1] += n
        print(" ".join(report), flush=True)

    for r in sorted(rows, key=lambda r: (r["series_id"], r["map_id"])):
        agg.update((root / r["sample_path"]).read_bytes())
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    mseries = {s["id"]: s for s in manifest.get("series", [])}
    for _, sid in FIELD_SERIES:
        s = mseries.get(sid)
        if s is None:
            fail(f"manifest lacks series {sid}")
        if s.get("sample_count") != totals[sid][0] or s.get("total_size_bytes") != totals[sid][1]:
            fail(f"manifest {sid}: {s.get('sample_count')}/{s.get('total_size_bytes')} != realized {totals[sid]}")
        print(f"series={sid} samples={totals[sid][0]} bytes={totals[sid][1]}")
    print(f"aggregate_sha256={agg.hexdigest()}")
    print("verify_status=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
