#!/usr/bin/env python3
"""Independent verification for the Cassini RADAR BIBQH recipe.

Re-derives every sample without zipfile or the build's label parser: parses
the ZIP local file header by hand, inflates the raw DEFLATE stream with zlib,
checks CRC32 and the pinned IMG MD5, reads the attached PDS3 label with
independent regexes, recomputes the label CHECKSUM, and byte-compares the
image window against the emitted sample. Checks the index, manifest totals,
the shared missing-value policy (DN 0 = MISSING_CONSTANT, preserved), and
rejects constant, all-missing, or near-empty products.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bidr import (  # noqa: E402  (constants only; parsing is re-implemented here)
    DATASET_ID,
    EXPECTED_PIXEL_BYTES,
    EXPECTED_PRODUCTS,
    OFFSET,
    SCALING_FACTOR,
    SERIES_ID,
    SOURCES_SHA256,
)

CHUNK = 1 << 22
# Missing-value policy shared with build: DN 0 is MISSING_CONSTANT (outside the
# SAR swath in the oblique-cylindrical frame) and is preserved, never dropped.
# Degeneracy floor: a product must keep at least this fraction and count of
# non-missing pixels and a non-trivial spread of DN levels.
MIN_NONZERO_FRACTION = 0.01
MIN_NONZERO_COUNT = 100_000
MIN_DISTINCT_NONZERO = 64
REQUIRED_INDEX_KEYS = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
)


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def label_value(label: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", label, re.M)
    if match is None:
        fail(f"attached label lacks {key}")
    return match.group(1).strip().strip('"')


def inflate_member(zip_path: Path, row: dict):
    """Yield decompressed IMG chunks from the single ZIP member, by hand."""
    with zip_path.open("rb") as handle:
        header = handle.read(30)
        sig, _ver, flags, method, _t, _d, crc, csize, usize, name_len, extra_len = struct.unpack("<IHHHHHIIIHH", header)
        if sig != 0x04034B50:
            fail(f"{row['product_id']}: missing ZIP local file header")
        name = handle.read(name_len).decode("ascii")
        handle.read(extra_len)
        if name != row["product_id"] + ".IMG" or method != 8 or flags & 0x1:
            fail(f"{row['product_id']}: unexpected local member {name!r} method={method} flags={flags}")
        if not flags & 0x8 and (csize != int(row["zip_member_compressed_bytes"]) or usize != int(row["img_bytes"])):
            fail(f"{row['product_id']}: local header sizes disagree with pinned central directory")
        remaining = int(row["zip_member_compressed_bytes"])
        inflater = zlib.decompressobj(-15)
        while remaining:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                fail(f"{row['product_id']}: truncated DEFLATE stream")
            remaining -= len(data)
            out = inflater.decompress(data)
            if out:
                yield out
        tail = inflater.flush()
        if tail:
            yield tail
        if not inflater.eof or inflater.unused_data:
            fail(f"{row['product_id']}: DEFLATE stream did not end exactly at the member boundary")


def verify_product(zip_path: Path, sample_path: Path, row: dict) -> dict:
    pid = row["product_id"]
    crc = 0
    md5 = hashlib.md5()
    histogram: collections.Counter = collections.Counter()
    sha = hashlib.sha256()
    offset = 0
    window = None
    label = b""
    with sample_path.open("rb") as sample:
        for chunk in inflate_member(zip_path, row):
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            if window is None:
                label += chunk
                end = re.search(rb"\r\nEND\r\n", label)
                if end is None:
                    if len(label) > 65536:
                        fail(f"{pid}: attached label END not found")
                    continue
                text = label[: end.end()].decode("ascii")
                checks = {
                    "PRODUCT_ID": pid,
                    "TARGET_NAME": "TITAN",
                    "DATA_SET_ID": "CO-SSA-RADAR-5-BIDR-V1.0",
                    "SAMPLE_TYPE": "UNSIGNED_INTEGER",
                    "SAMPLE_BITS": "8",
                    "SCALING_FACTOR": SCALING_FACTOR,
                    "OFFSET": OFFSET,
                    "MISSING_CONSTANT": "0",
                    "MAP_RESOLUTION": "128.0<PIX/DEG>",
                }
                for key, expected in checks.items():
                    if label_value(text, key) != expected:
                        fail(f"{pid}: attached label {key}={label_value(text, key)!r} != {expected!r}")
                record_bytes = int(label_value(text, "RECORD_BYTES"))
                file_records = int(label_value(text, "FILE_RECORDS"))
                label_records = int(label_value(text, "LABEL_RECORDS"))
                image_record = int(label_value(text, "^IMAGE"))
                lines = int(label_value(text, "LINES"))
                samples = int(label_value(text, "LINE_SAMPLES"))
                checksum = int(label_value(text, "CHECKSUM"))
                if record_bytes * file_records != int(row["img_bytes"]):
                    fail(f"{pid}: RECORD_BYTES*FILE_RECORDS != IMG size")
                if image_record != label_records + 1:
                    fail(f"{pid}: ^IMAGE does not follow the label records")
                if label_records + -(-lines * samples // record_bytes) != file_records:
                    fail(f"{pid}: FILE_RECORDS inconsistent with LINES*LINE_SAMPLES")
                window = ((image_record - 1) * record_bytes, lines * samples)
                chunk = label
                label = b""
            begin = offset
            offset += len(chunk)
            lo, hi = max(window[0], begin), min(window[0] + window[1], offset)
            if lo < hi:
                piece = chunk[lo - begin : hi - begin]
                if sample.read(len(piece)) != piece:
                    fail(f"{pid}: emitted sample differs from source image bytes")
                histogram.update(piece)
                sha.update(piece)
        if sample.read(1):
            fail(f"{pid}: emitted sample longer than the source image")
    if window is None or offset != int(row["img_bytes"]):
        fail(f"{pid}: decoded IMG length {offset} != {row['img_bytes']}")
    if f"{crc & 0xFFFFFFFF:08x}" != row["zip_member_crc32"]:
        fail(f"{pid}: CRC32 mismatch")
    if md5.hexdigest() != row["img_md5"]:
        fail(f"{pid}: decoded IMG MD5 != pinned ETag")
    total = sum(v * c for v, c in histogram.items())
    if total & 0xFFFFFFFF != checksum:
        fail(f"{pid}: pixel sum {total} != label CHECKSUM {checksum}")
    values = sum(histogram.values())
    nonzero = values - histogram.get(0, 0)
    distinct_nonzero = len([v for v in histogram if v])
    if values != window[1] or len(histogram) < 2:
        fail(f"{pid}: constant or short image")
    if nonzero < MIN_NONZERO_COUNT or nonzero / values < MIN_NONZERO_FRACTION:
        fail(f"{pid}: only {nonzero} non-missing pixels ({nonzero / values:.4%})")
    if distinct_nonzero < MIN_DISTINCT_NONZERO:
        fail(f"{pid}: only {distinct_nonzero} distinct non-missing DN levels")
    return {
        "lines": lines,
        "line_samples": samples,
        "value_count": values,
        "missing_count": histogram.get(0, 0),
        "nonzero_count": nonzero,
        "distinct_values": len(histogram),
        "distinct_nonzero_values": distinct_nonzero,
        "min": min(histogram),
        "max": max(histogram),
        "nonzero_min": min(v for v in histogram if v),
        "nonzero_max": max(histogram),
        "floor_dn1_count": histogram.get(1, 0),
        "sha256": sha.hexdigest(),
        "label_checksum": checksum,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    recipe = Path(args.recipe_dir)
    data_root = Path(args.data_root).resolve()

    raw = (recipe / "sources.tsv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCES_SHA256:
        fail("sources.tsv identity changed")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines(), delimiter="\t"))
    if len(rows) != EXPECTED_PRODUCTS:
        fail("source plan size changed")

    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        fail("manifest must declare exactly the one primary series")
    series = series[0]
    if (series["role"], series["numeric_kind"], series["bit_width"]) != ("primary", "uint", 8):
        fail("manifest series role/kind/width mismatch")

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(rows):
        fail(f"index has {len(index)} rows, expected {len(rows)}")
    series_dir = data_root / series["output_path"]
    expected_files = set()
    total_bytes = 0
    total_missing = 0
    for row, entry in zip(rows, index):
        missing_keys = [k for k in REQUIRED_INDEX_KEYS if k not in entry]
        if missing_keys:
            fail(f"index row lacks {missing_keys}")
        name = f"{int(row['ordinal']):02d}_{row['product_id']}.u8"
        expected_files.add(name)
        sample_path = series_dir / name
        if entry["sample_path"] != str(sample_path.relative_to(data_root)):
            fail(f"index sample_path mismatch for {row['product_id']}")
        fixed = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1, "product_id": row["product_id"],
            "flyby": row["flyby"], "segment": row["segment"], "missing_constant": 0,
        }
        for key, value in fixed.items():
            if entry.get(key) != value:
                fail(f"index {key}={entry.get(key)!r} for {row['product_id']}, expected {value!r}")
        zip_path = data_root / "downloads" / DATASET_ID / f"{row['product_id']}.ZIP"
        stats = verify_product(zip_path, sample_path, row)
        if [stats["lines"], stats["line_samples"]] != entry.get("sample_shape"):
            fail(f"index sample_shape mismatch for {row['product_id']}")
        if stats["lines"] != int(row["lines"]) or stats["line_samples"] != int(row["line_samples"]):
            fail(f"pinned geometry mismatch for {row['product_id']}")
        size = sample_path.stat().st_size
        if size != stats["value_count"] or entry["sample_size_bytes"] != size or entry["value_count"] != size:
            fail(f"size/value_count mismatch for {row['product_id']}")
        for key in ("missing_count", "nonzero_count", "distinct_values", "distinct_nonzero_values", "min", "max",
                    "nonzero_min", "nonzero_max", "floor_dn1_count", "sha256", "label_checksum"):
            if entry.get(key) != stats[key]:
                fail(f"index {key}={entry.get(key)!r} != recomputed {stats[key]!r} for {row['product_id']}")
        total_bytes += size
        total_missing += stats["missing_count"]
        print(
            f"verified {row['ordinal']:>2} {row['product_id']} {stats['lines']}x{stats['line_samples']} "
            f"missing={stats['missing_count'] / size:.4f} distinct_nonzero={stats['distinct_nonzero_values']}"
        )
    actual_files = {p.name for p in series_dir.iterdir()}
    if actual_files != expected_files:
        fail(f"unexpected files in series dir: {sorted(actual_files ^ expected_files)[:5]}")
    if total_bytes != EXPECTED_PIXEL_BYTES:
        fail("total primary bytes differ from pinned aggregate")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        fail("manifest sample_count/total_size_bytes do not match realized output")
    print(
        f"verify_ok samples={len(rows)} bytes={total_bytes} "
        f"missing_fraction={total_missing / total_bytes:.4f}"
    )


if __name__ == "__main__":
    main()
