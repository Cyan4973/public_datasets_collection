#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys


DATASET_ID = "zenodo_lora24_indoor_rssi_i8"
SERIES_ID = "lora24_rssi_i8"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    return parser.parse_args()


def main() -> None:
    args = arguments()
    data_root = args.repo_root / args.data_dir
    recipe_scripts = args.repo_root / "datasets" / DATASET_ID / "scripts"
    sys.path.insert(0, str(recipe_scripts))
    from build import parse_sources  # pylint: disable=import-outside-toplevel

    download_dir = data_root / "downloads" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SystemExit("missing build outputs")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups, _ = parse_sources(download_dir)
    expected: dict[tuple[object, ...], bytes] = {}
    for key, values in groups.items():
        signed = [value if value < 128 else value - 256 for value in values]
        if len(values) >= 1_024 and len(set(signed)) > 1:
            expected[key] = bytes(values)
    if len(rows) != len(expected):
        raise SystemExit(f"index/fresh group count mismatch: {len(rows)} != {len(expected)}")
    counts: list[int] = []
    hashes: set[str] = set()
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise SystemExit("wrong dataset/series identity")
        if row.get("numeric_kind") != "int" or int(row.get("bit_width", -1)) != 8:
            raise SystemExit("wrong numeric type")
        experiment = str(row["source_experiment"])
        node = int(row["source_node_id"])
        config = row.get("radio_configuration")
        if experiment == "exhaustive":
            key: tuple[object, ...] = (experiment, node)
            if config is not None:
                raise SystemExit("exhaustive sample unexpectedly has a fixed configuration")
        else:
            if not isinstance(config, dict):
                raise SystemExit("long-run sample lacks configuration")
            key = (
                experiment, node, int(config["channel"]), int(config["frequency_mhz"]),
                int(config["spreading_factor"]), int(config["bandwidth_khz_code"]),
                str(config["coding_rate_text"]), int(config["transmit_power"]),
                int(config["real_coding_rate"]),
            )
        sample = data_root / str(row["sample_path"])
        actual = sample.read_bytes()
        if actual != expected.pop(key, None):
            raise SystemExit(f"sample differs from fresh source decode: {sample}")
        if len(actual) != int(row["value_count"]) or len(actual) < 1_024:
            raise SystemExit(f"sample size mismatch: {sample}")
        signed = [value if value < 128 else value - 256 for value in actual]
        histogram = Counter(signed)
        if len(histogram) <= 1 or min(signed) != int(row["minimum"]) or max(signed) != int(row["maximum"]):
            raise SystemExit(f"range/diversity mismatch: {sample}")
        indexed = {int(key): int(value) for key, value in row["value_histogram"].items()}
        if dict(histogram) != indexed:
            raise SystemExit(f"histogram mismatch: {sample}")
        digest = hashlib.sha256(actual).hexdigest()
        if digest != row["sha256"] or digest in hashes:
            raise SystemExit(f"hash mismatch or duplicate: {sample}")
        hashes.add(digest)
        counts.append(len(actual))
    if expected:
        raise SystemExit(f"unindexed qualifying groups remain: {list(expected)[:5]}")
    total = sum(counts)
    median = statistics.median(counts)
    if total < 100_000 or median < 1_000 or total > 1_000_000_000:
        raise SystemExit(f"acceptance size floor/cap failed: total={total} median={median}")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(stats["samples"]) != len(rows) or int(stats["primary_values"]) != total:
        raise SystemExit("stats mismatch")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} values={total} bytes={total} median={median:g}")


if __name__ == "__main__":
    main()
