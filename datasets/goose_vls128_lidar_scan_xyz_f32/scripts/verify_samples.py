#!/usr/bin/env python3
"""Independently re-derive and check GOOSE VLS-128 sweep xyz float32 samples.

This verifier does not import the build code. It checks every source payload
against the CRC32 in sources.tsv and the SHA-256 in payload_sha256.tsv
(recorded from the first accepted download), then re-derives every expected
sample by slicing the first 12 bytes of each 16-byte source point record (no
float conversion), compares the result byte-for-byte with the sample file, and
re-checks the shared missing-value policy on raw IEEE-754 bit patterns:
non-finite fields (exponent bits all ones) and all-zero (x = y = z = +/-0)
points are fatal. It also rejects constant samples or axes, checks index
fields, min/max from the stored float32 values, SHA-256 digests, the sample
directory inventory, and the manifest's declared sample_count and
total_size_bytes.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import struct
import sys
import tomllib
import zlib
from array import array
from pathlib import Path

DATASET_ID = "goose_vls128_lidar_scan_xyz_f32"
SERIES_ID = "goose_vls128_sweep_xyz_f32"
INDEX_KEYS = {
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
}
EXPONENT_MASK = 0x7F800000
MAGNITUDE_MASK = 0x7FFFFFFF


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def uint32_words(raw: bytes) -> array:
    words = array("I")
    if words.itemsize != 4:
        words = array("L")
        if words.itemsize != 4:
            fail("no 32-bit unsigned array type on this platform")
    words.frombytes(raw)
    if sys.byteorder != "little":
        words.byteswap()
    return words


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
    series = {entry["id"]: entry for entry in manifest.get("series", [])}
    if set(series) != {SERIES_ID}:
        fail(f"manifest series {sorted(series)} != [{SERIES_ID}]")
    declared = series[SERIES_ID]
    if (declared.get("role"), declared.get("numeric_kind"), declared.get("bit_width"), declared.get("endianness")) != (
        "primary",
        "float",
        32,
        "little",
    ):
        fail("manifest series must be primary little-endian float32")

    license_text = (download_dir / "meta" / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("Attribution-ShareAlike 4.0 International"):
        fail("downloaded LICENSE member is not CC BY-SA 4.0")

    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    per_sequence = collections.Counter(row["sequence"] for row in sources)
    if len(per_sequence) != 8 or set(per_sequence.values()) != {8}:
        fail(f"sources.tsv must pin 8 sweeps per val sequence, got {dict(per_sequence)}")
    if len({row["member_name"] for row in sources}) != len(sources):
        fail("duplicate member in sources.tsv")
    with args.payload_sha256.open(encoding="utf-8", newline="") as handle:
        pinned_sha256 = {row["member_name"]: row for row in csv.DictReader(handle, delimiter="\t")}
    if set(pinned_sha256) != {row["member_name"] for row in sources}:
        fail("payload_sha256.tsv does not cover exactly the pinned members")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_member = {}
    for row in index_rows:
        missing = INDEX_KEYS - set(row)
        if missing:
            fail(f"index row missing {sorted(missing)}")
        if row["source_member"] in by_member:
            fail(f"duplicate index row for {row['source_member']}")
        by_member[row["source_member"]] = row
    if set(by_member) != {row["member_name"] for row in sources}:
        fail("index rows do not correspond one-to-one with pinned sources")

    expected_files = set()
    total_bytes = total_values = 0
    for source in sources:
        name = source["member_name"]
        base = Path(name).name
        if not name.startswith(f"lidar/val/{source['sequence']}/") or not base.endswith("_vls128.bin"):
            fail(f"unexpected member path {name}")
        payload = (download_dir / "lidar" / "val" / source["sequence"] / base).read_bytes()
        if len(payload) != int(source["payload_bytes"]) or len(payload) % 16:
            fail(f"{base}: payload size {len(payload)}")
        if f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}" != source["crc32"]:
            fail(f"{base}: payload CRC32 mismatch")
        pinned = pinned_sha256[name]
        if int(pinned["payload_bytes"]) != len(payload) or hashlib.sha256(payload).hexdigest() != pinned["sha256"]:
            fail(f"{base}: payload SHA-256 differs from payload_sha256.tsv")
        points = len(payload) // 16
        view = memoryview(payload)
        expected = b"".join(view[offset : offset + 12] for offset in range(0, len(payload), 16))

        row = by_member[name]
        sample_path = data_root / row["sample_path"]
        if sample_path.parent != series_dir:
            fail(f"{base}: sample outside series directory")
        expected_files.add(sample_path.name)
        actual = sample_path.read_bytes()
        if actual != expected:
            fail(f"{base}: sample bytes differ from source xyz fields")
        if (
            row["dataset_id"] != DATASET_ID
            or row["series_id"] != SERIES_ID
            or row["numeric_kind"] != "float"
            or int(row["bit_width"]) != 32
            or row["endianness"] != "little"
            or int(row["element_size_bytes"]) != 4
            or int(row["sample_size_bytes"]) != len(actual)
            or int(row["value_count"]) != 3 * points
            or int(row.get("point_count", -1)) != points
            or row.get("sample_shape") != [points, 3]
        ):
            fail(f"{base}: index fields disagree with sample")
        if row.get("sha256") != hashlib.sha256(actual).hexdigest():
            fail(f"{base}: sha256 mismatch")

        words = uint32_words(actual)
        if any((word & EXPONENT_MASK) == EXPONENT_MASK for word in words):
            fail(f"{base}: non-finite xyz value (fatal by policy)")
        remission_words = uint32_words(payload)[3::4]
        if any((word & EXPONENT_MASK) == EXPONENT_MASK for word in remission_words):
            fail(f"{base}: non-finite remission field in source record (fatal by policy)")
        xw, yw, zw = words[0::3], words[1::3], words[2::3]
        if any(((x | y | z) & MAGNITUDE_MASK) == 0 for x, y, z in zip(xw, yw, zw)):
            fail(f"{base}: all-zero padding point (fatal by policy)")
        floats = struct.unpack(f"<{3 * points}f", actual)
        for axis in range(3):
            column = floats[axis::3]
            if min(column) == max(column):
                fail(f"{base}: constant axis {axis}")
        if min(floats) != row.get("min") or max(floats) != row.get("max"):
            fail(f"{base}: index min/max do not match stored float32 values")
        total_bytes += len(actual)
        total_values += 3 * points

    present = {path.name for path in series_dir.iterdir()} if series_dir.is_dir() else set()
    if present != expected_files:
        fail(f"sample directory inventory mismatch: extra={sorted(present - expected_files)[:5]} missing={sorted(expected_files - present)[:5]}")
    if int(declared.get("sample_count", -1)) != len(index_rows):
        fail(f"manifest sample_count {declared.get('sample_count')} != {len(index_rows)}")
    if int(declared.get("total_size_bytes", -1)) != total_bytes:
        fail(f"manifest total_size_bytes {declared.get('total_size_bytes')} != {total_bytes}")
    counts = sorted(int(row["value_count"]) for row in index_rows)
    median = (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2
    if total_values < 10_000 or median < 1_000 or total_bytes > 1_000_000_000:
        fail(f"floor/cap violated: values={total_values} median={median} bytes={total_bytes}")
    print(
        f"verify_ok samples={len(index_rows)} sequences={len(per_sequence)} points={total_values // 3} "
        f"values={total_values} bytes={total_bytes} median_values={median}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
