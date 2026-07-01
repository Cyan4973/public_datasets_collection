#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eurostat_unemployment_monthly"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES="${EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES:-100000}"
export EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES="${EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES:-400000}"
export EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES="${EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES:-100000}"
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import re
import shutil
import struct
from itertools import product
from pathlib import Path

DATASET_ID = "eurostat_unemployment_monthly"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_primary_values = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES"])


def parse_time_key(raw: str) -> int:
    match = re.fullmatch(r"(\d{4})[-M](\d{2})", raw.strip())
    if not match:
        raise ValueError(raw)
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise ValueError(raw)
    return year * 12 + month


def flatten_index(ids: list[str], sizes: list[int], positions: dict[str, int]) -> int:
    index = 0
    stride = 1
    for dim_name, dim_size in zip(reversed(ids), reversed(sizes)):
        index += positions[dim_name] * stride
        stride *= dim_size
    return index


def category_items(payload: dict, dim_name: str) -> list[tuple[str, int]]:
    index = payload["dimension"][dim_name]["category"]["index"]
    return sorted(index.items(), key=lambda item: item[1])


raw_path = download_dir / "data.json"
if not raw_path.is_file():
    raise SystemExit(f"missing raw JSON: {raw_path}; run download.sh first")
payload = json.loads(raw_path.read_text(encoding="utf-8"))
ids = list(payload["id"])
sizes = [int(size) for size in payload["size"]]
value_data = payload["value"]

variable_dims = {"s_adj", "age", "sex", "geo", "time"}
for required in sorted(variable_dims):
    if required not in ids:
        raise SystemExit(f"missing required Eurostat dimension: {required}")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

age_items = category_items(payload, "age")
geo_items = category_items(payload, "geo")
s_adj_items = category_items(payload, "s_adj")
sex_items = category_items(payload, "sex")
time_items = category_items(payload, "time")
fixed_positions = {}
for dim_name in ids:
    if dim_name in variable_dims:
        continue
    if sizes[ids.index(dim_name)] != 1:
        raise SystemExit(f"unexpected non-fixed dimension {dim_name} size={sizes[ids.index(dim_name)]}")
    fixed_positions[dim_name] = 0

rates: list[float] = []
age_ordinals: list[int] = []
geo_ordinals: list[int] = []
s_adj_ordinals: list[int] = []
sex_ordinals: list[int] = []
month_ordinals: list[int] = []
kept_by_age: dict[str, int] = {}
kept_by_geo: dict[str, int] = {}
kept_by_s_adj: dict[str, int] = {}
kept_by_sex: dict[str, int] = {}
skipped_blank = 0
skipped_parse = 0

for (s_adj_code, s_adj_pos), (age_code, age_pos), (sex_code, sex_pos), (geo_code, geo_pos), (time_key, time_pos) in product(
    s_adj_items,
    age_items,
    sex_items,
    geo_items,
    time_items,
):
    positions = dict(fixed_positions)
    positions["s_adj"] = s_adj_pos
    positions["age"] = age_pos
    positions["sex"] = sex_pos
    positions["geo"] = geo_pos
    positions["time"] = time_pos
    flat_index = flatten_index(ids, sizes, positions)
    if isinstance(value_data, dict):
        raw_value = value_data.get(str(flat_index))
    else:
        raw_value = value_data[flat_index] if flat_index < len(value_data) else None
    if raw_value in ("", None):
        skipped_blank += 1
        continue
    try:
        rate = float(raw_value)
        month_ordinal = parse_time_key(time_key)
    except (TypeError, ValueError):
        skipped_parse += 1
        continue
    if not math.isfinite(rate):
        skipped_parse += 1
        continue
    rates.append(rate)
    s_adj_ordinals.append(s_adj_pos)
    age_ordinals.append(age_pos)
    sex_ordinals.append(sex_pos)
    geo_ordinals.append(geo_pos)
    month_ordinals.append(month_ordinal)
    kept_by_s_adj[s_adj_code] = kept_by_s_adj.get(s_adj_code, 0) + 1
    kept_by_age[age_code] = kept_by_age.get(age_code, 0) + 1
    kept_by_sex[sex_code] = kept_by_sex.get(sex_code, 0) + 1
    kept_by_geo[geo_code] = kept_by_geo.get(geo_code, 0) + 1

if len(rates) < min_primary_values:
    raise SystemExit(f"only {len(rates)} rates < EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES={min_primary_values}")

series_values = {
    "unemployment_rate_f32": ("primary", "float", 32, 4, "f", rates),
    "eurostat_unemployment_s_adj_index": ("auxiliary", "uint", 16, 2, "H", s_adj_ordinals),
    "eurostat_unemployment_age_index": ("auxiliary", "uint", 16, 2, "H", age_ordinals),
    "eurostat_unemployment_sex_index": ("auxiliary", "uint", 16, 2, "H", sex_ordinals),
    "eurostat_unemployment_geo_index": ("auxiliary", "uint", 16, 2, "H", geo_ordinals),
    "eurostat_unemployment_month_ordinal": ("auxiliary", "uint", 32, 4, "I", month_ordinals),
}
index_rows = []
for series_id, (role, kind, bits, element_size, code, values) in series_values.items():
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(values), 8192):
            chunk = values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    index_rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": role,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "eurostat_unemployment_observation_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["observation"],
            "natural_record_kind": "eurostat_unemployment_observation_table",
            "min": min(values),
            "max": max(values),
        }
    )

primary_rows = [row for row in index_rows if row["role"] == "primary"]
primary_values = sum(int(row["value_count"]) for row in primary_rows)
primary_bytes = sum(int(row["sample_size_bytes"]) for row in primary_rows)
median_primary_values = sorted(int(row["value_count"]) for row in primary_rows)[len(primary_rows) // 2]
if primary_bytes < min_primary_bytes:
    raise SystemExit(f"primary bytes below floor: {primary_bytes} < {min_primary_bytes}")
if median_primary_values < min_median_values:
    raise SystemExit(f"median primary values below floor: {median_primary_values} < {min_median_values}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "s_adj_categories": len(s_adj_items),
            "age_categories": len(age_items),
            "sex_categories": len(sex_items),
            "geo_categories": len(geo_items),
            "time_categories": len(time_items),
            "retained_records": len(rates),
            "skipped_blank_cells": skipped_blank,
            "skipped_parse_cells": skipped_parse,
            "primary_values": primary_values,
            "primary_sample_bytes": primary_bytes,
            "median_primary_values": median_primary_values,
            "kept_by_s_adj": kept_by_s_adj,
            "kept_by_age": kept_by_age,
            "kept_by_sex": kept_by_sex,
            "kept_by_geo_count": len(kept_by_geo),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (filter_dir / "dimension_categories.json").open("w", encoding="utf-8") as fh:
    json.dump(
        {
            "s_adj": [{"code": code, "index": pos} for code, pos in s_adj_items],
            "age": [{"code": code, "index": pos} for code, pos in age_items],
            "sex": [{"code": code, "index": pos} for code, pos in sex_items],
            "geo": [{"code": code, "index": pos} for code, pos in geo_items],
            "time": [{"code": code, "index": pos} for code, pos in time_items],
        },
        fh,
        indent=2,
        sort_keys=True,
    )
    fh.write("\n")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"retained_records={len(rates)} primary_values={primary_values} "
    f"primary_sample_bytes={primary_bytes} median_primary_values={median_primary_values}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
