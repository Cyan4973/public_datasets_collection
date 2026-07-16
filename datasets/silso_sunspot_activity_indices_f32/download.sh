#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="silso_sunspot_activity_indices_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

DAILY_URL="${SILSO_DAILY_TOTAL_URL:-https://www.sidc.be/SILSO/DATA/SN_d_tot_V2.0.csv}"
MONTHLY_URL="${SILSO_MONTHLY_TOTAL_URL:-https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv}"
DAILY_FILE="$DOWNLOAD_DIR/SN_d_tot_V2.0.csv"
MONTHLY_FILE="$DOWNLOAD_DIR/SN_m_tot_V2.0.csv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${SILSO_MAX_FILE_BYTES:-20000000}"
MIN_DAILY_ROWS="${SILSO_MIN_DAILY_ROWS:-70000}"
MIN_MONTHLY_ROWS="${SILSO_MIN_MONTHLY_ROWS:-3000}"

{
  printf 'resource_id\turl\tfile\n'
  printf 'daily_total\t%s\t%s\n' "$DAILY_URL" "$(basename "$DAILY_FILE")"
  printf 'monthly_total\t%s\t%s\n' "$MONTHLY_URL" "$(basename "$MONTHLY_FILE")"
} > "$PLAN"

fetch_one() {
  local url="$1"
  local target="$2"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit path=$target"
  else
    echo "fetch url=$url"
    curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
      -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
  fi
}

fetch_one "$DAILY_URL" "$DAILY_FILE"
fetch_one "$MONTHLY_URL" "$MONTHLY_FILE"

export DOWNLOAD_DIR DAILY_FILE MONTHLY_FILE DAILY_URL MONTHLY_URL
export MAX_FILE_BYTES MIN_DAILY_ROWS MIN_MONTHLY_ROWS
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path


def validate_csv(path: Path, expected_width: int, min_rows: int, value_columns: list[int]) -> dict[str, int]:
    if not path.is_file():
        raise SystemExit(f"missing download: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise SystemExit(f"empty download: {path}")
    if size > int(os.environ["MAX_FILE_BYTES"]):
        raise SystemExit(f"download exceeds cap: {path} bytes={size}")
    head = path.read_bytes()[:256].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head:
        raise SystemExit(f"download looks like HTML, not CSV: {path}")

    rows = 0
    bad_width = 0
    valid_by_column = {index: 0 for index in value_columns}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        for record in reader:
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != expected_width:
                bad_width += 1
                continue
            rows += 1
            for index in value_columns:
                try:
                    value = float(record[index].strip())
                except ValueError:
                    continue
                if value >= 0:
                    valid_by_column[index] += 1
    if rows < min_rows:
        raise SystemExit(f"too few rows in {path.name}: {rows} < {min_rows}")
    if bad_width:
        raise SystemExit(f"bad row width count in {path.name}: {bad_width}")
    for index, valid in valid_by_column.items():
        if valid < min_rows // 2:
            raise SystemExit(f"too few nonnegative numeric values in {path.name} column={index}: {valid}")
    return {"rows": rows, "bytes": size, **{f"valid_column_{k}": v for k, v in valid_by_column.items()}}


download_dir = Path(os.environ["DOWNLOAD_DIR"])
daily = validate_csv(Path(os.environ["DAILY_FILE"]), 8, int(os.environ["MIN_DAILY_ROWS"]), [4, 5, 6])
monthly = validate_csv(Path(os.environ["MONTHLY_FILE"]), 7, int(os.environ["MIN_MONTHLY_ROWS"]), [3, 4, 5])
inventory = {
    "dataset_id": "silso_sunspot_activity_indices_f32",
    "resources": [
        {
            "resource_id": "daily_total",
            "url": os.environ["DAILY_URL"],
            "file": Path(os.environ["DAILY_FILE"]).name,
            "rows": daily["rows"],
            "bytes": daily["bytes"],
        },
        {
            "resource_id": "monthly_total",
            "url": os.environ["MONTHLY_URL"],
            "file": Path(os.environ["MONTHLY_FILE"]).name,
            "rows": monthly["rows"],
            "bytes": monthly["bytes"],
        },
    ],
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "semantic_validation=ok "
    f"daily_rows={daily['rows']} monthly_rows={monthly['rows']} "
    f"daily_bytes={daily['bytes']} monthly_bytes={monthly['bytes']}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
