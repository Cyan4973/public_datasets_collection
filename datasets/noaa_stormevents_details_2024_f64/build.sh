#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_stormevents_details_2024_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

MIN_VALUES_PER_SAMPLE="${NOAA_STORMEVENTS_MIN_VALUES_PER_SAMPLE:-1000}"
MAX_PRIMARY_BYTES="${NOAA_STORMEVENTS_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_VALUES_PER_SAMPLE MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import shutil
import statistics
from array import array
from pathlib import Path

DATASET_ID = "noaa_stormevents_details_2024_f64"
SERIES_ID = "noaa_stormevents_detail_numeric_f64"
SELECTED_FIELDS = [
    "BEGIN_LAT",
    "BEGIN_LON",
    "END_LAT",
    "END_LON",
    "MAGNITUDE",
    "INJURIES_DIRECT",
    "INJURIES_INDIRECT",
    "DEATHS_DIRECT",
    "DEATHS_INDIRECT",
    "DAMAGE_PROPERTY",
    "DAMAGE_CROPS",
]
DAMAGE_FIELDS = {"DAMAGE_PROPERTY", "DAMAGE_CROPS"}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def parse_damage(value: str, field: str, row_number: int) -> float | None:
    token = value.strip().upper()
    if token in {"", "NA", "N/A"}:
        return None
    multiplier = 1.0
    if token[-1:] in {"K", "M", "B"}:
        suffix = token[-1]
        token = token[:-1]
        multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}[suffix]
    try:
        parsed = float(token.replace(",", ""))
    except ValueError as exc:
        raise SystemExit(f"invalid damage value field={field} row={row_number}: {value!r}") from exc
    result = parsed * multiplier
    if not math.isfinite(result):
        raise SystemExit(f"non-finite damage value field={field} row={row_number}: {value!r}")
    return result


def parse_decimal(value: str, field: str, row_number: int) -> float | None:
    token = value.strip()
    if token in {"", "NA", "N/A"}:
        return None
    try:
        parsed = float(token)
    except ValueError as exc:
        raise SystemExit(f"invalid numeric value field={field} row={row_number}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise SystemExit(f"non-finite numeric value field={field} row={row_number}: {value!r}")
    return parsed


def parse_value(value: str, field: str, row_number: int) -> float | None:
    if field in DAMAGE_FIELDS:
        return parse_damage(value, field, row_number)
    return parse_decimal(value, field, row_number)


inventory_path = download_dir / "download_inventory.json"
if inventory_path.is_file():
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    source_file = str(inventory.get("file", ""))
    source = download_dir / source_file
else:
    candidates = sorted(download_dir.glob("StormEvents_details-ftp_v1.0_d2024_c*.csv.gz"), reverse=True)
    if not candidates:
        raise SystemExit(f"missing download inventory and no 2024 StormEvents details gzip under {download_dir}")
    source = candidates[0]
    source_file = source.name
if not source.is_file():
    raise SystemExit(f"missing source file: {source}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / SERIES_ID
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

values_by_field: dict[str, array] = {field: array("d") for field in SELECTED_FIELDS}
blank_counts = {field: 0 for field in SELECTED_FIELDS}
row_count = 0

with gzip.open(source, "rt", encoding="utf-8-sig", newline="") as fh:
    reader = csv.DictReader(fh)
    if not reader.fieldnames:
        raise SystemExit("missing CSV header")
    missing = sorted(set(SELECTED_FIELDS) - {name.strip() for name in reader.fieldnames})
    if missing:
        raise SystemExit(f"missing selected fields: {missing}")
    for row_number, row in enumerate(reader, start=2):
        row_count += 1
        for field in SELECTED_FIELDS:
            parsed = parse_value(row.get(field, ""), field, row_number)
            if parsed is None:
                blank_counts[field] += 1
                continue
            values_by_field[field].append(parsed)

rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_small: list[str] = []
skipped_constant: list[str] = []
total_bytes = 0

for field in SELECTED_FIELDS:
    values = values_by_field[field]
    value_count = len(values)
    if value_count < min_values_per_sample:
        skipped_small.append(field)
        continue
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        skipped_constant.append(field)
        continue
    out = out_dir / f"{slug(field)}_f64_n{value_count:07d}.bin"
    with out.open("wb") as fh:
        values.tofile(fh)
    size = out.stat().st_size
    if size != value_count * 8:
        raise SystemExit(f"size mismatch for {field}: {size} != {value_count * 8}")
    if total_bytes + size > max_primary_bytes:
        out.unlink(missing_ok=True)
        break
    total_bytes += size
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": size,
        "value_count": value_count,
        "sample_format": "raw homogeneous float64 source-field column",
        "sample_geometry": "event_detail_table_field",
        "sample_rank": 1,
        "sample_shape": [value_count],
        "sample_axes": ["event_record"],
        "natural_record_kind": "noaa_stormevents_detail_year_field",
        "source_format": "gzip_csv",
        "source_field": f"StormEvents_details.{field}",
        "source_path": rel(source),
        "field_name": field,
        "blank_values_skipped": blank_counts[field],
        "min_value": min_value,
        "max_value": max_value,
    }
    rows.append(row)
    records.append({
        "field_name": field,
        "values": value_count,
        "blank_values_skipped": blank_counts[field],
        "sample_bytes": size,
        "min_value": min_value,
        "max_value": max_value,
    })

if len(rows) < 5:
    raise SystemExit(
        f"too few qualifying samples: {len(rows)} skipped_small={skipped_small} "
        f"skipped_constant={skipped_constant}"
    )
counts = sorted(int(row["value_count"]) for row in rows)
stats = {
    "dataset_id": DATASET_ID,
    "source_file": source_file,
    "source_rows": row_count,
    "samples": len(rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": statistics.median(counts),
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "skipped_small_fields": skipped_small,
    "skipped_constant_fields": skipped_constant,
    "max_primary_bytes": max_primary_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(rows)} values={stats['primary_values']} "
    f"bytes={total_bytes} median={int(statistics.median(counts))} source_rows={row_count}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
