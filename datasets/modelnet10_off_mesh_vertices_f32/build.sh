#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="modelnet10_off_mesh_vertices_f32"
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

import json
import math
import os
import shutil
import statistics
import struct
import zipfile
from pathlib import Path

DATASET_ID = "modelnet10_off_mesh_vertices_f32"
ARCHIVE = "ModelNet10.zip"
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_SAMPLES = 4_000
MIN_TOTAL_VALUES = 3_000_000
MIN_VERTEX_VALUES = 300

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive_path = download_dir / ARCHIVE
if not archive_path.is_file():
    raise SystemExit(f"missing archive: {archive_path}")


def slug(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else "_" for ch in text).split("_"))


def data_lines(text: str):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def parse_off(text: str, name: str) -> tuple[list[float], int, int]:
    lines = list(data_lines(text))
    if not lines:
        raise ValueError("empty OFF")
    first = lines[0]
    if first == "OFF":
        if len(lines) < 2:
            raise ValueError("missing OFF count line")
        count_parts = lines[1].split()
        vertex_start = 2
    elif first.startswith("OFF"):
        count_parts = first[3:].strip().split()
        vertex_start = 1
    else:
        raise ValueError("missing OFF magic")
    if len(count_parts) < 3:
        raise ValueError("bad OFF counts")
    n_vertices = int(count_parts[0])
    n_faces = int(count_parts[1])
    if n_vertices <= 0 or n_faces <= 0:
        raise ValueError("nonpositive OFF counts")
    if len(lines) < vertex_start + n_vertices:
        raise ValueError("truncated vertex block")
    values: list[float] = []
    for line in lines[vertex_start : vertex_start + n_vertices]:
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"bad vertex line in {name}")
        coords = [float(parts[0]), float(parts[1]), float(parts[2])]
        if any(not math.isfinite(value) for value in coords):
            raise ValueError(f"nonfinite vertex in {name}")
        values.extend(struct.unpack("<fff", struct.pack("<fff", *coords)))
    return values, n_vertices, n_faces


if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
bad_meshes = []
total_bytes = 0
with zipfile.ZipFile(archive_path) as zf:
    infos = sorted(
        [
            info for info in zf.infolist()
            if info.filename.lower().endswith(".off")
            and "__macosx/" not in info.filename.lower()
            and not Path(info.filename).name.startswith("._")
        ],
        key=lambda info: info.filename,
    )
    for info in infos:
        parts = Path(info.filename).parts
        if len(parts) < 4:
            bad_meshes.append({"file": info.filename, "reason": "unexpected path"})
            continue
        class_name = parts[-3]
        split = parts[-2]
        mesh_name = Path(parts[-1]).stem
        try:
            text = zf.read(info).decode("utf-8", errors="replace")
            values, vertex_count, face_count = parse_off(text, info.filename)
        except Exception as exc:
            bad_meshes.append({"file": info.filename, "reason": str(exc)})
            continue
        if len(values) < MIN_VERTEX_VALUES or len(set(values[: min(len(values), 300)])) <= 1:
            bad_meshes.append({"file": info.filename, "reason": "too small or constant"})
            continue
        series_id = f"modelnet10_{slug(class_name)}_{slug(split)}_{slug(mesh_name)}_vertices_f32"
        out_dir = samples_dir / series_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{series_id}_n{len(values):07d}.bin"
        out.write_bytes(struct.pack("<" + "f" * len(values), *values))
        size = out.stat().st_size
        total_bytes += size
        if total_bytes > MAX_PRIMARY_BYTES:
            raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": len(values),
            "sample_format": "raw homogeneous float32 OFF mesh vertex coordinate array",
            "sample_geometry": "mesh_vertex_coordinates",
            "sample_rank": 2,
            "sample_shape": [vertex_count, 3],
            "sample_axes": ["vertex", "coordinate"],
            "natural_record_kind": "modelnet10_off_mesh_vertices",
            "source_archive": ARCHIVE,
            "source_file": info.filename,
            "source_class": class_name,
            "source_split": split,
            "vertex_count": vertex_count,
            "face_count": face_count,
            "min": min(values),
            "max": max(values),
        }
        rows.append(row)
        records.append({
            "series_id": series_id,
            "class": class_name,
            "split": split,
            "vertices": vertex_count,
            "faces": face_count,
            "values": len(values),
            "sample_bytes": size,
            "min": min(values),
            "max": max(values),
        })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few accepted meshes: {len(rows)} < {MIN_SAMPLES}")
counts = sorted(int(row["value_count"]) for row in rows)
primary_values = sum(counts)
if primary_values < MIN_TOTAL_VALUES:
    raise SystemExit(f"too few total vertex values: {primary_values} < {MIN_TOTAL_VALUES}")
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(rows),
    "primary_values": primary_values,
    "primary_sample_bytes": total_bytes,
    "median_value_count": statistics.median(counts),
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "bad_meshes": bad_meshes[:100],
    "bad_mesh_count": len(bad_meshes),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(rows, key=lambda item: item["series_id"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} primary_values={primary_values} "
    f"primary_bytes={total_bytes} median_values={stats['median_value_count']} bad_meshes={len(bad_meshes)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
