#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/weatherbench2_era5_pressure_level_fields_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="weatherbench2_era5_pressure_level_fields_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR RECIPE_DIR REPO_ROOT
python3 - <<'PY'
from __future__ import annotations

from array import array
import csv
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tomllib


repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
sys.path.insert(0, str(recipe_dir / "scripts"))
from blosc_lz4 import decompress_file


dataset_id = "weatherbench2_era5_pressure_level_fields_f32"
series_by_variable = {
    "geopotential": "era5_geopotential_pressure_levels_f32",
    "specific_humidity": "era5_specific_humidity_pressure_levels_f32",
    "temperature": "era5_temperature_pressure_levels_f32",
    "u_component_of_wind": "era5_u_wind_pressure_levels_f32",
    "v_component_of_wind": "era5_v_wind_pressure_levels_f32",
    "vertical_velocity": "era5_vertical_velocity_pressure_levels_f32",
}
expected_levels = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]
expected_per_series_samples = 64
expected_sample_values = 377_520
expected_sample_bytes = 1_510_080
expected_samples = 384
expected_total_bytes = 579_870_720

manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
if manifest.get("dataset_id") != dataset_id:
    raise SystemExit("manifest dataset_id mismatch")
manifest_series = {row["id"]: row for row in manifest.get("series", [])}
if set(manifest_series) != set(series_by_variable.values()):
    raise SystemExit("manifest series set mismatch")
for series_id, entry in manifest_series.items():
    if entry.get("role") != "primary" or entry.get("numeric_kind") != "float":
        raise SystemExit(f"invalid manifest role/type for {series_id}")
    if entry.get("bit_width") != 32 or entry.get("endianness") != "little":
        raise SystemExit(f"invalid manifest width/endianness for {series_id}")
    if entry.get("sample_count") != expected_per_series_samples:
        raise SystemExit(f"manifest sample count mismatch for {series_id}")
    if entry.get("total_size_bytes") != expected_per_series_samples * expected_sample_bytes:
        raise SystemExit(f"manifest size mismatch for {series_id}")

plan_path = download_dir / "download_plan.tsv"
index_path = index_dir / "samples.jsonl"
stats_path = filter_dir / "ingest_stats.json"
if not plan_path.is_file() or not index_path.is_file() or not stats_path.is_file():
    raise SystemExit("missing plan, sample index, or ingest statistics")
plan_rows = list(csv.DictReader(plan_path.open("r", encoding="utf-8", newline=""), delimiter="\t"))
index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(plan_rows) != 48 or len(index_rows) != expected_samples:
    raise SystemExit("unexpected plan or sample count")

indexed: dict[tuple[str, int, int], dict[str, object]] = {}
sample_paths: set[str] = set()
sample_hashes: set[str] = set()
by_series: dict[str, list[dict[str, object]]] = {series_id: [] for series_id in manifest_series}
for row in index_rows:
    key = (str(row["variable"]), int(row["source_chunk_index"]), int(row["source_time_offset"]))
    if key in indexed:
        raise SystemExit(f"duplicate index key: {key}")
    indexed[key] = row
    series_id = str(row["series_id"])
    if series_id not in by_series or series_by_variable.get(str(row["variable"])) != series_id:
        raise SystemExit(f"variable/series mismatch: {row}")
    if row.get("dataset_id") != dataset_id or row.get("role") != "primary":
        raise SystemExit(f"dataset/role mismatch: {row.get('sample_path')}")
    if row.get("numeric_kind") != "float" or row.get("bit_width") != 32:
        raise SystemExit(f"not float32: {row.get('sample_path')}")
    if row.get("endianness") != "little" or row.get("element_size_bytes") != 4:
        raise SystemExit(f"wrong byte order or element size: {row.get('sample_path')}")
    if row.get("sample_shape") != [13, 240, 121]:
        raise SystemExit(f"wrong sample shape: {row.get('sample_path')}")
    if row.get("sample_axes") != ["pressure_level", "longitude", "latitude"]:
        raise SystemExit(f"wrong sample axes: {row.get('sample_path')}")
    if row.get("pressure_levels_hpa") != expected_levels:
        raise SystemExit(f"wrong pressure levels: {row.get('sample_path')}")
    if row.get("natural_record_kind") != "era5_global_pressure_level_field_at_analysis_time":
        raise SystemExit(f"wrong natural record kind: {row.get('sample_path')}")
    if row.get("value_count") != expected_sample_values or row.get("sample_size_bytes") != expected_sample_bytes:
        raise SystemExit(f"wrong sample size metadata: {row.get('sample_path')}")
    path_text = str(row["sample_path"])
    if path_text in sample_paths:
        raise SystemExit(f"duplicate sample path: {path_text}")
    sample_paths.add(path_text)
    by_series[series_id].append(row)

for plan in plan_rows:
    variable = plan["variable"]
    chunk_index = int(plan["time_chunk_index"])
    chunk_path = download_dir / "chunks" / variable / f"{chunk_index}.0.0.0.blosc"
    if not chunk_path.is_file() or chunk_path.stat().st_size != int(plan["size_bytes"]):
        raise SystemExit(f"missing or wrong-sized compressed chunk: {chunk_path}")
    if hashlib.md5(chunk_path.read_bytes()).hexdigest() != plan["md5_hex"]:
        raise SystemExit(f"compressed chunk MD5 mismatch: {chunk_path}")
    decoded, header = decompress_file(chunk_path)
    if len(decoded) != int(plan["decoded_chunk_bytes"]) or header["typesize"] != 4:
        raise SystemExit(f"decoded chunk mismatch: {chunk_path}")
    chunk_start = datetime.fromisoformat(plan["chunk_start_time"].replace("Z", "+00:00"))
    for offset in range(8):
        key = (variable, chunk_index, offset)
        row = indexed.get(key)
        if row is None:
            raise SystemExit(f"missing indexed sample: {key}")
        expected_timestamp = (chunk_start + timedelta(hours=6 * offset)).isoformat().replace("+00:00", "Z")
        if row.get("timestamp_utc") != expected_timestamp:
            raise SystemExit(f"timestamp mismatch: {key}")
        raw = decoded[offset * expected_sample_bytes : (offset + 1) * expected_sample_bytes]
        sample = data_root / str(row["sample_path"])
        if not sample.is_file() or sample.read_bytes() != raw:
            raise SystemExit(f"sample differs from source chunk: {row['sample_path']}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row.get("sha256") or digest in sample_hashes:
            raise SystemExit(f"digest mismatch or duplicate sample: {row['sample_path']}")
        sample_hashes.add(digest)
        values = array("f")
        values.frombytes(raw)
        if sys.byteorder != "little":
            values.byteswap()
        minimum = math.inf
        maximum = -math.inf
        for value in values:
            if not math.isfinite(value):
                raise SystemExit(f"non-finite value: {row['sample_path']}")
            minimum = min(minimum, value)
            maximum = max(maximum, value)
        if not minimum < maximum:
            raise SystemExit(f"constant sample: {row['sample_path']}")

for series_id, rows in by_series.items():
    if len(rows) != expected_per_series_samples:
        raise SystemExit(f"wrong count for {series_id}: {len(rows)}")
    timestamps = {str(row["timestamp_utc"]) for row in rows}
    if len(timestamps) != expected_per_series_samples:
        raise SystemExit(f"duplicate timestamps in {series_id}")

actual_files = {
    path.relative_to(data_root).as_posix()
    for path in (data_root / "samples" / dataset_id).rglob("*.bin")
}
if actual_files != sample_paths:
    raise SystemExit("sample directory and index disagree")
total_bytes = sum(int(row["sample_size_bytes"]) for row in index_rows)
counts = [int(row["value_count"]) for row in index_rows]
if total_bytes != expected_total_bytes or statistics.median(counts) != expected_sample_values:
    raise SystemExit("aggregate size or median mismatch")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("sample_count") != expected_samples or stats.get("primary_sample_bytes") != expected_total_bytes:
    raise SystemExit("ingest statistics disagree with verified output")

print(
    f"verified series={len(by_series)} chunks={len(plan_rows)} samples={len(index_rows)} "
    f"values={sum(counts)} bytes={total_bytes} median_values={int(statistics.median(counts))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
