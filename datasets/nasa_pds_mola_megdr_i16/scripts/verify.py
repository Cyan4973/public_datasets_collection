#!/usr/bin/env python3
"""Verify selected MOLA MEGDR int16 samples and metadata."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import statistics
import sys


DATASET_ID = "nasa_pds_mola_megdr_i16"
SERIES_ID = "mola_megdr_topography_i16"
PRODUCTS = {"MEGT00N000GB", "MEGT00N180GB", "MEGT90N000GB", "MEGT90N180GB"}
LINES = 5760
LINE_SAMPLES = 11520
VALUES_PER_SAMPLE = LINES * LINE_SAMPLES
BYTES_PER_SAMPLE = VALUES_PER_SAMPLE * 2
TOTAL_BYTES = BYTES_PER_SAMPLE * 4


def inspect(path: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    minimum = 32767
    maximum = -32768
    with path.open("rb") as handle:
        for raw in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            if len(raw) % 2:
                raise ValueError(f"{path}: odd byte count")
            digest.update(raw)
            values = array("h")
            values.frombytes(raw)
            if values:
                minimum = min(minimum, min(values))
                maximum = max(maximum, max(values))
    return minimum, maximum, digest.hexdigest()


def main() -> None:
    if sys.byteorder != "little":
        raise SystemExit("verification requires a little-endian host")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_root = args.repo_root / args.data_dir
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if len(rows) != 4 or {row.get("product_id") for row in rows} != PRODUCTS:
        raise SystemExit("index does not contain the four selected topography quadrants")
    sizes = []
    ranges = []
    for row in rows:
        expected = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": BYTES_PER_SAMPLE,
            "value_count": VALUES_PER_SAMPLE, "sample_geometry": "planetary_topography_quadrant_2d",
            "sample_rank": 2, "sample_shape": [LINES, LINE_SAMPLES],
            "sample_axes": ["latitude", "longitude"],
            "natural_record_kind": "mola_megdr_topography_quadrant",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise SystemExit(f"unexpected {key} for {row.get('product_id')}: {row.get(key)!r}")
        path = data_root / row["sample_path"]
        if not path.is_file() or path.stat().st_size != BYTES_PER_SAMPLE:
            raise SystemExit(f"missing or wrong-sized sample: {path}")
        minimum, maximum, digest = inspect(path)
        if minimum >= maximum or minimum != row.get("min") or maximum != row.get("max"):
            raise SystemExit(f"range mismatch for {path}: {minimum}..{maximum}")
        if digest != row.get("sha256"):
            raise SystemExit(f"SHA-256 mismatch for {path}")
        sizes.append(path.stat().st_size)
        ranges.append((minimum, maximum))
    if sum(sizes) != TOTAL_BYTES:
        raise SystemExit(f"unexpected primary byte total: {sum(sizes)}")
    if stats.get("sample_count") != 4 or stats.get("primary_bytes") != TOTAL_BYTES:
        raise SystemExit("stats/index totals disagree")
    if stats.get("primary_values") != VALUES_PER_SAMPLE * 4:
        raise SystemExit("stats primary value count disagrees")
    print(
        f"verified_samples=4 primary_values={VALUES_PER_SAMPLE * 4} primary_bytes={sum(sizes)} "
        f"median_sample_bytes={int(statistics.median(sizes))} "
        f"range={min(a for a, _ in ranges)}..{max(b for _, b in ranges)}"
    )


if __name__ == "__main__":
    main()
