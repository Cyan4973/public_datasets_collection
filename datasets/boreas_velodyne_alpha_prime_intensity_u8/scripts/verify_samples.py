#!/usr/bin/env python3
"""Independently re-derive and check Boreas Alpha Prime intensity uint8 samples.

This verifier does not import the build code. For every pinned sweep it
re-checks the source file's size and MD5 (sources.tsv) and, when present, the
SHA-256 recorded in payload_sha256.tsv; decodes every 24-byte point with
struct.iter_unpack('<6f'); re-applies the shared policy (all six fields
finite, intensity an integer in 0..255, laser_number an integer in 0..127;
violations are fatal, never clamped); rebuilds the expected uint8 sample from
field 3 in point order and compares it byte-for-byte with the sample file.
It also rejects constant or single-value-dominated samples (mode fraction
> 0.80), checks index fields, SHA-256, min/max, zero fraction, the sample
directory inventory, the 44-sequence x 6-sweep scope, and the manifest's
declared sample_count and total_size_bytes.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "boreas_velodyne_alpha_prime_intensity_u8"
SERIES_ID = "boreas_alpha_prime_sweep_intensity_u8"
SEQUENCES = 44
PER_SEQUENCE = 6
MAX_MODE_FRACTION = 0.80
INDEX_KEYS = {"dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"}
ERA = re.compile(r"^boreas-(2020-1[12]|2021-(0[1-9]|1[01]))-\d{2}-\d{2}-\d{2}$")


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--payload-sha256", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = {e["id"]: e for e in manifest.get("series", [])}
    if set(series) != {SERIES_ID}:
        fail(f"manifest series {sorted(series)} != [{SERIES_ID}]")
    decl = series[SERIES_ID]
    if (decl.get("role"), decl.get("numeric_kind"), decl.get("bit_width"), decl.get("endianness")) != (
            "primary", "uint", 8, "little"):
        fail("manifest series must be primary little-endian uint8")

    lic = (download_dir / "meta" / "DATA_LICENSE.md").read_text(encoding="utf-8")
    if "Creative Commons Attribution 4.0 International Public License" not in lic:
        fail("downloaded DATA_LICENSE.md does not state CC BY 4.0")

    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    per_seq = collections.Counter(r["sequence"] for r in sources)
    if len(per_seq) != SEQUENCES or set(per_seq.values()) != {PER_SEQUENCE}:
        fail(f"sources.tsv must pin {PER_SEQUENCE} sweeps for each of {SEQUENCES} sequences")
    for seq in per_seq:
        if not ERA.match(seq):
            fail(f"sequence {seq} outside the 2020-11..2021-11 Alpha Prime era")
    if len({r["key"] for r in sources}) != len(sources):
        fail("duplicate key in sources.tsv")
    pinned_sha = {}
    if args.payload_sha256.is_file():
        with args.payload_sha256.open(encoding="utf-8", newline="") as handle:
            pinned_sha = {r["key"]: r for r in csv.DictReader(handle, delimiter="\t")}
        if set(pinned_sha) != {r["key"] for r in sources}:
            fail("payload_sha256.tsv does not cover exactly the pinned keys")
    else:
        print("note: payload_sha256.tsv absent; relying on pinned size + MD5")

    index_rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_key = {}
    for row in index_rows:
        missing = INDEX_KEYS - set(row)
        if missing:
            fail(f"index row missing {sorted(missing)}")
        if row["source_key"] in by_key:
            fail(f"duplicate index row for {row['source_key']}")
        by_key[row["source_key"]] = row
    if set(by_key) != {r["key"] for r in sources}:
        fail("index rows do not correspond one-to-one with pinned sources")

    expected_files = set()
    total = 0
    counts = []
    zero_fracs = []
    for src in sources:
        key = src["key"]
        path = download_dir / src["sequence"] / f"{src['timestamp_us']}.bin"
        payload = path.read_bytes()
        if len(payload) != int(src["size_bytes"]) or len(payload) % 24 or not payload:
            fail(f"{key}: payload size {len(payload)}")
        if hashlib.md5(payload).hexdigest() != src["md5"]:
            fail(f"{key}: MD5 mismatch")
        if pinned_sha and hashlib.sha256(payload).hexdigest() != pinned_sha[key]["sha256"]:
            fail(f"{key}: SHA-256 differs from payload_sha256.tsv")
        expected = bytearray()
        for i, (x, y, z, inten, ring, t) in enumerate(struct.iter_unpack("<6f", payload)):
            if not all(math.isfinite(v) for v in (x, y, z, inten, ring, t)):
                fail(f"{key}: non-finite field at point {i}")
            if not (0.0 <= inten <= 255.0) or inten != math.floor(inten):
                fail(f"{key}: point {i} intensity {inten!r} not an integer in 0..255")
            if not (0.0 <= ring <= 127.0) or ring != math.floor(ring):
                fail(f"{key}: point {i} laser_number {ring!r} not an integer in 0..127")
            expected.append(int(inten))
        n = len(payload) // 24
        if n != int(src["point_count"]):
            fail(f"{key}: point count mismatch")

        row = by_key[key]
        sample_path = data_root / row["sample_path"]
        if sample_path.parent != series_dir:
            fail(f"{key}: sample outside series directory")
        if sample_path.name != f"{src['sequence']}__{src['timestamp_us']}.u8":
            fail(f"{key}: unexpected sample name {sample_path.name}")
        expected_files.add(sample_path.name)
        actual = sample_path.read_bytes()
        if actual != bytes(expected):
            fail(f"{key}: sample bytes differ from source intensity field")
        freq = collections.Counter(actual)
        if len(freq) < 2:
            fail(f"{key}: constant sample")
        mode_frac = max(freq.values()) / n
        if mode_frac > MAX_MODE_FRACTION:
            fail(f"{key}: single value dominates ({mode_frac:.3f})")
        zf = freq.get(0, 0) / n
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": n, "value_count": n,
            "sha256": hashlib.sha256(actual).hexdigest(), "min": min(freq), "max": max(freq),
            "source_md5": src["md5"], "sequence": src["sequence"], "timestamp_us": src["timestamp_us"],
            "distinct_values": len(freq),
        }
        for field, want in checks.items():
            if row.get(field) != want:
                fail(f"{key}: index {field}={row.get(field)!r} expected {want!r}")
        if abs(row["zero_fraction"] - zf) > 1e-6:
            fail(f"{key}: index zero_fraction mismatch")
        total += n
        counts.append(n)
        zero_fracs.append(zf)

    actual_files = {p.name for p in series_dir.iterdir()}
    if actual_files != expected_files:
        fail(f"sample directory inventory mismatch: extra={sorted(actual_files - expected_files)[:5]} "
             f"missing={sorted(expected_files - actual_files)[:5]}")
    if decl.get("sample_count") != len(sources):
        fail(f"manifest sample_count {decl.get('sample_count')} != {len(sources)}")
    if decl.get("total_size_bytes") != total:
        fail(f"manifest total_size_bytes {decl.get('total_size_bytes')} != {total}")
    counts.sort()
    m = len(counts)
    median = counts[m // 2] if m % 2 else (counts[m // 2 - 1] + counts[m // 2]) / 2
    if total < 100_000 or median < 1000:
        fail("below acceptance floor")
    if total > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    zero_fracs.sort()
    print(f"verify ok: samples={m} total_bytes={total} median_values={median} "
          f"zero_fraction min={zero_fracs[0]:.4f} median={zero_fracs[m // 2]:.4f} max={zero_fracs[-1]:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
