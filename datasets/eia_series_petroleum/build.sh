#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_series_petroleum"
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

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export EIA_PETROLEUM_MIN_SERIES_RECORDS="${EIA_PETROLEUM_MIN_SERIES_RECORDS:-1000}"
export EIA_PETROLEUM_MIN_PRIMARY_BYTES="${EIA_PETROLEUM_MIN_PRIMARY_BYTES:-102400}"
export EIA_PETROLEUM_MIN_MEDIAN_VALUES="${EIA_PETROLEUM_MIN_MEDIAN_VALUES:-1000}"
python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import shutil
import struct
from pathlib import Path

DATASET_ID = "eia_series_petroleum"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_series_records = int(os.environ["EIA_PETROLEUM_MIN_SERIES_RECORDS"])
min_primary_bytes = int(os.environ["EIA_PETROLEUM_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["EIA_PETROLEUM_MIN_MEDIAN_VALUES"])


def load_rows() -> tuple[list[dict], int]:
    combined = download_dir / "eia_series_petroleum.json"
    if combined.is_file():
        obj = json.loads(combined.read_text(encoding="utf-8"))
        data = (obj.get("response") or {}).get("data")
        if isinstance(data, list):
            return data, int((obj.get("download") or {}).get("page_count") or 1)
    page_files = sorted((download_dir / "pages").glob("page_*.json"))
    if page_files:
        rows: list[dict] = []
        for page_file in page_files:
            obj = json.loads(page_file.read_text(encoding="utf-8"))
            data = (obj.get("response") or {}).get("data")
            if not isinstance(data, list):
                raise SystemExit(f"{page_file}: missing response.data list")
            rows.extend(data)
        return rows, len(page_files)
    raise SystemExit(f"missing local EIA petroleum data under {download_dir}; run download.sh first")


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return text[:80] or "unknown"


def parse_day(period: str) -> int:
    day = dt.date.fromisoformat(period)
    return day.toordinal()


rows, source_pages = load_rows()
by_series: dict[str, dict] = {}
skipped = 0
duplicate_rows = 0
seen: set[tuple[str, str]] = set()

for row in rows:
    try:
        series = str(row["series"])
        period = str(row["period"])
        units = str(row["units"])
        value = float(str(row["value"]).strip())
        day = parse_day(period)
    except Exception:
        skipped += 1
        continue
    if not math.isfinite(value) or not series:
        skipped += 1
        continue
    key = (series, period)
    if key in seen:
        duplicate_rows += 1
        continue
    seen.add(key)
    bucket = by_series.setdefault(
        series,
        {
            "units": units,
            "series_description": str(row.get("series-description") or ""),
            "product": str(row.get("product") or ""),
            "product_name": str(row.get("product-name") or ""),
            "area": str(row.get("duoarea") or ""),
            "area_name": str(row.get("area-name") or ""),
            "rows": [],
        },
    )
    if bucket["units"] != units:
        skipped += 1
        continue
    bucket["rows"].append((day, value))

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
series_summary = {}
for series, info in sorted(by_series.items()):
    ordered = sorted(info["rows"])
    if len(ordered) < min_series_records:
        continue
    values = [value for _day, value in ordered]
    days = [day for day, _value in ordered]
    if min(values) == max(values):
        continue
    unit_slug = {"$/GAL": "usd_per_gallon", "$/BBL": "usd_per_barrel"}.get(info["units"], slug(info["units"]))
    series_slug = slug(series)
    family_id = f"eia_petroleum_spot_price_{unit_slug}_f64"
    sample_stem = f"{series_slug}_n{len(values):06d}"

    primary_dir = samples_dir / family_id
    primary_dir.mkdir(parents=True, exist_ok=True)
    primary_out = primary_dir / f"{sample_stem}.bin"
    with primary_out.open("wb") as fh:
        fh.write(struct.pack("<" + "d" * len(values), *values))
    index_rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": family_id,
            "role": "primary",
            "sample_path": primary_out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": primary_out.stat().st_size,
            "value_count": len(values),
            "sample_format": "raw homogeneous float64 array",
            "sample_geometry": "eia_petroleum_daily_spot_price_series",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["day"],
            "natural_record_kind": "eia_petroleum_daily_series",
            "eia_series": series,
            "units": info["units"],
            "series_description": info["series_description"],
            "product": info["product"],
            "product_name": info["product_name"],
            "area": info["area"],
            "area_name": info["area_name"],
            "min": min(values),
            "max": max(values),
        }
    )

    aux_id = "eia_petroleum_period_ordinal"
    aux_dir = samples_dir / aux_id
    aux_dir.mkdir(parents=True, exist_ok=True)
    aux_out = aux_dir / f"{sample_stem}_u32.bin"
    with aux_out.open("wb") as fh:
        fh.write(struct.pack("<" + "I" * len(days), *days))
    index_rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": aux_id,
            "role": "auxiliary",
            "sample_path": aux_out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": aux_out.stat().st_size,
            "value_count": len(days),
            "sample_format": "raw homogeneous uint32 array",
            "sample_geometry": "eia_petroleum_daily_date_axis",
            "sample_rank": 1,
            "sample_shape": [len(days)],
            "sample_axes": ["day"],
            "natural_record_kind": "eia_petroleum_daily_series_date_axis",
            "eia_series": series,
            "min": min(days),
            "max": max(days),
        }
    )
    series_summary[series] = {
        "records": len(values),
        "units": info["units"],
        "product": info["product"],
        "area": info["area"],
    }

primary_rows = [row for row in index_rows if row["role"] == "primary"]
if not primary_rows:
    raise SystemExit("no EIA petroleum series met the per-series record floor")

primary_values = sum(int(row["value_count"]) for row in primary_rows)
primary_sample_bytes = sum(int(row["sample_size_bytes"]) for row in primary_rows)
median_primary_values = sorted(int(row["value_count"]) for row in primary_rows)[len(primary_rows) // 2]
if primary_sample_bytes < min_primary_bytes:
    raise SystemExit(f"primary_sample_bytes below floor: {primary_sample_bytes} < {min_primary_bytes}")
if median_primary_values < min_median_values:
    raise SystemExit(f"median primary values below floor: {median_primary_values} < {min_median_values}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_pages": source_pages,
            "source_rows": len(rows),
            "retained_series": len(primary_rows),
            "retained_records": primary_values,
            "skipped_records": skipped,
            "duplicate_records": duplicate_rows,
            "primary_values": primary_values,
            "primary_sample_bytes": primary_sample_bytes,
            "median_primary_values": median_primary_values,
            "min_series_records": min_series_records,
            "series": series_summary,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"retained_series={len(primary_rows)} primary_values={primary_values} "
    f"primary_sample_bytes={primary_sample_bytes} median_primary_values={median_primary_values}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
