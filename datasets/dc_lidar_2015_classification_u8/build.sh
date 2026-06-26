#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_classification_u8"
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

MIN_SAMPLE_VALUES="${DC_LIDAR_MIN_SAMPLE_VALUES:-1000}"
MAX_PRIMARY_BYTES="${DC_LIDAR_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_SAMPLE_VALUES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
import struct
from collections import Counter
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_sample_values = int(os.environ["MIN_SAMPLE_VALUES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "dc_lidar_2015_classification_u8"
FAMILY = "dc_lidar_classification_code_u8"
MASK_OLD_CLASS = bytes([b & 0x1F for b in range(256)])


def read_las_layout(path: Path) -> dict[str, int]:
    with path.open("rb") as fh:
        header = fh.read(375)
    if len(header) < 227 or header[:4] != b"LASF":
        raise ValueError("not LAS")
    point_offset = struct.unpack_from("<I", header, 96)[0]
    point_format = header[104] & 0x3F
    record_length = struct.unpack_from("<H", header, 105)[0]
    legacy_count = struct.unpack_from("<I", header, 107)[0]
    point_count = legacy_count
    if len(header) >= 255 and point_count == 0:
        point_count = struct.unpack_from("<Q", header, 247)[0]
    if point_format > 10:
        raise ValueError(f"unsupported point format {point_format}")
    class_offset = 15 if point_format <= 5 else 16
    if record_length <= class_offset or point_count <= 0:
        raise ValueError("invalid point record layout")
    if point_offset + point_count * record_length > path.stat().st_size:
        raise ValueError("truncated point records")
    return {
        "point_offset": point_offset,
        "point_format": point_format,
        "record_length": record_length,
        "point_count": point_count,
        "class_offset": class_offset,
    }


plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_tiny = 0
skipped_constant = 0
skipped_invalid = 0
total_primary_bytes = 0

with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        source = download_dir / row["local_path"]
        if source.suffix.lower() == ".laz":
            skipped_invalid += 1
            continue
        if not source.is_file():
            raise SystemExit(f"missing LAS file {source}")
        try:
            layout = read_las_layout(source)
        except ValueError as exc:
            skipped_invalid += 1
            print(f"skip_invalid source={source.name} reason={exc}")
            continue
        point_count = layout["point_count"]
        if point_count < min_sample_values:
            skipped_tiny += 1
            continue
        if total_primary_bytes + point_count > max_primary_bytes:
            break

        out = out_dir / f"{source.stem}_classification_code_n{point_count:010d}.bin"
        tmp = out.with_suffix(".bin.tmp")
        histogram: Counter[int] = Counter()
        remaining = point_count
        records_per_chunk = max(1, (32 * 1024 * 1024) // layout["record_length"])
        with source.open("rb") as src, tmp.open("wb") as dst:
            src.seek(layout["point_offset"])
            while remaining:
                take = min(remaining, records_per_chunk)
                chunk = src.read(take * layout["record_length"])
                if len(chunk) != take * layout["record_length"]:
                    raise SystemExit(f"{source.name}: truncated during classification extraction")
                classes = chunk[layout["class_offset"] :: layout["record_length"]]
                if layout["point_format"] <= 5:
                    classes = classes.translate(MASK_OLD_CLASS)
                dst.write(classes)
                histogram.update(classes)
                remaining -= take

        if len(histogram) <= 1:
            tmp.unlink(missing_ok=True)
            skipped_constant += 1
            continue
        tmp.rename(out)
        total_primary_bytes += out.stat().st_size
        class_hist = {str(k): int(v) for k, v in sorted(histogram.items())}
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": point_count,
            "sample_geometry": "las_point_attribute_stream",
            "sample_rank": 1,
            "sample_shape": [point_count],
            "sample_axes": ["point"],
            "source_name": row["name"],
            "source_key": row["key"],
            "source_url": row["url"],
            "source_bytes": source.stat().st_size,
            "container_format": "las",
            "point_format": layout["point_format"],
            "point_record_length": layout["record_length"],
            "classification_offset": layout["class_offset"],
            "old_format_classification_bits_masked": layout["point_format"] <= 5,
            "natural_record_kind": "las_tile",
        })
        records.append({
            "source_name": row["name"],
            "source_bytes": source.stat().st_size,
            "point_count": point_count,
            "point_format": layout["point_format"],
            "point_record_length": layout["record_length"],
            "classification_histogram": class_hist,
        })

if not index_rows:
    raise SystemExit(
        f"no qualifying LAS classification samples; skipped_tiny={skipped_tiny} "
        f"skipped_constant={skipped_constant} skipped_invalid={skipped_invalid}"
    )

counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(index_rows),
    "skipped_tiny": skipped_tiny,
    "skipped_constant": skipped_constant,
    "skipped_invalid": skipped_invalid,
    "primary_values": sum(counts),
    "primary_sample_bytes": total_primary_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "max_primary_bytes": max_primary_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        out.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(index_rows)} bytes={total_primary_bytes} "
    f"median={stats['median_value_count']} range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
