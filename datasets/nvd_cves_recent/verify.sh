#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cves_recent"
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

DATASET_ID = "nvd_cves_recent"
EXPECTED_SERIES = {
    "nvd_published_at": ("I", 4),
    "nvd_last_modified_at": ("I", 4),
    "nvd_reference_count": ("H", 2),
    "nvd_cvss_base_score_x10": ("H", 2),
    "nvd_primary_cwe_id": ("H", 2),
    "nvd_cpe_match_count": ("H", 2),
}
MIN_CVE_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if {row["series_id"] for row in rows} != set(EXPECTED_SERIES):
    raise SystemExit(f"unexpected series set: {sorted(row['series_id'] for row in rows)}")
if stats.get("dataset_id") != DATASET_ID:
    raise SystemExit(f"unexpected stats dataset: {stats.get('dataset_id')}")
if int(stats.get("kept_cve_records", 0)) < MIN_CVE_RECORDS:
    raise SystemExit(f"kept CVE records below repair floor: {stats.get('kept_cve_records')}")

sizes = []
counts = []
decoded: dict[str, tuple[int, ...]] = {}
for row in rows:
    sid = row["series_id"]
    code, element_size = EXPECTED_SERIES[sid]
    if row["dataset_id"] != DATASET_ID or row.get("role") != "primary":
        raise SystemExit(f"unexpected dataset/role row: {row}")
    if row["numeric_kind"] != "uint" or int(row["element_size_bytes"]) != element_size:
        raise SystemExit(f"unexpected numeric row: {row}")
    if row.get("sample_geometry") != "sequence" or int(row.get("sample_rank", 0)) != 1:
        raise SystemExit(f"unexpected sample geometry: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    expected_size = int(row["sample_size_bytes"])
    expected_count = int(row["value_count"])
    if path.stat().st_size != expected_size or expected_size != expected_count * element_size:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    values = struct.unpack("<" + code * expected_count, path.read_bytes())
    if len(set(values)) <= 1:
        raise SystemExit(f"constant primary series rejected: {sid}")
    if expected_count != int(stats["kept_cve_records"]):
        raise SystemExit(f"series/count mismatch for {sid}: {expected_count} vs {stats['kept_cve_records']}")
    decoded[sid] = values
    sizes.append(expected_size)
    counts.append(expected_count)

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

published = decoded["nvd_published_at"]
if any(a > b for a, b in zip(published, published[1:])):
    raise SystemExit("published timestamps are not sorted")
start_2024 = calendar.timegm(datetime(2024, 1, 1).utctimetuple())
start_2025 = calendar.timegm(datetime(2025, 1, 1).utctimetuple())
if min(published) < start_2024 or max(published) >= start_2025:
    raise SystemExit("published timestamps fall outside 2024")
if max(decoded["nvd_cvss_base_score_x10"]) > 100:
    raise SystemExit("CVSS scaled score exceeds 100")

print(
    f"verified_samples={len(rows)} kept_cves={stats['kept_cve_records']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} source_bytes={stats.get('source_bytes', 0)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
