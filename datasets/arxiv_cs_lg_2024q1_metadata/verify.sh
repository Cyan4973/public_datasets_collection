#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="arxiv_cs_lg_2024q1_metadata"
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
    "arxiv_cs_lg_published_at_u32": ("uint", 32, 4, "I"),
    "arxiv_cs_lg_updated_at_u32": ("uint", 32, 4, "I"),
    "arxiv_cs_lg_author_count_u16": ("uint", 16, 2, "H"),
    "arxiv_cs_lg_category_count_u16": ("uint", 16, 2, "H"),
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
    prefix = array(code)
    with path.open("rb") as fh:
        prefix.frombytes(fh.read(min(count, 4096) * elem))
    if len(prefix) > 1 and len(set(prefix)) <= 1:
        raise SystemExit(f"constant sample prefix rejected: {row['sample_path']}")
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
    f"unique_entries={stats.get('unique_entries')}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
