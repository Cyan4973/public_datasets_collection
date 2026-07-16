#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usda_fia_ca_tree_measurements_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${USDA_FIA_CA_TREE_URL:-https://apps.fs.usda.gov/fia/datamart/CSV/CA_TREE.zip}"
TARGET="$DOWNLOAD_DIR/CA_TREE.zip"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MIN_ROWS="${USDA_FIA_CA_TREE_MIN_ROWS:-100000}"
MAX_FILE_BYTES="${USDA_FIA_CA_TREE_MAX_FILE_BYTES:-250000000}"
HARD_MAX_FILE_BYTES=1000000000

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

printf 'resource_id\turl\tfile\nca_tree_zip\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL MIN_ROWS MAX_FILE_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from pathlib import Path

REQUIRED_FIELDS = {"DIA", "HT", "TPA_UNADJ"}

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size}")
head = target.read_bytes()[:256].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not ZIP: {target}")

with zipfile.ZipFile(target) as zf:
    members = [
        name for name in zf.namelist()
        if name.lower().endswith("_tree.csv") or name.lower().endswith("tree.csv")
    ]
    if len(members) != 1:
        raise SystemExit(f"expected exactly one TREE CSV member, found {members}")
    member = members[0]
    info = zf.getinfo(member)
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(text)
        try:
            header = [field.strip().upper() for field in next(reader)]
        except StopIteration:
            raise SystemExit(f"empty CSV member: {member}") from None
        missing = sorted(REQUIRED_FIELDS - set(header))
        if missing:
            raise SystemExit(f"missing required TREE fields: {missing}")
        rows = 0
        bad_width = 0
        width = len(header)
        for record in reader:
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != width:
                bad_width += 1
                continue
            rows += 1

if rows < min_rows:
    raise SystemExit(f"too few TREE rows: {rows} < {min_rows}")
if bad_width:
    raise SystemExit(f"bad row width count: {bad_width}")

inventory = {
    "dataset_id": "usda_fia_ca_tree_measurements_f32",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "tree_member": member,
    "tree_rows": rows,
    "tree_columns": len(header),
    "tree_uncompressed_bytes": info.file_size,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok rows={rows} columns={len(header)} "
    f"archive_bytes={size} tree_bytes={info.file_size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
