#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="modis_active_fire_mask_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from collections import Counter
from pathlib import Path

DATASET_ID = "modis_active_fire_mask_u8"
SERIES_ID = "modis_8day_active_fire_mask_u8"
EXPECTED_SAMPLES = 12
EXPECTED_VALUES = 1200 * 1200
EXPECTED_TOTAL = EXPECTED_SAMPLES * EXPECTED_VALUES
MIN_MINORITY_FRACTION = 0.001
ALLOWED = set(range(10))
FIRE_CLASSES = {7, 8, 9}

data_root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) != EXPECTED_SAMPLES:
    raise SystemExit(f"primary sample count={len(primary)} expected={EXPECTED_SAMPLES}")

seen_items: set[str] = set()
seen_region_dates: set[tuple[str, str]] = set()
regions: Counter[str] = Counter()
dates: Counter[str] = Counter()
counts: list[int] = []
aggregate = Counter()

for row in primary:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
        raise SystemExit(f"wrong dataset/series identity: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", -1)) != 8:
        raise SystemExit(f"wrong numeric type: {row}")
    if row.get("endianness") != "little" or int(row.get("element_size_bytes", -1)) != 1:
        raise SystemExit(f"wrong byte representation: {row}")
    if row.get("sample_shape") != [1200, 1200] or int(row.get("sample_rank", -1)) != 2:
        raise SystemExit(f"wrong fixed sample shape: {row}")
    if row.get("source_format") != "cloud_optimized_geotiff":
        raise SystemExit(f"wrong source format: {row}")
    if row.get("source_field") != "FireMask.band_1.maximum_fire_mask_class_over_8_day_composite":
        raise SystemExit(f"wrong source field: {row}")
    if row.get("natural_record_kind") != "complete_mod14a2_8_day_firemask_tile":
        raise SystemExit(f"wrong natural record kind: {row}")

    item_id = str(row.get("item_id", ""))
    region = str(row.get("region", ""))
    date = str(row.get("analysis_start_date_utc", ""))
    if not item_id or item_id in seen_items:
        raise SystemExit(f"missing or duplicate item ID: {item_id}")
    if not region or not date or (region, date) in seen_region_dates:
        raise SystemExit(f"missing or duplicate region/date: {region} {date}")
    seen_items.add(item_id)
    seen_region_dates.add((region, date))
    regions[region] += 1
    dates[date] += 1

    sample = data_root / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample: {sample}")
    payload = sample.read_bytes()
    if len(payload) != EXPECTED_VALUES:
        raise SystemExit(f"wrong complete-tile size file={sample} bytes={len(payload)}")
    if len(payload) != int(row["sample_size_bytes"]) or len(payload) != int(row["value_count"]):
        raise SystemExit(f"index size mismatch: {sample}")
    histogram = Counter(payload)
    unexpected = set(histogram) - ALLOWED
    if unexpected:
        raise SystemExit(f"unexpected FireMask codes file={sample} codes={sorted(unexpected)}")
    if len(histogram) <= 1:
        raise SystemExit(f"constant FireMask sample: {sample}")
    minority_fraction = 1.0 - max(histogram.values()) / len(payload)
    if minority_fraction < MIN_MINORITY_FRACTION:
        raise SystemExit(f"degenerate FireMask sample={sample} minority_fraction={minority_fraction:.8f}")
    fire_pixels = sum(histogram[code] for code in FIRE_CLASSES)
    if fire_pixels <= 0:
        raise SystemExit(f"no fire-confidence pixels: {sample}")
    indexed_histogram = {int(key): int(value) for key, value in row["category_histogram"].items()}
    if dict(histogram) != indexed_histogram:
        raise SystemExit(f"histogram/index mismatch: {sample}")
    if fire_pixels != int(row["fire_confidence_pixels"]):
        raise SystemExit(f"fire-count/index mismatch: {sample}")
    aggregate.update(histogram)
    counts.append(len(payload))

if sorted(regions.values()) != [3, 3, 3, 3]:
    raise SystemExit(f"expected four regions with three samples each: {dict(regions)}")
if sorted(dates.values()) != [4, 4, 4]:
    raise SystemExit(f"expected three dates with four samples each: {dict(dates)}")
total = sum(counts)
if total != EXPECTED_TOTAL:
    raise SystemExit(f"wrong aggregate size: {total} != {EXPECTED_TOTAL}")
if statistics.median(counts) != EXPECTED_VALUES:
    raise SystemExit(f"wrong fixed-size median: {statistics.median(counts)}")
if total > 1_000_000_000:
    raise SystemExit(f"primary byte cap exceeded: {total}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["samples"]) != EXPECTED_SAMPLES:
    raise SystemExit("stats sample count mismatch")
if int(stats["primary_values"]) != total or int(stats["primary_sample_bytes"]) != total:
    raise SystemExit("stats primary totals mismatch")
stats_histogram = {int(key): int(value) for key, value in stats["category_histogram"].items()}
if dict(aggregate) != stats_histogram:
    raise SystemExit("stats aggregate histogram mismatch")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} values={total} bytes={total} "
    f"fixed_values={EXPECTED_VALUES} regions={len(regions)} dates={len(dates)} codes={sorted(aggregate)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
