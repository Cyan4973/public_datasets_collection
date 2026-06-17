#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_submissions_largecap_bundle"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
export ISSUERS_FILE="${ISSUERS_FILE_OVERRIDE:-$REPO_ROOT/datasets/sec_submissions_largecap_bundle/issuers.tsv}"

python3 - <<'PY'
from __future__ import annotations
import csv
import json
import os
import statistics
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
issuers_file = Path(os.environ["ISSUERS_FILE"])

expected_series = {
    "sec_submission_form_code": 2,
    "sec_submission_size": 4,
    "sec_submission_acceptance_timestamp": 8,
    "sec_submission_xbrl_flag": 1,
    "sec_submission_inline_xbrl_flag": 1,
    "sec_submission_filing_date_ordinal": 4,
}

expected_issuers = []
with issuers_file.open(encoding="utf-8") as fh:
    reader = csv.DictReader(fh, delimiter="\t")
    for row in reader:
        expected_issuers.append(row["issuer"])

stats = {}
with (filter_dir / "issuer_stats.tsv").open(encoding="utf-8") as fh:
    r = csv.DictReader(fh, delimiter="\t")
    for row in r:
        stats[row["issuer"]] = int(row["kept_count"])

if sorted(stats) != sorted(expected_issuers):
    raise SystemExit(f"unexpected issuers in stats: {sorted(stats)}")

rows = []
with (index_dir / "samples.jsonl").open(encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            rows.append(json.loads(line))

if len(rows) != len(expected_series) * len(expected_issuers):
    raise SystemExit(f"unexpected index row count: {len(rows)}")

for row in rows:
    issuer = row["issuer"]
    series_id = row["series_id"]
    expected_size = stats[issuer] * expected_series[series_id]
    if int(row["sample_size_bytes"]) != expected_size:
        raise SystemExit(
            f"size mismatch for {issuer} {series_id}: {row['sample_size_bytes']} != {expected_size}"
        )
    if int(row["value_count"]) != stats[issuer]:
        raise SystemExit(
            f"value mismatch for {issuer} {series_id}: {row['value_count']} != {stats[issuer]}"
        )
    if not (data_root / row["sample_path"]).exists():
        raise SystemExit(f"missing sample file: {row['sample_path']}")
    if row.get("role") != "primary":
        raise SystemExit(f"missing primary role for {issuer} {series_id}")
    if row.get("sample_geometry") != "sec_submission_recent_table_column_by_issuer":
        raise SystemExit(f"bad sample geometry for {issuer} {series_id}")
    if row.get("sample_rank") != 1 or row.get("sample_shape") != [stats[issuer]]:
        raise SystemExit(f"bad sample shape for {issuer} {series_id}")
    if row.get("sample_axes") != ["filing"]:
        raise SystemExit(f"bad sample axes for {issuer} {series_id}")

codebook = filter_dir / "form_codebook.tsv"
if not codebook.exists() or codebook.stat().st_size == 0:
    raise SystemExit("missing form codebook")

value_counts = [int(row["value_count"]) for row in rows]
total_values = sum(value_counts)
total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
median_values = statistics.median(value_counts)
if total_values < 10_000:
    raise SystemExit(f"below value floor: {total_values}")
if total_bytes < 102_400:
    raise SystemExit(f"below byte floor: {total_bytes}")
if median_values < 1_000:
    raise SystemExit(f"below median sample floor: {median_values}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"above output cap: {total_bytes}")

print(
    f"verified issuers={len(expected_issuers)} rows={sum(stats.values())} "
    f"index_rows={len(rows)} total_values={total_values} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
