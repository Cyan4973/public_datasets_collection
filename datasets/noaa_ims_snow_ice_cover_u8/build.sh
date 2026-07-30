#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_ims_snow_ice_cover_u8"
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
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
from collections import Counter
from pathlib import Path

DATASET_ID = "noaa_ims_snow_ice_cover_u8"
SERIES_ID = "ims_snow_ice_category_u8"
WIDTH = 6144
HEIGHT = 6144
EXPECTED_VALUES = WIDTH * HEIGHT
HEADER_LINES = 30
ALLOWED = set(range(5))
TRANSLATE = bytes.maketrans(b"01234", bytes(range(5)))

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
plan_path = download_dir / "download_plan.tsv"
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def decode_grid(path: Path) -> tuple[bytes, list[str]]:
    values = bytearray()
    headers: list[str] = []
    with gzip.open(path, "rb") as fh:
        for line_number, raw in enumerate(fh, 1):
            if line_number <= HEADER_LINES:
                headers.append(raw.decode("ascii", errors="replace").rstrip("\r\n"))
                continue
            compact = b"".join(raw.split())
            if not compact:
                continue
            if any(byte < 48 or byte > 52 for byte in compact):
                raise ValueError(f"{path.name}: invalid grid token on source line {line_number}")
            values.extend(compact.translate(TRANSLATE))
            if len(values) > EXPECTED_VALUES:
                raise ValueError(f"{path.name}: more than {EXPECTED_VALUES} grid values")
    if len(headers) != HEADER_LINES:
        raise ValueError(f"{path.name}: truncated IMS header")
    if len(values) != EXPECTED_VALUES:
        raise ValueError(f"{path.name}: grid values={len(values)} expected={EXPECTED_VALUES}")
    unexpected = set(values) - ALLOWED
    if unexpected:
        raise ValueError(f"{path.name}: unexpected category codes {sorted(unexpected)}")
    if len(set(values)) < 4:
        raise ValueError(f"{path.name}: degenerate category diversity {sorted(set(values))}")
    return bytes(values), headers


if not plan_path.is_file():
    raise SystemExit(f"missing download plan; run download.sh first: {plan_path}")

with plan_path.open("r", encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
if len(plan) != 12:
    raise SystemExit(f"expected 12 pinned source rows, found {len(plan)}")

reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
index_rows: list[dict[str, object]] = []
source_rows: list[dict[str, object]] = []
aggregate_hist = Counter()

for row in plan:
    source = download_dir / "grids" / row["filename"]
    if not source.is_file():
        raise SystemExit(f"missing source file: {source}")
    pixels, headers = decode_grid(source)
    output = out_dir / f"ims_{row['date_utc']}_4km_6144x6144.bin"
    output.write_bytes(pixels)
    hist = Counter(pixels)
    aggregate_hist.update(hist)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(output),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(pixels),
        "value_count": len(pixels),
        "sample_format": "raw homogeneous uint8 category grid",
        "sample_geometry": "6144x6144_northern_hemisphere_grid",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "natural_record_kind": "complete_ims_daily_4km_analysis_grid",
        "source_format": "gzip_compressed_ims_ascii_grid",
        "source_field": "IMS 4 km daily snow_and_ice_category grid cells after the documented 30-line header",
        "source_file": rel(source),
        "analysis_date_utc": row["date_utc"],
        "day_of_year": int(row["doy"]),
        "category_histogram": {str(key): hist[key] for key in sorted(hist)},
    })
    source_rows.append({
        "analysis_date_utc": row["date_utc"],
        "day_of_year": int(row["doy"]),
        "source_file": rel(source),
        "source_size_bytes": source.stat().st_size,
        "header_lines": headers,
        "category_histogram": {str(key): hist[key] for key in sorted(hist)},
    })
    print(f"built date={row['date_utc']} values={len(pixels)} histogram={dict(sorted(hist.items()))}")

index_path = index_dir / "samples.jsonl"
with index_path.open("w", encoding="utf-8") as fh:
    for index_row in index_rows:
        fh.write(json.dumps(index_row, sort_keys=True) + "\n")

total = sum(int(row["value_count"]) for row in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "width": WIDTH,
    "height": HEIGHT,
    "header_lines": HEADER_LINES,
    "primary_values": total,
    "primary_sample_bytes": total,
    "category_histogram": {str(key): aggregate_hist[key] for key in sorted(aggregate_hist)},
    "sources": source_rows,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"built dataset={DATASET_ID} samples={len(index_rows)} values={total} bytes={total}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
