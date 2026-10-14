#!/usr/bin/env python3
"""Independently re-derive and check every emitted SnowMicroPen force sample.

Re-selects the profiles from raw_data.csv (S36M, BestOfDay=1, Quality=1) plus
the PNT header gain (amplifier and sensor range 5000 pC), re-decodes each
local .PNT with struct (not array), and requires byte equality with the sample
file, consistent index fields, non-degenerate content, and manifest totals.

Usage: verify_smp.py <data_root> <recipe_dir>
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "slf_envidat_wfj_snowmicropen_force_i16"
SERIES_ID = "smp_s36m_force_counts_i16"


def fail(message: str) -> None:
    sys.exit(f"verify failed: {message}")


def main() -> None:
    data_root, recipe_dir = Path(sys.argv[1]), Path(sys.argv[2])
    downloads = data_root / "downloads" / DATASET_ID
    member_dir = downloads / "raw_data_members"
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = {s["id"]: s for s in manifest["series"]}[SERIES_ID]

    # Independent selection: CSV flags, then header gain on the local files.
    with open(downloads / "raw_data.csv", newline="", encoding="utf-8") as handle:
        csv_rows = [r for r in csv.DictReader(handle) if r["File"].startswith("S36M") and r["BestOfDay"] == "1"]
    if len(csv_rows) != 478:
        fail(f"raw_data.csv lists {len(csv_rows)} S36M BestOfDay=1 rows, expected 478")
    quality_paths = {r["Path"] for r in csv_rows if r["Quality"] == "1"}
    with open(recipe_dir / "members.tsv", newline="", encoding="utf-8") as handle:
        pinned = {m["zip_member"][len("raw_data/") :] for m in csv.DictReader(handle, delimiter="\t")}
    with open(recipe_dir / "excluded_gain10000.tsv", newline="", encoding="utf-8") as handle:
        excluded = {m["zip_member"][len("raw_data/") :] for m in csv.DictReader(handle, delimiter="\t")}
    # Quality=1 rows must split exactly into kept (gain 5000) and pinned gain-10000 exclusions.
    if pinned & excluded or (pinned | excluded) != quality_paths:
        fail(f"Quality=1 rows do not partition into kept/excluded: {sorted(quality_paths ^ (pinned | excluded))[:5]}")
    expected_paths = set()
    for rel in sorted(pinned):
        path = member_dir / rel
        if not path.is_file():
            fail(f"missing local member {rel}")
        with path.open("rb") as handle:
            head = handle.read(512)
        if struct.unpack(">hh", head[366:370]) != (5000, 5000):
            fail(f"{rel}: kept profile does not have gain 5000/5000")
        expected_paths.add(rel)
    stray = [p for p in member_dir.rglob("*") if p.is_file() and str(p.relative_to(member_dir)) not in pinned]
    if stray:
        fail(f"unexpected local members {stray[:3]}")

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(expected_paths):
        fail(f"index has {len(rows)} rows, expected {len(expected_paths)}")
    seen_members, seen_paths, seen_hashes = set(), set(), set()
    total_values = total_bytes = 0
    for row in rows:
        for key, value in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "int"),
                           ("bit_width", 16), ("endianness", "little"), ("element_size_bytes", 2)):
            if row.get(key) != value:
                fail(f"{row.get('sample_path')}: {key}={row.get(key)!r}")
        rel = row["source_zip_member"][len("raw_data/") :]
        if rel not in expected_paths or rel in seen_members:
            fail(f"unexpected or duplicate member {rel}")
        seen_members.add(rel)
        raw = (member_dir / rel).read_bytes()
        n = struct.unpack(">i", raw[358:362])[0]
        conv = struct.unpack(">f", raw[10:14])[0]
        if raw[256:264].decode("latin-1") != rel.split("/")[1][:8]:
            fail(f"{rel}: header filename mismatch")
        if not 0.00129 <= conv <= 0.00132 or conv != row["force_conv_factor"]:
            fail(f"{rel}: conversion factor {conv!r}")
        if n != row["value_count"] or 512 + 2 * n > len(raw):
            fail(f"{rel}: force count {n} vs index {row['value_count']}")
        values = struct.unpack(f">{n}h", raw[512 : 512 + 2 * n])
        expected = struct.pack(f"<{n}h", *values)
        sample_path = data_root / row["sample_path"]
        actual = sample_path.read_bytes()
        if actual != expected:
            fail(f"{rel}: sample bytes differ from independent decode")
        if row["sample_size_bytes"] != len(actual) or len(actual) != 2 * n:
            fail(f"{rel}: size fields")
        if hashlib.sha256(actual).hexdigest() != row["sha256"]:
            fail(f"{rel}: sha256")
        lo, hi, distinct = min(values), max(values), len(set(values))
        if (lo, hi, distinct) != (row["min"], row["max"], row["distinct_values"]):
            fail(f"{rel}: min/max/distinct mismatch")
        if distinct < 50 or hi - lo < 100:
            fail(f"{rel}: degenerate profile distinct={distinct} range={hi - lo}")
        top = collections.Counter(values).most_common(1)[0][1]
        if top > 0.5 * n:
            fail(f"{rel}: one value dominates the profile")
        if row["sha256"] in seen_hashes or row["sample_path"] in seen_paths:
            fail(f"{rel}: duplicate output")
        seen_hashes.add(row["sha256"])
        seen_paths.add(row["sample_path"])
        total_values += n
        total_bytes += len(actual)

    on_disk = {str(p.relative_to(data_root)) for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*")}
    if on_disk != seen_paths:
        fail(f"sample directory and index disagree: {sorted(on_disk ^ seen_paths)[:5]}")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != {len(rows)}/{total_bytes}")
    print(json.dumps({"verify": "ok", "samples": len(rows), "values": total_values, "bytes": total_bytes}))


if __name__ == "__main__":
    main()
