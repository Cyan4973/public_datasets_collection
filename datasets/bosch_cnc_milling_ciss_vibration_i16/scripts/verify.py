#!/usr/bin/env python3
"""Independently re-derive and check the CNC vibration int16 samples.

For every pinned source file: re-check size and git blob SHA-1, decode the
HDF5 dataset again, convert with a separate code path (``struct`` unpack,
per-value ``is_integer``/range checks, explicit little-endian ``<h`` pack),
re-apply the same keep/drop policy as build.py and require byte-identical
sample files, exact index metadata, matching drop records, no stray files,
non-degenerate samples, the repository floors and cap, and agreement with
manifest.toml.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cnc_h5  # noqa: E402

DATASET_ID = "bosch_cnc_milling_ciss_vibration_i16"
SERIES_ID = "cnc_ciss_vibration_xyz_i16"
EXPECTED_FILES = 1163
UNPACK = {"float32": ("f", "I", 0x80000000), "float64": ("d", "Q", 0x8000000000000000), "int64": ("q", None, None)}
TYPECODES = {"float32": "f", "float64": "d", "int64": "q"}


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def convert(raw: bytes, dtype: str) -> tuple[bytes | None, str, int]:
    """Return (expected int16 LE bytes or None, drop reason, negative-zero count)."""
    fmt, bits_fmt, negzero_bits = UNPACK[dtype]
    n = len(raw) // struct.calcsize(fmt)
    values = struct.unpack(f"<{n}{fmt}", raw)
    negative_zeros = 0
    reasons = []
    if fmt in "fd":
        if not all(map(float.is_integer, values)):  # False for NaN, +/-inf and fractions
            finite = [v for v in values if v == v and v not in (float("inf"), float("-inf"))]
            if len(finite) != n:
                reasons.append("non_finite")
            if not all(map(float.is_integer, finite)):
                reasons.append("non_integral")
            ints = [int(v) for v in finite if v.is_integer()]
        else:
            ints = list(map(int, values))
        negative_zeros = struct.unpack(f"<{n}{bits_fmt}", raw).count(negzero_bits)
    else:
        ints = list(values)
    if ints and (min(ints) < -32768 or max(ints) > 32767):
        reasons.append("out_of_int16")
    if reasons:
        return None, "+".join(reasons), negative_zeros
    return struct.pack(f"<{n}h", *ints), "", negative_zeros


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    args = parser.parse_args()
    data_root = Path(args.data_dir) if Path(args.data_dir).is_absolute() else args.repo_root / args.data_dir
    data_root = data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    output_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    for required in (index_path, stats_path, output_dir):
        if not required.exists():
            fail(f"missing {required}; run download.sh and build.sh first")

    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series with the expected id")
    series_decl = series[0]
    if (series_decl.get("numeric_kind"), series_decl.get("bit_width"), series_decl.get("endianness")) != ("int", 16, "little"):
        fail("manifest numeric representation mismatch")

    with (args.recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    if len(sources) != EXPECTED_FILES:
        fail(f"sources.tsv has {len(sources)} rows")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_source = {}
    for row in index_rows:
        if row.get("source_path") in by_source:
            fail(f"duplicate index row for {row.get('source_path')}")
        by_source[row.get("source_path")] = row
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats_dropped = {d["source_path"]: d["reason"] for d in stats.get("dropped", [])}

    seen_hashes: dict[str, str] = {}
    expected_files: set[Path] = set()
    expected_drops: dict[str, str] = {}
    aggregate = hashlib.sha256()
    counts: list[int] = []
    negative_zero_total = 0
    for number, src in enumerate(sources, 1):
        buf = (download_dir / src["path"]).read_bytes()
        if len(buf) != int(src["size_bytes"]):
            fail(f"size mismatch {src['path']}")
        if hashlib.sha1(b"blob %d\x00" % len(buf) + buf).hexdigest() != src["git_blob_sha1"]:
            fail(f"git blob SHA-1 mismatch {src['path']}")
        decoded = cnc_h5.decode_file(buf)
        rows = int(src["rows"])
        if decoded.root_links != ["vibration_data"] or decoded.dataset.shape != (rows, 3):
            fail(f"structure mismatch {src['path']}: {decoded.root_links} {decoded.dataset.shape}")
        if decoded.dataset.typecode != TYPECODES[src["container_dtype"]]:
            fail(f"container dtype mismatch {src['path']}")
        expected, reason, negative_zeros = convert(decoded.raw, src["container_dtype"])
        if expected is not None:
            out_values = struct.unpack(f"<{rows * 3}h", expected)
            axis_ranges = [(min(out_values[i::3]), max(out_values[i::3])) for i in range(3)]
            if any(lo == hi for lo, hi in axis_ranges):
                reason = "constant_axis"
            else:
                digest = hashlib.sha256(expected).hexdigest()
                if digest in seen_hashes:
                    reason = "duplicate_output"
                else:
                    seen_hashes[digest] = src["path"]
        if reason:
            expected_drops[src["path"]] = reason
            if src["path"] in by_source:
                fail(f"{src['path']} should be dropped ({reason}) but is indexed")
            continue
        assert expected is not None
        row = by_source.get(src["path"])
        if row is None:
            fail(f"{src['path']} passes the policy but has no index row")
        sample = data_root / row["sample_path"]
        want_rel = Path("samples") / DATASET_ID / SERIES_ID / src["machine"] / src["operation"] / src["label"] / (Path(src["path"]).stem + ".bin")
        if Path(row["sample_path"]) != want_rel:
            fail(f"unexpected sample path {row['sample_path']}")
        actual = sample.read_bytes()
        if actual != expected:
            fail(f"sample differs from independent re-derivation: {row['sample_path']}")
        digest = hashlib.sha256(actual).hexdigest()
        lo = min(a for a, _ in axis_ranges)
        hi = max(b for _, b in axis_ranges)
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": len(actual), "value_count": rows * 3,
            "sample_rank": 2, "sample_shape": [rows, 3],
            "natural_record_kind": series_decl["natural_record_kind"],
            "source_format": series_decl["source_format"], "source_field": series_decl["source_field"],
            "source_git_blob_sha1": src["git_blob_sha1"], "source_size_bytes": int(src["size_bytes"]),
            "source_container_dtype": src["container_dtype"], "machine": src["machine"],
            "operation": src["operation"], "label": src["label"], "timeframe": src["timeframe"],
            "run_index": src["run_index"], "minimum": lo, "maximum": hi,
            "axis_minimum": [a for a, _ in axis_ranges], "axis_maximum": [b for _, b in axis_ranges],
            "negative_zero_values": negative_zeros, "sha256": digest,
        }
        for key, value in checks.items():
            if row.get(key) != value:
                fail(f"index field {key} mismatch for {src['path']}: {row.get(key)!r} != {value!r}")
        if row.get("distinct_values", 0) < 2 or len(set(out_values)) != row["distinct_values"]:
            fail(f"distinct-value mismatch or constant sample {src['path']}")
        if rows * 3 < 1000:
            fail(f"sample below 1,000 values: {src['path']}")
        expected_files.add(sample.resolve())
        aggregate.update(actual)
        counts.append(rows * 3)
        negative_zero_total += negative_zeros
        if number % 100 == 0:
            print(f"verified {number}/{len(sources)}", flush=True)

    if set(by_source) - {s["path"] for s in sources}:
        fail("index has rows for unknown sources")
    if expected_drops != stats_dropped:
        fail(f"drop records differ: expected={expected_drops} stats={stats_dropped}")
    actual_files = {p.resolve() for p in output_dir.rglob("*") if p.is_file()}
    if actual_files != expected_files:
        fail(f"sample directory has {len(actual_files)} files, expected {len(expected_files)}")
    total_values = sum(counts)
    total_bytes = 2 * total_values
    median = statistics.median(counts)
    if total_values < 10_000 and total_bytes < 100_000:
        fail("aggregate floor not met")
    if median < 1_000:
        fail(f"median sample values {median} below floor")
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed the 1 GB cap")
    if series_decl.get("sample_count") != len(counts) or series_decl.get("total_size_bytes") != total_bytes:
        fail(f"manifest scope mismatch: manifest {series_decl.get('sample_count')}/{series_decl.get('total_size_bytes')} realized {len(counts)}/{total_bytes}")
    for key, value in {
        "kept_samples": len(counts), "total_values": total_values, "total_size_bytes": total_bytes,
        "median_sample_values": median, "negative_zero_values": negative_zero_total,
        "aggregate_sha256": aggregate.hexdigest(), "dropped_files": len(expected_drops),
    }.items():
        if stats.get(key) != value:
            fail(f"ingest stats {key} mismatch: {stats.get(key)!r} != {value!r}")
    labels = {by_source[p]["label"] for p in by_source}
    machines = {by_source[p]["machine"] for p in by_source}
    if labels != {"good", "bad"} or machines != {"M01", "M02"}:
        fail(f"realized scope lost a label or machine: labels={labels} machines={machines}")
    print(
        f"verified dataset={DATASET_ID} samples={len(counts)} dropped={len(expected_drops)} "
        f"values={total_values} bytes={total_bytes} median={median} "
        f"min_values={min(counts)} max_values={max(counts)} negative_zeros={negative_zero_total} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
