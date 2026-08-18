#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import statistics


DATASET_ID = "zenodo_aegis_obd_pid_u8"
SERIES_ID = "aegis_obd_pid_value_u8"
HEADER = ["obdData_id", "trip_id", "obdPid", "data", "timestamp"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = args.repo_root / args.data_dir
    source = data_root / "extracted" / DATASET_ID / "obdData.csv"
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not source.is_file() or not index_path.is_file() or not stats_path.is_file():
        raise SystemExit("missing source, index, or stats; run download.sh and build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    primary = [row for row in rows if row.get("role") == "primary"]
    if len(primary) < 3:
        raise SystemExit(f"too few primary samples: {len(primary)}")
    expected_keys = {(int(row["source_trip_id"]), str(row["obd_pid_hex"])) for row in primary}
    if len(expected_keys) != len(primary):
        raise SystemExit("duplicate trip/PID index keys")
    reconstructed: dict[tuple[int, str], bytearray] = defaultdict(bytearray)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != HEADER:
            raise SystemExit("source header changed")
        for line_number, row in enumerate(reader, 2):
            if len(row) != 5:
                raise SystemExit(f"line {line_number}: wrong field count")
            key = (int(row[1]), row[2].strip().upper())
            if key not in expected_keys:
                continue
            try:
                value = Decimal(row[3].strip())
            except InvalidOperation:
                raise SystemExit(f"line {line_number}: selected group has nonnumeric value")
            if not value.is_finite() or value != value.to_integral_value() or not 0 <= value <= 255:
                raise SystemExit(f"line {line_number}: selected group has non-u8 value {value}")
            reconstructed[key].append(int(value))

    counts: list[int] = []
    hashes: set[str] = set()
    for row in primary:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise SystemExit("wrong dataset or series identity")
        if row.get("numeric_kind") != "uint" or int(row.get("bit_width", -1)) != 8:
            raise SystemExit("wrong numeric representation")
        if row.get("endianness") != "little" or int(row.get("element_size_bytes", -1)) != 1:
            raise SystemExit("wrong byte representation")
        if row.get("natural_record_kind") != "complete_aegis_trip_pid_timeline":
            raise SystemExit("wrong natural record kind")
        key = (int(row["source_trip_id"]), str(row["obd_pid_hex"]))
        expected = bytes(reconstructed[key])
        sample = data_root / str(row["sample_path"])
        actual = sample.read_bytes()
        if actual != expected:
            raise SystemExit(f"sample differs from fresh source decode: {sample}")
        if len(actual) != int(row["value_count"]) or len(actual) != int(row["sample_size_bytes"]):
            raise SystemExit(f"sample size/index mismatch: {sample}")
        if len(actual) < 1_024 or len(set(actual)) <= 1:
            raise SystemExit(f"tiny or constant selected sample: {sample}")
        digest = hashlib.sha256(actual).hexdigest()
        if digest != row.get("sha256") or digest in hashes:
            raise SystemExit(f"hash mismatch or duplicate sample: {sample}")
        hashes.add(digest)
        histogram = Counter(actual)
        indexed_histogram = {int(key): int(value) for key, value in row["value_histogram"].items()}
        if dict(histogram) != indexed_histogram:
            raise SystemExit(f"histogram mismatch: {sample}")
        if min(actual) != int(row["minimum"]) or max(actual) != int(row["maximum"]):
            raise SystemExit(f"range mismatch: {sample}")
        counts.append(len(actual))

    total = sum(counts)
    median = statistics.median(counts)
    if total < 100_000:
        raise SystemExit(f"aggregate sample bytes below floor: {total}")
    if median < 1_024:
        raise SystemExit(f"median natural sample below floor: {median}")
    if total > 1_000_000_000:
        raise SystemExit(f"primary byte cap exceeded: {total}")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(stats["samples"]) != len(primary):
        raise SystemExit("stats sample count mismatch")
    if int(stats["primary_values"]) != total or int(stats["primary_sample_bytes"]) != total:
        raise SystemExit("stats total mismatch")
    print(
        f"verified dataset={DATASET_ID} samples={len(primary)} values={total} "
        f"bytes={total} median={median:g} trips={stats['selected_trip_ids']} "
        f"pids={stats['selected_pids']}"
    )


if __name__ == "__main__":
    main()
