#!/usr/bin/env python3
"""Independent verifier for noaa_goes16_xrs_1s_flux_f32.

Re-decodes every inventory file without the build module: variables are
resolved through the creation-order link index (build uses the name index),
the chunk is inflated in one call and un-shuffled with a per-element gather,
and missing values are classified from the raw float32 bit patterns.  Every
sample is byte-compared, the day-exclusion policy is re-applied, and index
rows, ingest_stats.json and manifest counts must agree exactly.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from h5lite import H5Error, H5File  # noqa: E402

DATASET_ID = "noaa_goes16_xrs_1s_flux_f32"
N = 86400
VARIABLES = {"goes16_xrsa_flux_1s_f32": "xrsa_flux", "goes16_xrsb_flux_1s_f32": "xrsb_flux"}
F32_TYPE = bytes.fromhex("11201f000400000000002000170800177f000000")
FILL_WORD = 0xC61C3C00  # float32 -9999.0
LICENSE_ATTR = "These data may be redistributed and used without restriction. "
MAX_MISSING = 0.5
MIN_DISTINCT = 100
INDEX_KEYS = {"dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count", "date", "source_file",
              "source_variable", "fill_count", "nan_count", "min", "max"}


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def decode(raw: bytes, filename: str, date: str) -> dict[str, bytes]:
    f = H5File(raw)
    links = f.links(f.root_addr, "creation_order")
    attrs = f.attributes(f.root_addr)
    if attrs.get("id") != filename or attrs.get("platform") != "g16" or attrs.get("license") != LICENSE_ATTR:
        fail(f"{filename}: global id/platform/license attributes")
    if attrs.get("time_coverage_start") != f"{date}T00:00:00.000Z":
        fail(f"{filename}: time_coverage_start {attrs.get('time_coverage_start')!r}")
    out = {}
    for sid, variable in VARIABLES.items():
        info = f.dataset(links[variable])
        if info["shape"] != (N,) or info["datatype"] != F32_TYPE:
            fail(f"{filename}:{variable}: shape/datatype")
        if [fid for fid, _fl, _v in info["filters"]] != [2, 1] or info["filters"][0][2] != (4,):
            fail(f"{filename}:{variable}: filter pipeline {info['filters']}")
        entries, _final = f.chunk_index(info["chunk_btree"], 2)
        if len(entries) != 1 or entries[0][1] != 0:
            fail(f"{filename}:{variable}: chunk index")
        size, _mask, _offsets, addr = entries[0]
        plain = zlib.decompress(raw[addr:addr + size])
        if len(plain) != 4 * N:
            fail(f"{filename}:{variable}: inflated length {len(plain)}")
        lanes = [plain[k * N:(k + 1) * N] for k in range(4)]
        out[sid] = b"".join(bytes((lanes[0][i], lanes[1][i], lanes[2][i], lanes[3][i])) for i in range(N))
    return out


def classify(payload: bytes) -> dict:
    words = struct.unpack(f"<{N}I", payload)
    fill = nan = 0
    valid_words = []
    for w in words:
        if w == FILL_WORD:
            fill += 1
        elif (w & 0x7F800000) == 0x7F800000:
            if w & 0x007FFFFF:
                nan += 1
            else:
                fail("infinite value in sample")
        else:
            valid_words.append(w)
    valid = struct.unpack(f"<{len(valid_words)}f", struct.pack(f"<{len(valid_words)}I", *valid_words))
    return {"fill": fill, "nan": nan, "distinct": len(set(valid_words)),
            "min": min(valid) if valid else None, "max": max(valid) if valid else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID / "daily"
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id")
    lines = Path(args.inventory).read_text(encoding="utf-8").splitlines()[1:]
    inventory = [line.split("\t") for line in lines]

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    by_key = {}
    for row in rows:
        if set(row) != INDEX_KEYS:
            fail(f"index row keys {sorted(row)}")
        key = (row["series_id"], row["date"])
        if key in by_key:
            fail(f"duplicate index row {key}")
        by_key[key] = row

    expected_rows = 0
    excluded = []
    for number, (date, filename, size, sha) in enumerate(inventory, 1):
        path = downloads / filename
        raw = path.read_bytes()
        if len(raw) != int(size):
            fail(f"{filename}: size {len(raw)} != {size}")
        try:
            payloads = decode(raw, filename, date)
        except (H5Error, KeyError, struct.error, IndexError, zlib.error) as exc:
            fail(f"{filename}: {exc}")
        classes = {sid: classify(p) for sid, p in payloads.items()}
        keep = all((c["fill"] + c["nan"]) / N <= MAX_MISSING for c in classes.values()) and all(
            c["distinct"] >= MIN_DISTINCT for c in classes.values())
        if not keep:
            excluded.append(date)
            for sid in VARIABLES:
                if (sid, date) in by_key:
                    fail(f"{date}: day should be excluded but is indexed for {sid}")
            continue
        for sid, payload in payloads.items():
            row = by_key.get((sid, date))
            if row is None:
                fail(f"missing index row for {sid} {date}")
            expected_rows += 1
            rel = f"samples/{DATASET_ID}/{sid}/{date.replace('-', '')}.f32"
            if row["sample_path"] != rel or row["source_file"] != filename or row["source_variable"] != VARIABLES[sid]:
                fail(f"{sid} {date}: index path/source fields")
            if (row["dataset_id"], row["numeric_kind"], row["bit_width"], row["endianness"],
                    row["element_size_bytes"], row["sample_size_bytes"], row["value_count"]) != (
                    DATASET_ID, "float", 32, "little", 4, 4 * N, N):
                fail(f"{sid} {date}: index typing fields")
            sample = (data_root / rel).read_bytes()
            if sample != payload:
                fail(f"{sid} {date}: sample bytes differ from independent decode")
            c = classes[sid]
            if (row["fill_count"], row["nan_count"], row["min"], row["max"]) != (c["fill"], c["nan"], c["min"], c["max"]):
                fail(f"{sid} {date}: index fill/nan/min/max disagree with recount")
            if sample == sample[:4] * N:
                fail(f"{sid} {date}: constant sample")
        if number % 25 == 0:
            print(f"verified {number}/{len(inventory)}")
    if expected_rows != len(rows):
        fail(f"index has {len(rows)} rows, expected {expected_rows}")
    for sid in VARIABLES:
        files = sorted((data_root / "samples" / DATASET_ID / sid).iterdir())
        if len(files) != len(inventory) - len(excluded):
            fail(f"{sid}: {len(files)} sample files on disk, expected {len(inventory) - len(excluded)}")

    stats = json.loads((data_root / "filtered" / DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    if [item["date"] for item in stats["excluded_days"]] != excluded:
        fail("ingest_stats excluded_days disagree with the re-applied policy")
    declared = {s["id"]: s for s in manifest.get("series", [])}
    if set(declared) != set(VARIABLES):
        fail(f"manifest series {sorted(declared)}")
    for sid in VARIABLES:
        count = sum(1 for row in rows if row["series_id"] == sid)
        size = sum(row["sample_size_bytes"] for row in rows if row["series_id"] == sid)
        if declared[sid].get("sample_count") != count or declared[sid].get("total_size_bytes") != size:
            fail(f"{sid}: manifest sample_count/total_size_bytes {declared[sid].get('sample_count')}/"
                 f"{declared[sid].get('total_size_bytes')} != realized {count}/{size}")
        lows = {row["min"] for row in rows if row["series_id"] == sid}
        if len({(row["min"], row["max"]) for row in rows if row["series_id"] == sid}) < 2 or len(lows) < 2:
            fail(f"{sid}: degenerate series (identical per-day ranges)")
        print(f"series {sid}: samples={count} bytes={size}")
    print(f"verify=ok days={len(inventory)} excluded={len(excluded)} rows={len(rows)}")


if __name__ == "__main__":
    main()
