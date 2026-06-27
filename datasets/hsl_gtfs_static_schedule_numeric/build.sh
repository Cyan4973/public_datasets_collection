#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hsl_gtfs_static_schedule_numeric"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLE_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLE_DIR
export HSL_GTFS_MIN_VALUES="${HSL_GTFS_MIN_VALUES:-1000}"
export HSL_GTFS_MAX_PRIMARY_BYTES="${HSL_GTFS_MAX_PRIMARY_BYTES:-1000000000}"
python3 - <<'PY'
from __future__ import annotations

import csv
import io
import json
import math
import os
import shutil
import statistics
import struct
import zipfile
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
ROOT = Path(os.environ["REPO_ROOT"])
DATA_ROOT = ROOT / os.environ["DATA_DIR"]
DOWNLOAD_DIR = Path(os.environ["DOWNLOAD_DIR"])
FILTER_DIR = Path(os.environ["FILTER_DIR"])
INDEX_DIR = Path(os.environ["INDEX_DIR"])
SAMPLE_DIR = Path(os.environ["SAMPLE_DIR"])
ZIP_PATH = DOWNLOAD_DIR / "hsl_gtfs.zip"
MIN_VALUES = int(os.environ["HSL_GTFS_MIN_VALUES"])
MAX_PRIMARY_BYTES = int(os.environ["HSL_GTFS_MAX_PRIMARY_BYTES"])

SPECS = {
    "stop_times_arrival_seconds_i32": ("int", 32, 4, "<i", "gtfs_table_column", 1),
    "stop_times_departure_seconds_i32": ("int", 32, 4, "<i", "gtfs_table_column", 1),
    "stop_times_stop_sequence_u32": ("uint", 32, 4, "<I", "gtfs_table_column", 1),
    "stop_times_shape_dist_traveled_f64": ("float", 64, 8, "<d", "gtfs_table_column", 1),
    "shapes_lat_lon_f64": ("float", 64, 8, "<d", "gtfs_shape_point_pairs", 2),
    "shapes_sequence_u32": ("uint", 32, 4, "<I", "gtfs_table_column", 1),
    "shapes_dist_traveled_f64": ("float", 64, 8, "<d", "gtfs_table_column", 1),
    "stops_lat_lon_f64": ("float", 64, 8, "<d", "gtfs_stop_point_pairs", 2),
    "frequencies_start_end_headway_seconds_i32": ("int", 32, 4, "<i", "gtfs_frequency_triples", 2),
}
REQUIRED_SERIES = {
    "stop_times_arrival_seconds_i32",
    "stop_times_departure_seconds_i32",
    "stop_times_stop_sequence_u32",
    "shapes_lat_lon_f64",
    "shapes_sequence_u32",
    "stops_lat_lon_f64",
}


def open_table(zf: zipfile.ZipFile, name: str):
    if name not in zf.namelist():
        raise KeyError(name)
    return io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")


def parse_time(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"bad GTFS time {value!r}")
    h, m, s = (int(part) for part in parts)
    if h < 0 or not (0 <= m < 60) or not (0 <= s < 60):
        raise ValueError(f"bad GTFS time {value!r}")
    seconds = h * 3600 + m * 60 + s
    if not (-2**31 <= seconds < 2**31):
        raise ValueError(f"GTFS time overflows int32: {value!r}")
    return seconds


def parse_u32(value: str, field: str) -> int:
    parsed = int(value.strip())
    if not (0 <= parsed <= 0xFFFFFFFF):
        raise ValueError(f"{field} out of uint32 range: {value!r}")
    return parsed


def parse_i32(value: str, field: str) -> int:
    parsed = int(value.strip())
    if not (-2**31 <= parsed < 2**31):
        raise ValueError(f"{field} out of int32 range: {value!r}")
    return parsed


def parse_f64(value: str, field: str) -> float:
    parsed = float(value.strip())
    if not math.isfinite(parsed):
        raise ValueError(f"{field} is non-finite: {value!r}")
    return parsed


def write_values(path: Path, fmt: str, values: list[int] | list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for offset in range(0, len(values), 8192):
            chunk = values[offset : offset + 8192]
            fh.write(struct.pack("<" + fmt[-1] * len(chunk), *chunk))


def emit(
    rows: list[dict[str, object]],
    series_id: str,
    values: list[int] | list[float],
    source_table: str,
    sample_shape: list[int],
    skip_counts: dict[str, int],
) -> None:
    if len(values) < MIN_VALUES:
        skip_counts[f"{series_id}:below_min_values"] = skip_counts.get(f"{series_id}:below_min_values", 0) + 1
        return
    if min(values) == max(values):
        skip_counts[f"{series_id}:constant"] = skip_counts.get(f"{series_id}:constant", 0) + 1
        return
    numeric_kind, bit_width, element_size, fmt, geometry, rank = SPECS[series_id]
    sample_size_bytes = len(values) * element_size
    rel_sample = Path("samples") / DATASET_ID / series_id / f"{series_id}.bin"
    write_values(DATA_ROOT / rel_sample, fmt, values)
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": str(rel_sample),
            "source_table": source_table,
            "numeric_kind": numeric_kind,
            "bit_width": bit_width,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": sample_size_bytes,
            "value_count": len(values),
            "sample_geometry": geometry,
            "sample_rank": rank,
            "sample_shape": sample_shape,
            "sample_axes": ["row"] if rank == 1 else ["row", "field"],
            "min": min(values),
            "max": max(values),
        }
    )


if not ZIP_PATH.is_file():
    raise SystemExit(f"missing local GTFS ZIP {ZIP_PATH}; run download.sh first")

shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
shutil.rmtree(INDEX_DIR, ignore_errors=True)
FILTER_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)
for series_id in SPECS:
    (SAMPLE_DIR / series_id).mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
skip_counts: dict[str, int] = {}
table_counts: dict[str, int] = {}

with zipfile.ZipFile(ZIP_PATH) as zf:
    with open_table(zf, "stop_times.txt") as fh:
        reader = csv.DictReader(fh)
        arrivals: list[int] = []
        departures: list[int] = []
        sequences: list[int] = []
        stop_shape_dists: list[float] = []
        for row in reader:
            arrivals.append(parse_time(row["arrival_time"]))
            departures.append(parse_time(row["departure_time"]))
            sequences.append(parse_u32(row["stop_sequence"], "stop_sequence"))
            dist = (row.get("shape_dist_traveled") or "").strip()
            if dist:
                stop_shape_dists.append(parse_f64(dist, "shape_dist_traveled"))
        table_counts["stop_times.txt"] = len(arrivals)
    emit(index_rows, "stop_times_arrival_seconds_i32", arrivals, "stop_times.txt", [len(arrivals)], skip_counts)
    emit(index_rows, "stop_times_departure_seconds_i32", departures, "stop_times.txt", [len(departures)], skip_counts)
    emit(index_rows, "stop_times_stop_sequence_u32", sequences, "stop_times.txt", [len(sequences)], skip_counts)
    emit(index_rows, "stop_times_shape_dist_traveled_f64", stop_shape_dists, "stop_times.txt", [len(stop_shape_dists)], skip_counts)

    with open_table(zf, "shapes.txt") as fh:
        reader = csv.DictReader(fh)
        shape_lat_lon: list[float] = []
        shape_sequences: list[int] = []
        shape_dists: list[float] = []
        shape_rows = 0
        for row in reader:
            lat = parse_f64(row["shape_pt_lat"], "shape_pt_lat")
            lon = parse_f64(row["shape_pt_lon"], "shape_pt_lon")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"shape coordinate out of range: {lat}, {lon}")
            shape_lat_lon.extend([lat, lon])
            shape_sequences.append(parse_u32(row["shape_pt_sequence"], "shape_pt_sequence"))
            dist = (row.get("shape_dist_traveled") or "").strip()
            if dist:
                shape_dists.append(parse_f64(dist, "shape_dist_traveled"))
            shape_rows += 1
        table_counts["shapes.txt"] = shape_rows
    emit(index_rows, "shapes_lat_lon_f64", shape_lat_lon, "shapes.txt", [shape_rows, 2], skip_counts)
    emit(index_rows, "shapes_sequence_u32", shape_sequences, "shapes.txt", [len(shape_sequences)], skip_counts)
    emit(index_rows, "shapes_dist_traveled_f64", shape_dists, "shapes.txt", [len(shape_dists)], skip_counts)

    with open_table(zf, "stops.txt") as fh:
        reader = csv.DictReader(fh)
        stops_lat_lon: list[float] = []
        stop_rows = 0
        for row in reader:
            lat = parse_f64(row["stop_lat"], "stop_lat")
            lon = parse_f64(row["stop_lon"], "stop_lon")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"stop coordinate out of range: {lat}, {lon}")
            stops_lat_lon.extend([lat, lon])
            stop_rows += 1
        table_counts["stops.txt"] = stop_rows
    emit(index_rows, "stops_lat_lon_f64", stops_lat_lon, "stops.txt", [stop_rows, 2], skip_counts)

    if "frequencies.txt" in zf.namelist():
        with open_table(zf, "frequencies.txt") as fh:
            reader = csv.DictReader(fh)
            frequencies: list[int] = []
            freq_rows = 0
            for row in reader:
                frequencies.extend(
                    [
                        parse_time(row["start_time"]),
                        parse_time(row["end_time"]),
                        parse_i32(row["headway_secs"], "headway_secs"),
                    ]
                )
                freq_rows += 1
            table_counts["frequencies.txt"] = freq_rows
        emit(
            index_rows,
            "frequencies_start_end_headway_seconds_i32",
            frequencies,
            "frequencies.txt",
            [freq_rows, 3],
            skip_counts,
        )

series_seen = {str(row["series_id"]) for row in index_rows}
missing_required = REQUIRED_SERIES - series_seen
if missing_required:
    raise SystemExit(f"missing required emitted series: {sorted(missing_required)}")
primary_counts = [int(row["value_count"]) for row in index_rows]
primary_bytes = [int(row["sample_size_bytes"]) for row in index_rows]
if sum(primary_bytes) > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {sum(primary_bytes)}")
if len(index_rows) < 2:
    raise SystemExit(f"only {len(index_rows)} primary samples emitted")
if sum(primary_counts) < 10_000 and sum(primary_bytes) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(primary_counts)} bytes={sum(primary_bytes)}")
median_values = statistics.median(primary_counts)
if median_values < 1_000:
    raise SystemExit(f"median sample values below floor: {median_values}")

with (INDEX_DIR / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

series_stats: dict[str, dict[str, int]] = {}
for row in index_rows:
    stats = series_stats.setdefault(str(row["series_id"]), {"sample_count": 0, "total_size_bytes": 0, "total_values": 0})
    stats["sample_count"] += 1
    stats["total_size_bytes"] += int(row["sample_size_bytes"])
    stats["total_values"] += int(row["value_count"])

stats = {
    "dataset_id": DATASET_ID,
    "source_zip": "hsl_gtfs.zip",
    "table_counts": table_counts,
    "primary_sample_count": len(index_rows),
    "primary_values": sum(primary_counts),
    "primary_sample_bytes": sum(primary_bytes),
    "median_primary_values": median_values,
    "min_values_per_sample": MIN_VALUES,
    "series": series_stats,
    "skip_counts": skip_counts,
}
(FILTER_DIR / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"built samples={len(index_rows)} bytes={sum(primary_bytes)} "
    f"median_values={int(median_values)} tables={table_counts} series={series_stats}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
