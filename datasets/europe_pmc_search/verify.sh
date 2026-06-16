#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="europe_pmc_search"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import calendar
import json
import os
import statistics
import struct
from datetime import datetime
from pathlib import Path

DATASET_ID = "europe_pmc_search"
EXPECTED_SERIES = {
    "europepmc_first_publication_date": ("auxiliary", "I", 4),
    "europepmc_cited_by_count": ("primary", "I", 4),
    "europepmc_author_count": ("primary", "H", 2),
    "europepmc_title_length": ("primary", "H", 2),
    "europepmc_pub_type_count": ("primary", "H", 2),
    "europepmc_fulltext_id_count": ("primary", "H", 2),
    "europepmc_journal_title_length": ("primary", "H", 2),
}
MIN_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if {row["series_id"] for row in rows} != set(EXPECTED_SERIES):
    raise SystemExit(f"unexpected series set: {sorted(row['series_id'] for row in rows)}")
if stats.get("dataset_id") != DATASET_ID:
    raise SystemExit(f"unexpected stats dataset: {stats.get('dataset_id')}")
if int(stats.get("kept_records", 0)) < MIN_RECORDS:
    raise SystemExit(f"kept Europe PMC records below repair floor: {stats.get('kept_records')}")

sizes = []
counts = []
decoded: dict[str, tuple[int, ...]] = {}
for row in rows:
    sid = row["series_id"]
    role, code, element_size = EXPECTED_SERIES[sid]
    if row["dataset_id"] != DATASET_ID or row.get("role") != role:
        raise SystemExit(f"unexpected dataset/role row: {row}")
    if row["numeric_kind"] != "uint" or int(row["element_size_bytes"]) != element_size:
        raise SystemExit(f"unexpected numeric row: {row}")
    if row.get("sample_geometry") != "sequence" or int(row.get("sample_rank", 0)) != 1:
        raise SystemExit(f"unexpected sample geometry: {row}")
    if row.get("sample_axes") != ["publication_sorted_by_first_publication_date"]:
        raise SystemExit(f"unexpected sample axes: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    expected_size = int(row["sample_size_bytes"])
    expected_count = int(row["value_count"])
    if path.stat().st_size != expected_size or expected_size != expected_count * element_size:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    if row.get("sample_shape") != [expected_count]:
        raise SystemExit(f"sample shape/count mismatch: {row}")
    values = struct.unpack("<" + code * expected_count, path.read_bytes())
    if expected_count != int(stats["kept_records"]):
        raise SystemExit(f"series/count mismatch for {sid}: {expected_count} vs {stats['kept_records']}")
    if role == "primary":
        if len(set(values)) <= 1:
            raise SystemExit(f"constant primary series rejected: {sid}")
        sizes.append(expected_size)
        counts.append(expected_count)
    decoded[sid] = values

primary_values = sum(counts)
primary_bytes = sum(sizes)
median_values = statistics.median(counts)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary total mismatch")

dates = decoded["europepmc_first_publication_date"]
if any(a > b for a, b in zip(dates, dates[1:])):
    raise SystemExit("first publication dates are not sorted")
start = calendar.timegm(datetime.strptime(stats["start_date"], "%Y-%m-%d").utctimetuple())
end_dt = datetime.strptime(stats["end_date"], "%Y-%m-%d")
end = calendar.timegm(end_dt.utctimetuple())
if min(dates) < start or max(dates) > end:
    raise SystemExit("first publication dates fall outside configured query window")

print(
    f"verified_samples={len(rows)} kept_records={stats['kept_records']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} source_bytes={stats.get('source_bytes', 0)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
