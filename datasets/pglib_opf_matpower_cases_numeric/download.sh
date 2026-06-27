#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="pglib_opf_matpower_cases_numeric"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

REF="${PGLIB_OPF_REF:-master}"
ARCHIVE_URL="${PGLIB_OPF_ARCHIVE_URL:-https://github.com/power-grid-lib/pglib-opf/archive/refs/heads/${REF}.tar.gz}"
MAX_FILE_BYTES="${PGLIB_MAX_FILE_BYTES:-250000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
ARCHIVE="$DOWNLOAD_DIR/pglib-opf.tar.gz"

if [ -s "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  bytes="$(wc -c < "$ARCHIVE" | tr -d ' ')"
  echo "archive cache_hit bytes=$bytes path=$ARCHIVE"
else
  echo "fetch_archive url=$ARCHIVE_URL"
  curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    --speed-limit 1024 --speed-time 180 \
    -A "$UA" -o "$ARCHIVE.tmp" "$ARCHIVE_URL"
  mv "$ARCHIVE.tmp" "$ARCHIVE"
  bytes="$(wc -c < "$ARCHIVE" | tr -d ' ')"
  echo "archive downloaded bytes=$bytes"
fi

if [ "$bytes" -gt "$MAX_FILE_BYTES" ]; then
  echo "archive exceeds per-file cap: $bytes > $MAX_FILE_BYTES" >&2
  exit 1
fi

rm -rf "$EXTRACT_DIR/source.tmp" "$EXTRACT_DIR/source"
mkdir -p "$EXTRACT_DIR/source.tmp"
tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR/source.tmp"
mv "$EXTRACT_DIR/source.tmp" "$EXTRACT_DIR/source"

export DATASET_ID ARCHIVE ARCHIVE_URL EXTRACT_DIR DOWNLOAD_DIR MAX_FILE_BYTES
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

archive = Path(os.environ["ARCHIVE"])
extract_dir = Path(os.environ["EXTRACT_DIR"]) / "source"
download_dir = Path(os.environ["DOWNLOAD_DIR"])

case_files = sorted(extract_dir.rglob("pglib_opf_case*.m"))
if not case_files:
    raise SystemExit("archive validation failed: no pglib_opf_case*.m files found")

required = ("bus", "branch", "gen")
matrix_re = re.compile(r"\bmpc\.(bus|branch|gen|gencost)\s*=\s*\[")
valid_cases = []
field_counts = {field: 0 for field in ("bus", "branch", "gen", "gencost")}
for path in case_files:
    text = path.read_text(encoding="utf-8", errors="replace")
    fields = set(matrix_re.findall(text))
    if all(field in fields for field in required):
        valid_cases.append(path)
        for field in fields:
            field_counts[field] += 1

if len(valid_cases) < 5:
    raise SystemExit(f"archive validation failed: only {len(valid_cases)} valid MATPOWER cases")
if field_counts["branch"] < 5 or field_counts["bus"] < 5 or field_counts["gen"] < 5:
    raise SystemExit(f"archive validation failed: insufficient core matrix blocks {field_counts}")

digest = hashlib.sha256()
with archive.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        digest.update(chunk)

records = [
    {
        "case_file": str(path.relative_to(extract_dir)),
        "source_bytes": path.stat().st_size,
    }
    for path in valid_cases
]
inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "archive_url": os.environ["ARCHIVE_URL"],
    "archive_local_path": str(archive.relative_to(download_dir)),
    "archive_bytes": archive.stat().st_size,
    "archive_sha256": digest.hexdigest(),
    "valid_case_count": len(valid_cases),
    "matrix_field_counts": field_counts,
    "records": records,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "semantic_validation=ok "
    f"valid_cases={len(valid_cases)} "
    f"archive_bytes={archive.stat().st_size} "
    f"fields={field_counts}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
