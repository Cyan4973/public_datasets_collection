#!/usr/bin/env python3
"""Independently re-derive and check every usgs_3dep_nc_geiger_laz_x_i32 sample.

For every pinned tile: re-decode the LAZ file with tools/laz/laszip.py, take X
with struct.iter_unpack('<i26x') (a different extraction path from the
byte-lane copy in build_samples.py), and compare value by value with the
stored sample. Also checks the shared missing-value policy (decoded count ==
header count; every X within the header X bounds in ticks, +-1), that the
decoded X extent matches the header bounds (+-2 ticks, a decoder-integrity
check), non-degeneracy (>= 1000 distinct values, no value above 50% of the
sample), the index rows (fields, sizes, sha256, min/max from the stored
int32) and the manifest totals.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import os
import struct
import sys
import tomllib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "laz"))
import laszip  # noqa: E402

DATASET_ID = "usgs_3dep_nc_geiger_laz_x_i32"
SERIES_ID = "nc_geiger_anson_2016_x_i32"
X_ONLY = struct.Struct("<i26x")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def verify_tile(job: tuple) -> dict:
    row, laz_path, sample_path, index_row = job
    name = row["file_name"]
    hdr = laszip.read_header(str(laz_path))
    if (hdr["point_format"], hdr["point_record_length"], hdr["scale"], hdr["offset"]) != (6, 30, (0.01, 0.01, 0.01), (0.0, 0.0, 0.0)):
        fail(f"{name}: header format/scale/offset changed")
    if hdr["system_identifier"] != "IntelliEarthGmAPDSensorS/N003":
        fail(f"{name}: system identifier {hdr['system_identifier']!r}")
    count = hdr["point_count"]
    if count != int(row["pc_count"]):
        fail(f"{name}: header count {count} != pinned {row['pc_count']}")
    derived = array.array("i")
    for _index, n, recs in laszip.iter_chunks(str(laz_path)):
        derived.extend(t[0] for t in X_ONLY.iter_unpack(recs[:30 * n]))
    if len(derived) != count:
        fail(f"{name}: decoded {len(derived)} points != header {count}")
    raw = sample_path.read_bytes()
    if len(raw) != 4 * count:
        fail(f"{name}: sample bytes {len(raw)} != 4 x {count}")
    stored = array.array("i")
    stored.frombytes(raw)
    if sys.byteorder != "little":
        stored.byteswap()
    if stored != derived:
        bad = next(i for i, (a, b) in enumerate(zip(stored, derived)) if a != b)
        fail(f"{name}: sample differs from re-decoded X at point {bad}")
    vmin, vmax = min(stored), max(stored)
    hmin, hmax = round(hdr["min"][0] / 0.01), round(hdr["max"][0] / 0.01)
    if vmin < hmin - 1 or vmax > hmax + 1:
        fail(f"{name}: X ticks {vmin}..{vmax} outside header bounds {hmin}..{hmax}")
    if abs(vmin - hmin) > 2 or abs(vmax - hmax) > 2:
        fail(f"{name}: decoded X extent {vmin}..{vmax} does not match header bounds {hmin}..{hmax}")
    span = vmax - vmin + 1
    if span > 50_000_000:
        fail(f"{name}: X span {span} ticks is implausible for a 2,500 ft tile")
    counts = array.array("I", bytes(4 * span))
    for value in stored:
        counts[value - vmin] += 1
    distinct = sum(1 for c in counts if c)
    top = max(counts)
    if distinct < 1000 or top * 2 > count:
        fail(f"{name}: degenerate sample (distinct={distinct}, top value share={top / count:.3f})")
    digest = hashlib.sha256(raw).hexdigest()
    for key, want in (("value_count", count), ("sample_size_bytes", len(raw)), ("min", vmin), ("max", vmax), ("sha256", digest)):
        if index_row.get(key) != want:
            fail(f"{name}: index {key}={index_row.get(key)!r} != {want!r}")
    return {"tile_id": row["tile_id"], "points": count, "distinct": distinct, "top_share": round(top / count, 5),
            "min": vmin, "max": vmax}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    data_root = Path(args.data_root)
    with open(args.sources, encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(sources):
        fail(f"index has {len(rows)} rows, sources.tsv pins {len(sources)} tiles")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    jobs = []
    for src, row in zip(sources, rows):
        stem = src["file_name"][:-len(".laz")]
        expected_path = f"samples/{DATASET_ID}/{SERIES_ID}/{stem}.x_i32le.bin"
        fixed = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": expected_path, "numeric_kind": "int",
                 "bit_width": 32, "endianness": "little", "element_size_bytes": 4, "tile_id": src["tile_id"],
                 "source_file": src["file_name"]}
        for key, want in fixed.items():
            if row.get(key) != want:
                fail(f"index row for {src['file_name']}: {key}={row.get(key)!r} != {want!r}")
        jobs.append((src, data_root / "downloads" / DATASET_ID / "laz" / src["file_name"], data_root / expected_path, row))
    if on_disk != sorted(Path(j[2]).name for j in jobs):
        fail("sample directory contents differ from the index")
    workers = args.workers or min(len(jobs), max(1, (os.cpu_count() or 2) - 1))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(verify_tile, jobs):
            results.append(result)
            print(f"ok tile={result['tile_id']} points={result['points']} distinct={result['distinct']} "
                  f"top_share={result['top_share']} x={result['min']}..{result['max']}", flush=True)
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series " + SERIES_ID)
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
             f"!= realized {len(rows)}/{total_bytes}")
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed the 1 GB cap")
    if len({(r['min'], r['max']) for r in results}) < 2:
        fail("all samples share identical extents")
    print(f"verify=ok samples={len(rows)} values={sum(r['value_count'] for r in rows)} bytes={total_bytes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
