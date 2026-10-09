#!/usr/bin/env python3
"""Independent verification of the ds007738 resting-state CW-fNIRS samples.

Re-walks each run's cached HDF5 metadata with the low-level reader (path
resolution instead of the builder's read_layout), re-checks every
measurementList dataType and the channel order, byte-compares every sample
with its fetched dataTimeSeries range, recomputes the index statistics with
memoryview/array code paths separate from the builder, applies the same
missing-value policy, rejects degenerate output, and checks the manifest
totals. Reports the share of NaN, exact-zero and 1e-6-floor values.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402
import snirf_fnirs as S  # noqa: E402  (constants and file naming only)

INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def walk_layout(store: H.BlockStore, size: int) -> tuple[int, int, int, str]:
    f = H.H5File(store, expected_size=size)
    info = f.dataset(f.resolve("/nirs/data1/dataTimeSeries"))
    dtype = bytes(info["datatype"])
    if dtype.rstrip(b"\0") != H.H5T_IEEE_F64LE.rstrip(b"\0") or info["filters"] or info["layout_class"] != 1:
        fail(f"dataTimeSeries is not a contiguous unfiltered H5T_IEEE_F64LE dataset ({dtype.hex()})")
    rows, cols = info["shape"]
    if cols != S.CHANNELS or int(info["contiguous_size"]) != rows * cols * 8:
        fail(f"dataTimeSeries shape {info['shape']} / size {info['contiguous_size']}")
    data1 = f.group_links(f.resolve("/nirs/data1"))
    lists = sorted((int(name[len("measurementList"):]), address) for name, address in data1.items()
                   if name.startswith("measurementList"))
    if [n for n, _ in lists] != list(range(1, S.CHANNELS + 1)) or len(data1) != S.CHANNELS + 2:
        fail("measurementList groups are not exactly 1..1134 (+ dataTimeSeries, time)")
    lines = ["channel\tsourceIndex\tdetectorIndex\twavelengthIndex\tdataType\tdataTypeIndex"]
    for number, address in lists:
        links = f.group_links(address)
        values = []
        for field in S.ML_FIELDS:
            item = f.dataset(links[field])
            if item["shape"] != () or item["layout_class"] != 1 or int(item["contiguous_size"]) != 8:
                fail(f"measurementList{number}/{field} is not a contiguous scalar")
            values.append(int.from_bytes(f.read(int(item["contiguous_address"]), 8), "little", signed=True))
        if values[3] != 1:
            fail(f"measurementList{number}/dataType = {values[3]} (only raw CW amplitude, 1, is collected)")
        lines.append("\t".join(str(v) for v in [number] + values))
    layout_sha = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    if layout_sha != S.LAYOUT_SHA256:
        fail(f"channel order/layout differs: {layout_sha}")
    return int(info["contiguous_address"]), int(info["contiguous_size"]), int(rows), layout_sha


def recompute(raw: bytes, rows: int) -> dict[str, object]:
    if sys.byteorder != "little":
        fail("verify assumes a little-endian host")
    values = memoryview(raw).cast("d")
    bits = memoryview(raw).cast("Q")
    count = len(values)
    nan_index = [i for i in range(count) if values[i] != values[i]]
    for i in nan_index:
        if bits[i] != S.CANONICAL_NAN:
            fail(f"non-canonical NaN at value {i}")
    nan_set = set(nan_index)
    finite = [values[i] for i in range(count) if i not in nan_set] if nan_index else list(values)
    if any(math.isinf(v) for v in finite):
        fail("infinite value present")
    zero = sum(1 for v in finite if v == 0.0)
    floor = sum(1 for v in finite if v == S.FLOOR)
    negative = sum(1 for v in finite if v < 0.0)
    below = sum(1 for v in finite if 0.0 < v < S.FLOOR)
    as32 = array.array("f", finite)
    f32_exact = sum(1 for a, b in zip(as32, finite) if a == b)
    mean = math.fsum(finite) / len(finite)
    var = math.fsum((v - mean) ** 2 for v in finite) / len(finite)
    constant_channels = 0
    for c in range(S.CHANNELS):
        column = set(bits[c::S.CHANNELS])
        if len(column) == 1:
            constant_channels += 1
    return {
        "nan_count": len(nan_index),
        "nan_row_count": len({i // S.CHANNELS for i in nan_index}),
        "zero_count": zero,
        "floor_1e-6_count": floor,
        "negative_count": negative,
        "positive_below_floor_count": below,
        "finite_count": len(finite),
        "finite_min": min(finite),
        "finite_max": max(finite),
        "distinct_count": len(set(bits)),
        "float32_exact_count": f32_exact,
        "std": math.sqrt(var),
        "constant_channels": constant_channels,
        "time_points": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--recipe-dir", required=True)
    args = parser.parse_args()
    data_root, recipe_dir = Path(args.data_root), Path(args.recipe_dir)
    download_dir = data_root / "downloads" / S.DATASET_ID
    sample_dir = data_root / "samples" / S.DATASET_ID / S.SERIES_ID
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == S.SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary" or len(manifest["series"]) != 1:
        fail("manifest must declare exactly the one primary series")
    runs = S.load_runs(recipe_dir)
    hashes = {(r["kind"], r["subject"], r["block"]): r for r in S.read_tsv(download_dir / "range_sha256.tsv")}
    index_rows = [json.loads(line) for line in
                  (data_root / "index" / S.DATASET_ID / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    if [r["subject"] for r in index_rows] != [r["subject"] for r in runs]:
        fail("index rows do not list the 24 runs in runs.tsv order")
    expected_files = {S.sample_name(run) for run in runs}
    present = {p.name for p in sample_dir.iterdir()}
    if present != expected_files:
        fail(f"sample directory mismatch: extra={sorted(present - expected_files)} missing={sorted(expected_files - present)}")
    totals = {"values": 0, "bytes": 0, "nan": 0, "zero": 0, "floor": 0}
    digests = set()
    for run, row in zip(runs, index_rows):
        subject = run["subject"]
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            fail(f"{subject}: index row lacks {missing}")
        size = int(run["size_bytes"])
        store = H.BlockStore(download_dir / "runs" / subject / "meta", size, S.META_BLOCK)
        try:
            address, nbytes, rows, layout_sha = walk_layout(store, size)
        except H.MissingBlock as exc:
            fail(f"{subject}: metadata block {exc.index} missing")
        for block in store.used:
            pin = hashes.get(("meta", subject, str(block)))
            if pin is None or hashlib.sha256(store.block_path(block).read_bytes()).hexdigest() != pin["sha256"]:
                fail(f"{subject}: metadata block {block} checksum")
        for column, value in (("data_address", address), ("data_bytes", nbytes), ("time_points", rows)):
            if run[column] != "-" and int(run[column]) != value:
                fail(f"{subject}: {column} {value} != pinned {run[column]}")
        source = (download_dir / "runs" / subject / "dataTimeSeries.f64le").read_bytes()
        sample_path = data_root / row["sample_path"]
        sample = sample_path.read_bytes()
        if sample_path.name != S.sample_name(run) or sample != source or len(sample) != nbytes:
            fail(f"{subject}: sample is not byte-identical to the dataTimeSeries range")
        digest = hashlib.sha256(sample).hexdigest()
        pin = hashes.get(("data", subject, "-"))
        if digest != row["sha256"] or pin is None or pin["sha256"] != digest or int(pin["start"]) != address:
            fail(f"{subject}: sha256 mismatch against index or range_sha256.tsv")
        if run["data_sha256"] != "-" and digest != run["data_sha256"]:
            fail(f"{subject}: sha256 differs from runs.tsv pin")
        if digest in digests:
            fail(f"{subject}: duplicate sample")
        digests.add(digest)
        fixed = {"dataset_id": S.DATASET_ID, "series_id": S.SERIES_ID, "numeric_kind": "float", "bit_width": 64,
                 "endianness": "little", "element_size_bytes": 8, "sample_size_bytes": nbytes,
                 "value_count": nbytes // 8, "source_offset": address, "layout_sha256": layout_sha,
                 "sample_shape": [rows, S.CHANNELS], "source_key": run["s3_key"], "source_etag": run["etag"]}
        for key, value in fixed.items():
            if row.get(key) != value:
                fail(f"{subject}: index {key}={row.get(key)!r} != {value!r}")
        stats = recompute(sample, rows)
        for key in ("nan_count", "nan_row_count", "zero_count", "floor_1e-6_count", "negative_count",
                    "positive_below_floor_count", "finite_count", "finite_min", "finite_max", "distinct_count",
                    "float32_exact_count", "time_points"):
            if row.get(key) != stats[key]:
                fail(f"{subject}: index {key}={row.get(key)!r} but recomputed {stats[key]!r}")
        count = nbytes // 8
        if stats["nan_count"] > S.MAX_NAN_FRACTION * count:
            fail(f"{subject}: NaN share {stats['nan_count'] / count:.4%} above policy")
        if stats["std"] <= 0 or stats["finite_min"] == stats["finite_max"]:
            fail(f"{subject}: constant sample")
        if stats["distinct_count"] < S.MIN_DISTINCT_FRACTION * count:
            fail(f"{subject}: only {stats['distinct_count']} distinct of {count}")
        if stats["constant_channels"] > S.CHANNELS // 4:
            fail(f"{subject}: {stats['constant_channels']} constant channels (degenerate)")
        totals["values"] += count
        totals["bytes"] += nbytes
        totals["nan"] += stats["nan_count"]
        totals["zero"] += stats["zero_count"]
        totals["floor"] += stats["floor_1e-6_count"]
        print(f"verify_ok subject={subject} shape=({rows},{S.CHANNELS}) nan={stats['nan_count']} "
              f"({stats['nan_count'] / count:.4%}, {stats['nan_row_count']} frames) "
              f"zero={stats['zero_count'] / count:.4%} floor_1e-6={stats['floor_1e-6_count'] / count:.4%} "
              f"constant_channels={stats['constant_channels']} distinct={stats['distinct_count'] / count:.4f} "
              f"f32_exact={stats['float32_exact_count']} std={stats['std']:.4g}")
    aggregate = hashlib.sha256("".join(r["sha256"] for r in index_rows).encode()).hexdigest()
    ingest = json.loads((data_root / "filtered" / S.DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    if ingest["aggregate_sha256"] != aggregate or ingest["values"] != totals["values"]:
        fail("ingest_stats.json disagrees with the samples")
    if series[0]["sample_count"] != len(index_rows) or series[0]["total_size_bytes"] != totals["bytes"]:
        fail(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
             f"!= realized {len(index_rows)}/{totals['bytes']}")
    print(f"verify_summary samples={len(index_rows)} values={totals['values']} bytes={totals['bytes']} "
          f"nan_share={totals['nan'] / totals['values']:.6f} zero_share={totals['zero'] / totals['values']:.6f} "
          f"floor_1e-6_share={totals['floor'] / totals['values']:.6f} aggregate_sha256={aggregate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
