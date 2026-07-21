#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="natural_earth_10m_geometry_xy_f64"
LEGACY_DATASET_ID="natural_earth_vector_shp_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LEGACY_DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$LEGACY_DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

MIN_VALUES_PER_SAMPLE="${NATURAL_EARTH_MIN_VALUES_PER_SAMPLE:-1000}"
MAX_PRIMARY_BYTES="${NATURAL_EARTH_MAX_PRIMARY_BYTES:-1000000000}"
MIN_PRIMARY_VALUES="${NATURAL_EARTH_MIN_PRIMARY_VALUES:-10000}"
MIN_PRIMARY_BYTES="${NATURAL_EARTH_MIN_PRIMARY_BYTES:-102400}"
SOURCE_ZIP_DIR="${NATURAL_EARTH_SOURCE_ZIP_DIR:-}"
if [[ -z "$SOURCE_ZIP_DIR" ]]; then
  if compgen -G "$DOWNLOAD_DIR/zips/*.zip" > /dev/null; then
    SOURCE_ZIP_DIR="$DOWNLOAD_DIR/zips"
  elif compgen -G "$LEGACY_DOWNLOAD_DIR/zips/*.zip" > /dev/null; then
    SOURCE_ZIP_DIR="$LEGACY_DOWNLOAD_DIR/zips"
    echo "using legacy local ZIP cache: $SOURCE_ZIP_DIR"
  else
    SOURCE_ZIP_DIR="$DOWNLOAD_DIR/zips"
  fi
fi

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR SOURCE_ZIP_DIR
export MIN_VALUES_PER_SAMPLE MAX_PRIMARY_BYTES MIN_PRIMARY_VALUES MIN_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

from array import array
import json
import math
import os
import shutil
import statistics
import struct
import sys
import zipfile
from pathlib import Path

DATASET_ID = "natural_earth_10m_geometry_xy_f64"
SERIES_ID = "natural_earth_10m_feature_xy_f64"
SHAPE_TYPE_NAMES = {1: "point", 3: "polyline", 5: "polygon"}
KEEP_SHAPE_TYPES = {3, 5}
COORD_EPSILON = 1e-9

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source_zip_dir = Path(os.environ["SOURCE_ZIP_DIR"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])
min_primary_values = int(os.environ["MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["MIN_PRIMARY_BYTES"])

if not source_zip_dir.is_dir():
    raise SystemExit(f"missing Natural Earth ZIP directory: {source_zip_dir}")


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def read_i32_le(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<i", payload, offset)[0]


def read_f64_pair(payload: bytes, offset: int) -> tuple[float, float]:
    return struct.unpack_from("<2d", payload, offset)


def validate_lon_lat(x: float, y: float, context: str) -> None:
    if not (math.isfinite(x) and math.isfinite(y)):
        raise RuntimeError(f"{context}: non-finite coordinate {x},{y}")
    if not (
        -180.0 - COORD_EPSILON <= x <= 180.0 + COORD_EPSILON
        and -90.0 - COORD_EPSILON <= y <= 90.0 + COORD_EPSILON
    ):
        raise RuntimeError(f"{context}: coordinate outside lon/lat range {x},{y}")


def write_f64(path: Path, values: list[float]) -> None:
    out = array("d", values)
    if sys.byteorder != "little":
        out.byteswap()
    with path.open("wb") as fh:
        out.tofile(fh)


def parse_shp_records(payload: bytes, shp_name: str) -> tuple[int, list[dict[str, object]]]:
    if len(payload) < 100:
        raise RuntimeError(f"{shp_name}: shapefile shorter than 100-byte header")
    file_code = struct.unpack(">I", payload[:4])[0]
    file_length_words = struct.unpack(">I", payload[24:28])[0]
    version = read_i32_le(payload, 28)
    file_shape_type = read_i32_le(payload, 32)
    if file_code != 9994 or version != 1000:
        raise RuntimeError(f"{shp_name}: invalid shapefile header code={file_code} version={version}")
    expected_bytes = file_length_words * 2
    if expected_bytes != len(payload):
        raise RuntimeError(f"{shp_name}: shapefile header length {expected_bytes} != actual {len(payload)}")
    if file_shape_type not in SHAPE_TYPE_NAMES:
        raise RuntimeError(f"{shp_name}: unsupported file shape_type={file_shape_type}")

    records: list[dict[str, object]] = []
    offset = 100
    while offset + 8 <= len(payload):
        record_number, content_words = struct.unpack(">2i", payload[offset : offset + 8])
        content_start = offset + 8
        content_end = content_start + content_words * 2
        if content_end > len(payload):
            raise RuntimeError(f"{shp_name}: truncated record {record_number}")
        content = payload[content_start:content_end]
        if len(content) < 4:
            raise RuntimeError(f"{shp_name}: short record {record_number}")
        shape_type = read_i32_le(content, 0)
        if shape_type == 0:
            offset = content_end
            continue
        if shape_type != file_shape_type:
            raise RuntimeError(
                f"{shp_name}: record {record_number} shape_type={shape_type} differs from file type {file_shape_type}"
            )
        if shape_type == 1:
            if len(content) != 20:
                raise RuntimeError(f"{shp_name}: bad point record length {record_number}")
            x, y = read_f64_pair(content, 4)
            validate_lon_lat(x, y, f"{shp_name} record {record_number}")
            records.append(
                {
                    "record_number": record_number,
                    "shape_type": shape_type,
                    "part_count": 1,
                    "point_count": 1,
                    "values": [x, y],
                }
            )
        elif shape_type in KEEP_SHAPE_TYPES:
            if len(content) < 44:
                raise RuntimeError(f"{shp_name}: short poly record {record_number}")
            part_count = read_i32_le(content, 36)
            point_count = read_i32_le(content, 40)
            if part_count < 1 or point_count < 1:
                raise RuntimeError(f"{shp_name}: empty poly record {record_number}")
            expected_len = 44 + part_count * 4 + point_count * 16
            if len(content) != expected_len:
                raise RuntimeError(
                    f"{shp_name}: record {record_number} length {len(content)} != expected {expected_len}"
                )
            part_offsets = [
                read_i32_le(content, 44 + index * 4) for index in range(part_count)
            ]
            if part_offsets[0] != 0 or sorted(part_offsets) != part_offsets:
                raise RuntimeError(f"{shp_name}: invalid part offsets in record {record_number}")
            if part_offsets[-1] >= point_count:
                raise RuntimeError(f"{shp_name}: part offset beyond points in record {record_number}")
            points_offset = 44 + part_count * 4
            values: list[float] = []
            for index in range(point_count):
                x, y = read_f64_pair(content, points_offset + index * 16)
                validate_lon_lat(x, y, f"{shp_name} record {record_number} point {index}")
                values.extend((x, y))
            records.append(
                {
                    "record_number": record_number,
                    "shape_type": shape_type,
                    "part_count": part_count,
                    "point_count": point_count,
                    "values": values,
                }
            )
        else:
            raise RuntimeError(f"{shp_name}: unsupported record shape_type={shape_type}")
        offset = content_end
    if offset != len(payload):
        raise RuntimeError(f"{shp_name}: trailing bytes after records")
    return file_shape_type, records


out_dir = samples_dir / SERIES_ID
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows: list[dict[str, object]] = []
layers: list[dict[str, object]] = []
selected_values = 0
selected_bytes = 0
skipped_small_records = 0
skipped_point_records = 0
sample_ordinal = 0

zip_paths = sorted(source_zip_dir.glob("*.zip"))
if len(zip_paths) != 12:
    raise SystemExit(f"expected 12 Natural Earth ZIPs, found {len(zip_paths)} in {source_zip_dir}")

for zip_path in zip_paths:
    with zipfile.ZipFile(zip_path) as zf:
        shp_names = [name for name in zf.namelist() if name.lower().endswith(".shp")]
        if len(shp_names) != 1:
            raise RuntimeError(f"{zip_path.name}: expected exactly one .shp member, found {shp_names}")
        shp_name = shp_names[0]
        payload = zf.read(shp_name)
    file_shape_type, records = parse_shp_records(payload, shp_name)
    layer_selected = 0
    layer_values = 0
    for record in records:
        shape_type = int(record["shape_type"])
        values = record["values"]
        assert isinstance(values, list)
        if shape_type not in KEEP_SHAPE_TYPES:
            skipped_point_records += 1
            continue
        if len(values) < min_values_per_sample:
            skipped_small_records += 1
            continue
        sample_size_bytes = len(values) * 8
        if selected_bytes + sample_size_bytes > max_primary_bytes:
            raise RuntimeError(
                f"primary output would exceed cap: {selected_bytes + sample_size_bytes} > {max_primary_bytes}"
            )
        sample_ordinal += 1
        layer_stem = Path(shp_name).stem
        record_number = int(record["record_number"])
        out = out_dir / f"{sample_ordinal:05d}_{layer_stem}_rec{record_number:06d}.bin"
        write_f64(out, values)
        min_value = min(values)
        max_value = max(values)
        if min_value == max_value:
            raise RuntimeError(f"constant geometry record should not be accepted: {out.name}")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "family": SERIES_ID,
            "role": "primary",
            "sample_path": rel(out),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": sample_size_bytes,
            "value_count": len(values),
            "sample_geometry": "shapefile_feature_xy_pairs",
            "sample_rank": 2,
            "sample_shape": [int(record["point_count"]), 2],
            "sample_axes": ["point", "xy"],
            "natural_record_kind": "natural_earth_shapefile_feature_geometry",
            "source_zip": zip_path.name,
            "source_member": shp_name,
            "source_record_number": record_number,
            "source_shape_type": shape_type,
            "source_shape_type_name": SHAPE_TYPE_NAMES[shape_type],
            "part_count": int(record["part_count"]),
            "point_count": int(record["point_count"]),
            "min_value": min_value,
            "max_value": max_value,
        }
        rows.append(row)
        selected_values += len(values)
        selected_bytes += sample_size_bytes
        layer_selected += 1
        layer_values += len(values)
    layers.append(
        {
            "zip": zip_path.name,
            "shp_member": shp_name,
            "file_shape_type": file_shape_type,
            "file_shape_type_name": SHAPE_TYPE_NAMES[file_shape_type],
            "source_records": len(records),
            "selected_records": layer_selected,
            "selected_values": layer_values,
        }
    )

if not rows:
    raise SystemExit("no Natural Earth geometry records selected")
sample_value_counts = [int(row["value_count"]) for row in rows]
if selected_values < min_primary_values:
    raise SystemExit(f"too few primary values: {selected_values} < {min_primary_values}")
if selected_bytes < min_primary_bytes:
    raise SystemExit(f"primary payload too small: {selected_bytes} < {min_primary_bytes}")
if statistics.median(sample_value_counts) < min_values_per_sample:
    raise SystemExit("median primary sample size below floor")
if len(set(sample_value_counts)) < 2:
    raise SystemExit("selected samples have identical sizes")

stats = {
    "dataset_id": DATASET_ID,
    "source_zip_dir": str(source_zip_dir),
    "layers": layers,
    "source_layer_count": len(layers),
    "sample_count": len(rows),
    "total_values": selected_values,
    "total_bytes": selected_bytes,
    "min_values_per_sample": min(sample_value_counts),
    "median_values_per_sample": statistics.median(sample_value_counts),
    "max_values_per_sample": max(sample_value_counts),
    "skipped_point_records": skipped_point_records,
    "skipped_small_records": skipped_small_records,
    "max_primary_bytes": max_primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
