#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_books_1gram_counts_2020_eng_u64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${GOOGLE_BOOKS_NGRAM_URL:-https://storage.googleapis.com/books/ngrams/books/20200217/eng/1-00000-of-00024.gz}"
TARGET="$DOWNLOAD_DIR/eng_1gram_20200217_00000_of_00024.gz"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${GOOGLE_BOOKS_NGRAM_MAX_FILE_BYTES:-800000000}"
HARD_MAX_FILE_BYTES=1000000000
MIN_OBSERVATIONS="${GOOGLE_BOOKS_NGRAM_MIN_OBSERVATIONS:-10000000}"

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

printf 'resource_id\turl\tfile\nbooks_1gram_eng_2020_shard_00000\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL MAX_FILE_BYTES MIN_OBSERVATIONS
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
min_observations = int(os.environ["MIN_OBSERVATIONS"])

if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:512].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not gzip data: {target}")
if target.read_bytes()[:2] != b"\x1f\x8b":
    raise SystemExit(f"download is not gzip data: {target}")

lines_seen = 0
observations_seen = 0
min_year = 9999
max_year = 0
with gzip.open(target, "rt", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            raise SystemExit(f"bad ngram row without observations near line {lines_seen + 1}")
        for obs in fields[1:]:
            parts = obs.split(",")
            if len(parts) != 3:
                raise SystemExit(f"bad observation near line {lines_seen + 1}: {obs!r}")
            year = int(parts[0])
            match_count = int(parts[1])
            volume_count = int(parts[2])
            if not (1400 <= year <= 2100):
                raise SystemExit(f"unexpected year near line {lines_seen + 1}: {year}")
            if match_count < 0 or volume_count < 0:
                raise SystemExit(f"negative count near line {lines_seen + 1}: {obs!r}")
            min_year = min(min_year, year)
            max_year = max(max_year, year)
            observations_seen += 1
        lines_seen += 1
        if observations_seen >= min_observations:
            break

if observations_seen < min_observations:
    raise SystemExit(
        f"too few Google Books observations: {observations_seen} < {min_observations}"
    )

inventory = {
    "dataset_id": "google_books_1gram_counts_2020_eng_u64",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "max_file_bytes": max_file_bytes,
    "validated_lines_at_least": lines_seen,
    "validated_observations_at_least": observations_seen,
    "min_year_seen": min_year,
    "max_year_seen": max_year,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok observations_at_least={observations_seen} "
    f"lines_at_least={lines_seen} archive_bytes={size} years=[{min_year},{max_year}]"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
