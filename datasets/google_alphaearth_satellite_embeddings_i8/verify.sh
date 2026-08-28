#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/google_alphaearth_satellite_embeddings_i8"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_alphaearth_satellite_embeddings_i8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

if ! command -v zstd >/dev/null 2>&1; then
  echo "FATAL: zstd command is required" >&2
  exit 1
fi

export DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR RECIPE_DIR REPO_ROOT
python3 - <<'PY'
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tomllib


repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
family = "alphaearth_embedding_axis_i8"
expected_sources = 6
expected_samples = expected_sources * 64
expected_sample_bytes = 1024 * 1024
expected_total_bytes = expected_samples * expected_sample_bytes

manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
if manifest.get("dataset_id") != os.environ["DATASET_ID"]:
    raise SystemExit("manifest dataset_id mismatch")
series = manifest.get("series", [])
if len(series) != 1 or series[0].get("id") != family:
    raise SystemExit("manifest series mismatch")
if series[0].get("numeric_kind") != "int" or series[0].get("bit_width") != 8:
    raise SystemExit("manifest does not declare signed int8")
if series[0].get("endianness") != "little":
    raise SystemExit("manifest does not declare little-endian output")
if series[0].get("sample_count") != expected_samples or series[0].get("total_size_bytes") != expected_total_bytes:
    raise SystemExit("manifest sample count or total size mismatch")

plan_path = download_dir / "download_plan.tsv"
index_path = index_dir / "samples.jsonl"
stats_path = filter_dir / "ingest_stats.json"
if not plan_path.is_file() or not index_path.is_file() or not stats_path.is_file():
    raise SystemExit("missing plan, sample index, or ingest statistics")
plan_rows = list(csv.DictReader(plan_path.open("r", encoding="utf-8", newline=""), delimiter="\t"))
index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(plan_rows) != expected_samples or len(index_rows) != expected_samples:
    raise SystemExit(f"expected {expected_samples} plan/index rows")
plan_by_id = {row["sample_id"]: row for row in plan_rows}
if len(plan_by_id) != expected_samples:
    raise SystemExit("duplicate sample IDs in download plan")

by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
sample_paths: set[str] = set()
sample_hashes: set[str] = set()
total_bytes = 0
for ordinal, row in enumerate(index_rows):
    if row.get("dataset_id") != os.environ["DATASET_ID"] or row.get("series_id") != family:
        raise SystemExit("index dataset or family mismatch")
    if row.get("role") != "primary" or row.get("numeric_kind") != "int":
        raise SystemExit(f"invalid role or numeric kind: {row.get('sample_path')}")
    if row.get("bit_width") != 8 or row.get("element_size_bytes") != 1 or row.get("endianness") != "little":
        raise SystemExit(f"invalid int8 representation: {row.get('sample_path')}")
    if row.get("sample_shape") != [1024, 1024] or row.get("sample_axes") != ["y", "x"]:
        raise SystemExit(f"invalid sample geometry: {row.get('sample_path')}")
    if row.get("natural_record_kind") != "alphaearth_embedding_axis_cog_internal_tile":
        raise SystemExit(f"invalid natural record kind: {row.get('sample_path')}")
    sample_path = str(row["sample_path"])
    if sample_path in sample_paths:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    sample_paths.add(sample_path)
    sample = data_root / sample_path
    if not sample.is_file() or sample.stat().st_size != expected_sample_bytes:
        raise SystemExit(f"missing or wrong-sized sample: {sample_path}")
    raw = sample.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row.get("sha256"):
        raise SystemExit(f"sample digest mismatch: {sample_path}")
    if digest in sample_hashes:
        raise SystemExit(f"duplicate sample payload: {sample_path}")
    sample_hashes.add(digest)
    histogram = Counter(raw)
    if len(histogram) < 16:
        raise SystemExit(f"degenerate sample: {sample_path}")
    if histogram.get(128, 0) / len(raw) > 0.25:
        raise SystemExit(f"excess -128 NoData: {sample_path}")

    sample_id = Path(sample_path).name.rsplit("_n", 1)[0]
    plan = plan_by_id.get(sample_id)
    if plan is None:
        raise SystemExit(f"sample absent from download plan: {sample_id}")
    chunk = download_dir / plan["chunk_path"]
    if not chunk.is_file() or chunk.stat().st_size != int(plan["byte_count"]):
        raise SystemExit(f"missing or invalid compressed chunk: {chunk}")
    completed = subprocess.run(
        ["zstd", "-q", "-d", "-c", str(chunk)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0 or completed.stdout != raw:
        raise SystemExit(f"sample is not the exact decoded source chunk: {sample_path}")
    by_source[str(row["source_id"])].append(row)
    total_bytes += len(raw)
    if (ordinal + 1) % 32 == 0:
        print(f"verified samples={ordinal + 1}/{len(index_rows)}")

if len(by_source) != expected_sources:
    raise SystemExit(f"expected {expected_sources} sources, found {len(by_source)}")
for source_id, rows in by_source.items():
    axes = {int(row["embedding_axis_index"]) for row in rows}
    locations = {(int(row["tiff_tile_x"]), int(row["tiff_tile_y"])) for row in rows}
    if axes != set(range(64)) or len(rows) != 64:
        raise SystemExit(f"incomplete axis coverage for {source_id}")
    if len(locations) != 1:
        raise SystemExit(f"embedding axes are not spatially aligned for {source_id}")

if total_bytes != expected_total_bytes:
    raise SystemExit(f"unexpected total bytes: {total_bytes} != {expected_total_bytes}")
counts = [int(row["value_count"]) for row in index_rows]
if statistics.median(counts) != expected_sample_bytes:
    raise SystemExit("unexpected median sample size")
actual_files = {
    path.relative_to(data_root).as_posix()
    for path in (data_root / "samples" / os.environ["DATASET_ID"]).rglob("*.bin")
}
if actual_files != sample_paths:
    raise SystemExit("sample directory and index disagree")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("sample_count") != expected_samples or stats.get("primary_sample_bytes") != expected_total_bytes:
    raise SystemExit("ingest statistics disagree with verified output")

print(
    f"verified family={family} sources={len(by_source)} samples={len(index_rows)} "
    f"values={sum(counts)} total_bytes={total_bytes} median_values={int(statistics.median(counts))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
