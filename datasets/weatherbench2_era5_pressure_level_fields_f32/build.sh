#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/weatherbench2_era5_pressure_level_fields_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="weatherbench2_era5_pressure_level_fields_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

MAX_PRIMARY_BYTES="${ERA5_MAX_PRIMARY_BYTES:-950000000}"
export DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR MAX_PRIMARY_BYTES RECIPE_DIR REPO_ROOT SAMPLES_DIR
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
import shutil
import sys


repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])
sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
from blosc_lz4 import decompress_file


dataset_id = "weatherbench2_era5_pressure_level_fields_f32"
variables = {
    "geopotential": ("era5_geopotential_pressure_levels_f32", "m^2 s^-2"),
    "specific_humidity": ("era5_specific_humidity_pressure_levels_f32", "kg kg^-1"),
    "temperature": ("era5_temperature_pressure_levels_f32", "K"),
    "u_component_of_wind": ("era5_u_wind_pressure_levels_f32", "m s^-1"),
    "v_component_of_wind": ("era5_v_wind_pressure_levels_f32", "m s^-1"),
    "vertical_velocity": ("era5_vertical_velocity_pressure_levels_f32", "Pa s^-1"),
}
pressure_levels_hpa = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]
plan_path = download_dir / "download_plan.tsv"
if not plan_path.is_file():
    raise SystemExit(f"missing download plan: {plan_path}")
plan_rows = list(csv.DictReader(plan_path.open("r", encoding="utf-8", newline=""), delimiter="\t"))
if len(plan_rows) != 48:
    raise SystemExit(f"expected 48 compressed chunks, found {len(plan_rows)}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
for series_id, _ in variables.values():
    (samples_dir / series_id).mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)


def analyze_f32le(raw: bytes) -> tuple[float, float]:
    values = array("f")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    minimum = math.inf
    maximum = -math.inf
    for value in values:
        if not math.isfinite(value):
            raise ValueError("non-finite float32 value")
        minimum = min(minimum, value)
        maximum = max(maximum, value)
    if not minimum < maximum:
        raise ValueError(f"constant or invalid float32 sample: min={minimum} max={maximum}")
    return minimum, maximum


index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
total_bytes = 0
for chunk_ordinal, row in enumerate(plan_rows):
    variable = row["variable"]
    if variable not in variables:
        raise SystemExit(f"unexpected variable in plan: {variable}")
    series_id, units = variables[variable]
    chunk_index = int(row["time_chunk_index"])
    chunk_path = download_dir / "chunks" / variable / f"{chunk_index}.0.0.0.blosc"
    if not chunk_path.is_file() or chunk_path.stat().st_size != int(row["size_bytes"]):
        raise SystemExit(f"missing or wrong-sized compressed chunk: {chunk_path}")
    compressed_md5 = hashlib.md5(chunk_path.read_bytes()).hexdigest()
    if compressed_md5 != row["md5_hex"]:
        raise SystemExit(f"compressed MD5 mismatch: {chunk_path}")
    decoded, blosc_header = decompress_file(chunk_path)
    expected_chunk_bytes = int(row["decoded_chunk_bytes"])
    if len(decoded) != expected_chunk_bytes or blosc_header["typesize"] != 4:
        raise SystemExit(f"decoded chunk layout mismatch: {chunk_path}")
    time_count = int(row["output_samples"])
    values_per_sample = int(row["output_values_per_sample"])
    bytes_per_sample = values_per_sample * 4
    if len(decoded) != time_count * bytes_per_sample:
        raise SystemExit(f"time-slice geometry mismatch: {chunk_path}")
    chunk_start = datetime.fromisoformat(row["chunk_start_time"].replace("Z", "+00:00"))
    for offset in range(time_count):
        timestamp = chunk_start + timedelta(hours=6 * offset)
        raw = decoded[offset * bytes_per_sample : (offset + 1) * bytes_per_sample]
        try:
            minimum, maximum = analyze_f32le(raw)
        except ValueError as exc:
            raise SystemExit(f"{variable} {timestamp.isoformat()}: {exc}") from exc
        if total_bytes + len(raw) > max_primary_bytes:
            raise SystemExit(f"primary output would exceed cap: {total_bytes + len(raw)}")
        stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
        output = samples_dir / series_id / f"{variable}_{stamp}_n{values_per_sample}.bin"
        output.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        index_rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": series_id,
                "role": "primary",
                "sample_path": output.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(raw),
                "value_count": values_per_sample,
                "sample_geometry": "pressure_level_longitude_latitude_volume_3d",
                "sample_rank": 3,
                "sample_shape": [13, 240, 121],
                "sample_axes": ["pressure_level", "longitude", "latitude"],
                "pressure_levels_hpa": pressure_levels_hpa,
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "variable": variable,
                "units": units,
                "source_object": row["object_name"],
                "source_generation": row["generation"],
                "source_chunk_index": chunk_index,
                "source_time_offset": offset,
                "compressed_chunk_path": f"chunks/{variable}/{chunk_index}.0.0.0.blosc",
                "sha256": digest,
                "natural_record_kind": "era5_global_pressure_level_field_at_analysis_time",
            }
        )
        records.append(
            {
                "variable": variable,
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "minimum": minimum,
                "maximum": maximum,
                "sha256": digest,
            }
        )
        total_bytes += len(raw)
    print(
        f"decoded chunk={chunk_ordinal + 1}/{len(plan_rows)} variable={variable} "
        f"time_chunk={chunk_index} output_bytes={total_bytes}"
    )

if len(index_rows) != 384 or total_bytes != 579_870_720:
    raise SystemExit(f"unexpected output: samples={len(index_rows)} bytes={total_bytes}")
index_rows.sort(key=lambda item: str(item["sample_path"]))
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
    for row in index_rows:
        handle.write(json.dumps(row, sort_keys=True) + "\n")

series_stats = {}
for variable, (series_id, units) in variables.items():
    rows = [row for row in index_rows if row["series_id"] == series_id]
    series_stats[series_id] = {
        "variable": variable,
        "units": units,
        "sample_count": len(rows),
        "value_count": sum(int(row["value_count"]) for row in rows),
        "sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
    }
stats = {
    "dataset_id": dataset_id,
    "source_chunk_count": len(plan_rows),
    "sample_count": len(index_rows),
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "primary_sample_bytes": total_bytes,
    "sample_value_count": 377_520,
    "sample_size_bytes": 1_510_080,
    "pressure_levels_hpa": pressure_levels_hpa,
    "series": series_stats,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"built chunks={len(plan_rows)} samples={len(index_rows)} "
    f"values={stats['primary_values']} bytes={total_bytes}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
