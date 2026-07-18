#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_open_buildings_v3_s2_073_geometry_f32"
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

MIN_BUILDINGS="${OPEN_BUILDINGS_BUILD_MIN_BUILDINGS:-500000}"
MIN_VERTEX_PAIRS="${OPEN_BUILDINGS_MIN_VERTEX_PAIRS:-2500000}"
MAX_PRIMARY_BYTES="${OPEN_BUILDINGS_MAX_PRIMARY_BYTES:-950000000}"
HARD_MAX_PRIMARY_BYTES=1000000000
if (( MAX_PRIMARY_BYTES > HARD_MAX_PRIMARY_BYTES )); then
  echo "requested max primary bytes $MAX_PRIMARY_BYTES exceeds hard cap $HARD_MAX_PRIMARY_BYTES; clamping"
  MAX_PRIMARY_BYTES="$HARD_MAX_PRIMARY_BYTES"
fi

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_BUILDINGS MIN_VERTEX_PAIRS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import shutil
import sys
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_buildings = int(os.environ["MIN_BUILDINGS"])
min_vertex_pairs = int(os.environ["MIN_VERTEX_PAIRS"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "google_open_buildings_v3_s2_073_geometry_f32"
FAMILY = "open_buildings_v3_s2_073_geometry_f32"
SOURCE = download_dir / "073_buildings.csv.gz"
PER_BUILDING_BYTES = 4 * 4
PER_VERTEX_PAIR_BYTES = 2 * 4
CHUNK_VALUES = 200000

if not SOURCE.is_file():
    raise SystemExit(f"missing source file: {SOURCE}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

little = sys.byteorder == "little"
paths = {
    "centroid_lat_lon_f32": out_dir / "centroid_lat_lon_f32.bin",
    "area_in_meters_f32": out_dir / "area_in_meters_f32.bin",
    "confidence_f32": out_dir / "confidence_f32.bin",
    "polygon_vertex_lon_lat_f32": out_dir / "polygon_vertex_lon_lat_f32.bin",
}
files = {name: path.open("wb") for name, path in paths.items()}
buffers = {name: array("f") for name in paths}
mins = {name: math.inf for name in paths}
maxs = {name: -math.inf for name in paths}
building_count = 0
vertex_pairs = 0
source_rows_seen = 0
truncated_for_cap = False


def flush() -> None:
    for name, buf in buffers.items():
        if not buf:
            continue
        if little:
            buf.tofile(files[name])
        else:
            copy = array("f", buf)
            copy.byteswap()
            copy.tofile(files[name])
        buffers[name] = array("f")


COORD_RE = re.compile(
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)


def parse_polygon_lon_lat_pairs(wkt: str) -> list[tuple[float, float]]:
    if not (
        wkt.startswith("POLYGON((")
        or wkt.startswith("POLYGON ((")
        or wkt.startswith("MULTIPOLYGON(((")
        or wkt.startswith("MULTIPOLYGON (((")
    ):
        raise ValueError(f"unsupported WKT polygon: {wkt[:64]!r}")
    pairs: list[tuple[float, float]] = []
    for match in COORD_RE.finditer(wkt):
        lon = float(match.group(1))
        lat = float(match.group(2))
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError(f"polygon vertex outside lon/lat range: {lon},{lat}")
        pairs.append((lon, lat))
    if len(pairs) < 4:
        raise ValueError("too few polygon vertices")
    return pairs


try:
    with gzip.open(SOURCE, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise SystemExit("missing Open Buildings CSV header")
        required = {"latitude", "longitude", "area_in_meters", "confidence", "geometry"}
        missing = sorted(required - {field.strip() for field in reader.fieldnames})
        if missing:
            raise SystemExit(f"missing required fields: {missing}")
        for row in reader:
            source_rows_seen += 1
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            area = float(row["area_in_meters"])
            confidence = float(row["confidence"])
            vertices = parse_polygon_lon_lat_pairs(row["geometry"])
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise SystemExit(f"bad centroid near row {source_rows_seen}: {lat},{lon}")
            if not (math.isfinite(area) and area > 0.0):
                raise SystemExit(f"bad area near row {source_rows_seen}: {area}")
            if not (0.0 <= confidence <= 1.0):
                raise SystemExit(f"bad confidence near row {source_rows_seen}: {confidence}")
            next_bytes = PER_BUILDING_BYTES + len(vertices) * PER_VERTEX_PAIR_BYTES
            current_bytes = building_count * PER_BUILDING_BYTES + vertex_pairs * PER_VERTEX_PAIR_BYTES
            if current_bytes + next_bytes > max_primary_bytes:
                truncated_for_cap = True
                break
            for value in (lat, lon):
                buffers["centroid_lat_lon_f32"].append(value)
                mins["centroid_lat_lon_f32"] = min(mins["centroid_lat_lon_f32"], value)
                maxs["centroid_lat_lon_f32"] = max(maxs["centroid_lat_lon_f32"], value)
            buffers["area_in_meters_f32"].append(area)
            mins["area_in_meters_f32"] = min(mins["area_in_meters_f32"], area)
            maxs["area_in_meters_f32"] = max(maxs["area_in_meters_f32"], area)
            buffers["confidence_f32"].append(confidence)
            mins["confidence_f32"] = min(mins["confidence_f32"], confidence)
            maxs["confidence_f32"] = max(maxs["confidence_f32"], confidence)
            for vertex_lon, vertex_lat in vertices:
                buffers["polygon_vertex_lon_lat_f32"].extend((vertex_lon, vertex_lat))
                mins["polygon_vertex_lon_lat_f32"] = min(
                    mins["polygon_vertex_lon_lat_f32"], vertex_lon, vertex_lat
                )
                maxs["polygon_vertex_lon_lat_f32"] = max(
                    maxs["polygon_vertex_lon_lat_f32"], vertex_lon, vertex_lat
                )
            building_count += 1
            vertex_pairs += len(vertices)
            if sum(len(buf) for buf in buffers.values()) >= CHUNK_VALUES:
                flush()
    flush()
finally:
    for fh in files.values():
        fh.close()

if building_count < min_buildings:
    raise SystemExit(f"too few buildings: {building_count} < {min_buildings}")
if vertex_pairs < min_vertex_pairs:
    raise SystemExit(f"too few polygon vertex pairs: {vertex_pairs} < {min_vertex_pairs}")

expected_sizes = {
    "centroid_lat_lon_f32": building_count * 2 * 4,
    "area_in_meters_f32": building_count * 4,
    "confidence_f32": building_count * 4,
    "polygon_vertex_lon_lat_f32": vertex_pairs * 2 * 4,
}
records: list[dict[str, object]] = []
total_bytes = 0
for name, path in paths.items():
    size = path.stat().st_size
    if size != expected_sizes[name]:
        raise SystemExit(f"size mismatch for {name}: {size} != {expected_sizes[name]}")
    total_bytes += size
    value_count = size // 4
    if mins[name] == maxs[name]:
        raise SystemExit(f"constant sample should not be accepted: {name}")
    if name == "centroid_lat_lon_f32":
        shape = [building_count, 2]
        axes = ["building", "lat_lon"]
        geometry = "centroid_lat_lon_pairs"
    elif name == "polygon_vertex_lon_lat_f32":
        shape = [vertex_pairs, 2]
        axes = ["polygon_vertex", "lon_lat"]
        geometry = "polygon_vertex_lon_lat_pairs"
    else:
        shape = [building_count]
        axes = ["building"]
        geometry = "building_scalar_field"
    records.append({
        "dataset_id": DATASET_ID,
        "series_id": f"open_buildings_073_{name}",
        "family": FAMILY,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": size,
        "value_count": value_count,
        "sample_geometry": geometry,
        "sample_rank": len(shape),
        "sample_shape": shape,
        "sample_axes": axes,
        "source_field_name": name,
        "source_path": SOURCE.as_posix(),
        "min_value": mins[name],
        "max_value": maxs[name],
        "natural_record_kind": "google_open_buildings_footprint_geometry",
    })

if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary output exceeds cap: {total_bytes} > {max_primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "source_file": SOURCE.name,
    "source_bytes": SOURCE.stat().st_size,
    "source_rows_seen": source_rows_seen,
    "buildings": building_count,
    "polygon_vertex_pairs": vertex_pairs,
    "truncated_for_cap": truncated_for_cap,
    "samples": len(records),
    "primary_values": sum(record["value_count"] for record in records),
    "primary_sample_bytes": total_bytes,
    "max_primary_bytes": max_primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for record in records:
        out.write(json.dumps(record, sort_keys=True) + "\n")

print(
    f"built samples={len(records)} buildings={building_count} vertex_pairs={vertex_pairs} "
    f"values={stats['primary_values']} bytes={total_bytes} truncated_for_cap={truncated_for_cap}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
