#!/usr/bin/env python3
"""Independent verification of the OzFlux L3 flux samples.

Re-decodes every local .dods payload with a separate implementation
(array('d') + byteswap rather than struct), applies the same missing-value
policy as the build (drop exact -9999.0, NaN/Inf and the NetCDF default fill;
skip pairs with < 1000 valid values), and byte-compares with each emitted
sample. Also checks the index, the gap sidecars, the manifest totals, and
rejects constant or degenerate series.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import sys
import tomllib
from pathlib import Path

DATASET_ID = "tern_ozflux_l3_eddy_covariance_fluxes_f64"
SERIES = {"Fco2": "ozflux_l3_fco2_f64", "Fe": "ozflux_l3_fe_f64", "Fh": "ozflux_l3_fh_f64"}
MISSING = {-9999.0, 9.969209968386869e36}
MIN_VALID = 1000
INDEX_KEYS = {"dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"}


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def decode(payload: bytes, var: str, n: int) -> array.array:
    marker = payload.index(b"Data:\n")
    header = payload[:marker].decode("ascii")
    want = f"Float64 {var}[time = {n}][latitude = 1][longitude = 1];"
    if header.count("[time = ") != 1 or want not in header:
        fail(f"{var}: DDS header mismatch")
    pos = marker + len(b"Data:\n")
    lengths = array.array("I")
    lengths.frombytes(payload[pos:pos + 8])
    if sys.byteorder == "little":
        lengths.byteswap()
    if list(lengths) != [n, n]:
        fail(f"{var}: XDR lengths {list(lengths)} != {n}")
    body = payload[pos + 8:]
    if len(body) != 8 * n:
        fail(f"{var}: body {len(body)} bytes != {8 * n}")
    values = array.array("d")
    values.frombytes(body)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    a = ap.parse_args()
    recipe = Path(a.recipe_dir)
    root = Path(a.data_root)
    files = [line.split("\t") for line in (recipe / "files.tsv").read_text().splitlines()
             if line and not line.startswith("#")]
    if len(files) != 51 or len({f[2] for f in files}) != 51:
        fail(f"files.tsv must list 51 distinct files, found {len(files)}")
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    index = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    by_key = {}
    for row in index:
        missing = INDEX_KEYS - row.keys()
        if missing:
            fail(f"index row lacks {sorted(missing)}")
        if (row["dataset_id"], row["numeric_kind"], row["bit_width"], row["endianness"],
                row["element_size_bytes"]) != (DATASET_ID, "float", 64, "little", 8):
            fail(f"index row type fields wrong: {row['sample_path']}")
        key = (row["series_id"], row["source_file"])
        if key in by_key:
            fail(f"duplicate index row {key}")
        by_key[key] = row
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    declared = {s["id"]: s for s in manifest["series"] if s.get("role") == "primary"}
    totals = {sid: [0, 0, 0] for sid in SERIES.values()}  # samples, bytes, values
    expected_rows = 0
    for site, release, name, url_path, length, step in files:
        n = int(length)
        stem = name[:-3]
        for var, sid in SERIES.items():
            src = root / "downloads" / DATASET_ID / site / f"{stem}.{var}.dods"
            values = decode(src.read_bytes(), var, n)
            valid = array.array("d", (v for v in values if math.isfinite(v) and v not in MISSING))
            fill_count = n - len(valid)
            key = (sid, name)
            if len(valid) < MIN_VALID:
                if key in by_key:
                    fail(f"{key} should have been skipped ({len(valid)} valid)")
                continue
            expected_rows += 1
            row = by_key.get(key)
            if row is None:
                fail(f"missing index row for {key}")
            if valid.itemsize != 8:
                fail("platform double is not 8 bytes")
            if sys.byteorder != "little":
                valid.byteswap()
            raw = valid.tobytes()
            sample = root / row["sample_path"]
            if row["sample_path"] != f"samples/{DATASET_ID}/{sid}/{stem}.f64":
                fail(f"unexpected sample path {row['sample_path']}")
            data = sample.read_bytes()
            if data != raw:
                fail(f"sample bytes differ from re-decoded source: {sample}")
            if row["value_count"] != len(valid) or row["sample_size_bytes"] != len(raw) \
                    or row["fill_count"] != fill_count or row["time_length"] != n \
                    or row["sha256"] != hashlib.sha256(raw).hexdigest():
                fail(f"index counters wrong for {key}")
            lo, hi = min(valid), max(valid)
            if row["min"] != lo or row["max"] != hi:
                fail(f"index min/max wrong for {key}")
            distinct = len(set(valid))
            if lo == hi or distinct < 0.2 * len(valid):
                fail(f"degenerate sample {key}: distinct={distinct} of {len(valid)}")
            if all(v == int(v) for v in valid[:5000]):
                fail(f"integral-only values in {key}")
            gaps = json.loads((root / "filtered" / DATASET_ID / "gaps" / sid / f"{stem}.json").read_text())
            if gaps["time_length"] != n or sum(r[1] for r in gaps["fill_runs"]) != fill_count:
                fail(f"gap sidecar inconsistent for {key}")
            for start, run in gaps["fill_runs"][:50]:
                if any(math.isfinite(values[i]) and values[i] not in MISSING for i in range(start, start + run)):
                    fail(f"gap sidecar marks valid values as fill in {key}")
            t = totals[sid]
            t[0] += 1; t[1] += len(raw); t[2] += len(valid)
    if expected_rows != len(index):
        fail(f"index has {len(index)} rows, expected {expected_rows}")
    for sid, (count, nbytes, nvalues) in totals.items():
        spec = declared.get(sid)
        if spec is None:
            fail(f"manifest lacks primary series {sid}")
        if spec["sample_count"] != count or spec["total_size_bytes"] != nbytes:
            fail(f"manifest {sid}: declared {spec['sample_count']}/{spec['total_size_bytes']} "
                 f"realized {count}/{nbytes}")
        sizes = sorted(r["value_count"] for r in index if r["series_id"] == sid)
        median = sizes[len(sizes) // 2]
        if median < 1000:
            fail(f"{sid}: median sample {median} values below floor")
        print(f"verify_ok {sid}: samples={count} values={nvalues} bytes={nbytes} median_values={median}")
    print(f"verify_ok rows={len(index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
