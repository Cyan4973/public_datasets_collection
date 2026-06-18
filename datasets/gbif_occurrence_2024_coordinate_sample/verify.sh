#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gbif_occurrence_2024_coordinate_sample"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DATASET_ID FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json
import os
import statistics
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
allowed = {
    "gbif_occurrence_key_u64": ("uint", 64, 8, "Q"),
    "gbif_taxon_key_u32": ("uint", 32, 4, "I"),
    "gbif_kingdom_key_u32": ("uint", 32, 4, "I"),
    "gbif_phylum_key_u32": ("uint", 32, 4, "I"),
    "gbif_class_key_u32": ("uint", 32, 4, "I"),
    "gbif_order_key_u32": ("uint", 32, 4, "I"),
    "gbif_decimal_latitude_f64": ("float", 64, 8, "d"),
    "gbif_decimal_longitude_f64": ("float", 64, 8, "d"),
}
if stats.get("dataset_id") != dataset_id:
    raise SystemExit("stats dataset mismatch")
if len(rows) != len(allowed):
    raise SystemExit(f"unexpected sample row count: {len(rows)}")

counts = []
sizes = []
for row in rows:
    sid = row["series_id"]
    if sid not in allowed:
        raise SystemExit(f"unexpected series: {sid}")
    kind, width, elem, code = allowed[sid]
    if row.get("role") != "primary" or row["numeric_kind"] != kind or int(row["bit_width"]) != width:
        raise SystemExit(f"unexpected row metadata: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    count = int(row["value_count"])
    size = int(row["sample_size_bytes"])
    if count * elem != size or path.stat().st_size != size:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    values = array(code)
    with path.open("rb") as fh:
        values.frombytes(fh.read())
    if len(values) != count:
        raise SystemExit(f"decoded value count mismatch: {row['sample_path']}")
    if len(values) > 1 and len(set(values)) <= 1:
        raise SystemExit(f"globally constant sample rejected: {row['sample_path']}")
    counts.append(count)
    sizes.append(size)

primary_values = sum(counts)
primary_bytes = sum(sizes)
median_values = statistics.median(counts)
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary total mismatch")
if primary_values < 10_000:
    raise SystemExit(f"primary values below floor: {primary_values}")
if median_values < 1_000:
    raise SystemExit(f"median primary sample values below floor: {median_values}")

print(
    f"verified_samples={len(rows)} primary_values={primary_values} "
    f"primary_bytes={primary_bytes} median_values={median_values} "
    f"retained_rows={stats.get('retained_rows')}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
