#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_petroleum_barrel_prices"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export EIA_BARREL_PRICE_MIN_SERIES_RECORDS="${EIA_BARREL_PRICE_MIN_SERIES_RECORDS:-240}"
export EIA_BARREL_PRICE_MIN_RETAINED_SERIES="${EIA_BARREL_PRICE_MIN_RETAINED_SERIES:-5}"
export EIA_BARREL_PRICE_MIN_PRIMARY_BYTES="${EIA_BARREL_PRICE_MIN_PRIMARY_BYTES:-102400}"
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

DATASET_ID = "eia_petroleum_barrel_prices"
FAMILY = "eia_petroleum_crude_oil_price_usd_per_barrel_f64"

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["EIA_BARREL_PRICE_MIN_SERIES_RECORDS"])
min_series = int(os.environ["EIA_BARREL_PRICE_MIN_RETAINED_SERIES"])
min_primary_bytes = int(os.environ["EIA_BARREL_PRICE_MIN_PRIMARY_BYTES"])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:100] or "unknown"


def parse_period(period: str) -> tuple:
    period = str(period)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
        return (0, dt.date.fromisoformat(period).toordinal())
    if re.fullmatch(r"\d{4}-\d{2}", period):
        year, month = map(int, period.split("-"))
        return (1, year * 12 + month)
    if re.fullmatch(r"\d{4}", period):
        return (2, int(period))
    return (3, period)


def is_barrel_unit(units: str) -> bool:
    u = re.sub(r"\s+", "", units.upper())
    return u in {"$/BBL", "DOLLARS/BARREL", "DOLLARSPERBARREL", "DOLLARS/BBL"}


def is_crude_oil_price(info: dict) -> bool:
    text = " ".join(
        str(info.get(k) or "")
        for k in (
            "series-description",
            "series_description",
            "product-name",
            "product_name",
            "product",
            "process-name",
            "process",
        )
    ).lower()
    positive = ("crude", "oil", "brent", "wti", "lls", "mars", "refiner acquisition")
    negative = ("stock", "inventory", "production", "imports", "exports", "volume")
    return any(k in text for k in positive) and not any(k in text for k in negative)


pages = sorted(p for p in page_dir.glob("*/*/page_*.json") if p.is_file())
if not pages:
    raise SystemExit(f"missing downloaded pages under {page_dir}; run download.sh first")

by_series: dict[tuple[str, str, str], dict] = {}
skipped = 0
duplicates = 0
seen: set[tuple[str, str, str, str]] = set()
for page in pages:
    endpoint_slug = page.parts[-3]
    frequency = page.parts[-2]
    obj = json.loads(page.read_text(encoding="utf-8"))
    rows = (obj.get("response") or {}).get("data")
    if not isinstance(rows, list):
        continue
    for row in rows:
        try:
            series = str(row["series"])
            units = str(row["units"])
            period = str(row["period"])
            value = float(str(row["value"]).strip())
        except Exception:
            skipped += 1
            continue
        if not series or not math.isfinite(value):
            skipped += 1
            continue
        if not is_barrel_unit(units) or not is_crude_oil_price(row):
            continue
        key = (endpoint_slug, frequency, series)
        row_key = (*key, period)
        if row_key in seen:
            duplicates += 1
            continue
        seen.add(row_key)
        bucket = by_series.setdefault(
            key,
            {
                "rows": [],
                "units": units,
                "series_description": str(row.get("series-description") or row.get("series_description") or ""),
                "product": str(row.get("product") or ""),
                "product_name": str(row.get("product-name") or row.get("product_name") or ""),
                "area": str(row.get("duoarea") or row.get("area") or ""),
                "area_name": str(row.get("area-name") or row.get("area_name") or ""),
            },
        )
        bucket["rows"].append((parse_period(period), period, value))

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
family_dir = samples_dir / FAMILY
family_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
series_summary = {}
for (endpoint_slug, frequency, series), info in sorted(by_series.items()):
    ordered = sorted(info["rows"], key=lambda x: x[0])
    if len(ordered) < min_records:
        continue
    values = [v for _key, _period, v in ordered]
    if len(set(values)) <= 1:
        continue
    sample_stem = f"{endpoint_slug}_{frequency}_{slug(series)}_n{len(values):06d}"
    out = family_dir / f"{sample_stem}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + "d" * len(values), *values))
    index_rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_format": "raw homogeneous float64 array",
            "sample_geometry": "eia_petroleum_price_time_series",
            "sample_rank": 1,
            "sample_axes": ["period"],
            "natural_record_kind": "eia_petroleum_price_series",
            "endpoint": endpoint_slug,
            "frequency": frequency,
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
    series_summary[f"{endpoint_slug}:{frequency}:{series}"] = {
        "records": len(values),
        "units": info["units"],
        "product": info["product"],
        "area": info["area"],
        "description": info["series_description"],
    }

if len(index_rows) < min_series:
    raise SystemExit(f"retained only {len(index_rows)} series < {min_series}")

primary_bytes = sum(int(row["sample_size_bytes"]) for row in index_rows)
primary_values = sum(int(row["value_count"]) for row in index_rows)
if primary_bytes < min_primary_bytes:
    raise SystemExit(f"primary bytes below floor: {primary_bytes} < {min_primary_bytes}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "source_pages": len(pages),
            "candidate_series": len(by_series),
            "retained_series": len(index_rows),
            "primary_values": primary_values,
            "primary_sample_bytes": primary_bytes,
            "min_series_records": min_records,
            "min_retained_series": min_series,
            "skipped_rows": skipped,
            "duplicate_rows": duplicates,
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

print(f"retained_series={len(index_rows)} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
