#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nhtsa_fars_2022_crash_tables_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${NHTSA_FARS_2022_URL:-https://static.nhtsa.gov/nhtsa/downloads/FARS/2022/National/FARS2022NationalCSV.zip}"
TARGET="$DOWNLOAD_DIR/FARS2022NationalCSV.zip"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${NHTSA_FARS_MAX_FILE_BYTES:-250000000}"
HARD_MAX_FILE_BYTES=1000000000
MIN_ACCIDENT_ROWS="${NHTSA_FARS_MIN_ACCIDENT_ROWS:-30000}"
MIN_PERSON_ROWS="${NHTSA_FARS_MIN_PERSON_ROWS:-50000}"
MIN_VEHICLE_ROWS="${NHTSA_FARS_MIN_VEHICLE_ROWS:-40000}"

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

printf 'resource_id\turl\tfile\nfars2022_zip\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL MAX_FILE_BYTES
export MIN_ACCIDENT_ROWS MIN_PERSON_ROWS MIN_VEHICLE_ROWS
python3 - <<'PY'
from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from pathlib import Path

TABLES = {
    "ACCIDENT": int(os.environ["MIN_ACCIDENT_ROWS"]),
    "PERSON": int(os.environ["MIN_PERSON_ROWS"]),
    "VEHICLE": int(os.environ["MIN_VEHICLE_ROWS"]),
}

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:256].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not ZIP: {target}")

resources = []
with zipfile.ZipFile(target) as zf:
    by_table = {}
    for name in zf.namelist():
        base = Path(name).name.upper()
        stem = base.rsplit(".", 1)[0]
        if base.endswith(".CSV") and stem in TABLES:
            by_table[stem] = name
    missing = sorted(set(TABLES) - set(by_table))
    if missing:
        raise SystemExit(f"missing FARS CSV members: {missing}")

    for table, min_rows in TABLES.items():
        member = by_table[table]
        info = zf.getinfo(member)
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.reader(text)
            try:
                header = next(reader)
            except StopIteration:
                raise SystemExit(f"empty CSV member: {member}") from None
            width = len(header)
            rows = 0
            bad_width = 0
            for record in reader:
                if not record or all(not cell.strip() for cell in record):
                    continue
                if len(record) != width:
                    bad_width += 1
                    continue
                rows += 1
        if rows < min_rows:
            raise SystemExit(f"too few {table} rows: {rows} < {min_rows}")
        if bad_width:
            raise SystemExit(f"{table} bad row width count: {bad_width}")
        resources.append({
            "table": table,
            "member": member,
            "rows": rows,
            "columns": width,
            "uncompressed_bytes": info.file_size,
        })

inventory = {
    "dataset_id": "nhtsa_fars_2022_crash_tables_f64",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "max_file_bytes": max_file_bytes,
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "semantic_validation=ok "
    + " ".join(f"{item['table'].lower()}_rows={item['rows']}" for item in resources)
    + f" archive_bytes={size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
