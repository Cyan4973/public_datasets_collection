#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_stormevents_details_2024_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${NOAA_STORMEVENTS_BASE_URL:-https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${NOAA_STORMEVENTS_MAX_FILE_BYTES:-200000000}"
MIN_ROWS="${NOAA_STORMEVENTS_MIN_ROWS:-50000}"

URLS_FILE="$DOWNLOAD_DIR/candidate_urls.txt"
LISTING="$DOWNLOAD_DIR/noaa_stormevents_csvfiles_listing.html"
rm -f "$URLS_FILE"

if [[ -n "${NOAA_STORMEVENTS_DETAILS_URL:-}" ]]; then
  printf '%s\n' "$NOAA_STORMEVENTS_DETAILS_URL" > "$URLS_FILE"
else
  echo "discover latest d2024 details file from $BASE_URL"
  if curl --globoff -fsSL --retry 2 --retry-delay 5 \
    -A "openzl-public-datasets/1.0 (noaa-stormevents-f64)" \
    -o "$LISTING.tmp" "$BASE_URL"; then
    mv "$LISTING.tmp" "$LISTING"
    python3 - "$BASE_URL" "$LISTING" "$URLS_FILE" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin

base_url = sys.argv[1]
listing = Path(sys.argv[2])
out = Path(sys.argv[3])
text = listing.read_text(encoding="utf-8", errors="replace")
names = sorted(
    set(re.findall(r"StormEvents_details-ftp_v1\.0_d2024_c\d{8}\.csv\.gz", text)),
    reverse=True,
)
if names:
    out.write_text("".join(urljoin(base_url, name) + "\n" for name in names), encoding="utf-8")
PY
  else
    rm -f "$LISTING.tmp"
    echo "listing discovery failed; will try fallback correction dates"
  fi
fi

if [[ ! -s "$URLS_FILE" ]]; then
  cat > "$URLS_FILE" <<EOF
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250716.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250618.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250520.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250418.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250318.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250220.csv.gz
${BASE_URL}StormEvents_details-ftp_v1.0_d2024_c20250117.csv.gz
EOF
fi

TARGET=""
URL=""
while IFS= read -r candidate_url; do
  [[ -n "$candidate_url" ]] || continue
  candidate_file="$(basename "$candidate_url")"
  candidate_target="$DOWNLOAD_DIR/$candidate_file"
  if [[ -s "$candidate_target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit url=$candidate_url path=$candidate_target bytes=$(wc -c < "$candidate_target" | tr -d ' ')"
    TARGET="$candidate_target"
    URL="$candidate_url"
    break
  fi
  echo "fetch url=$candidate_url"
  rm -f "$candidate_target.tmp"
  if curl --globoff -fL --retry 2 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (noaa-stormevents-f64)" \
    -o "$candidate_target.tmp" "$candidate_url"; then
    mv "$candidate_target.tmp" "$candidate_target"
    TARGET="$candidate_target"
    URL="$candidate_url"
    break
  fi
  rm -f "$candidate_target.tmp"
done < "$URLS_FILE"

if [[ -z "$TARGET" || -z "$URL" ]]; then
  echo "ERROR: no NOAA StormEvents d2024 details gzip could be downloaded." >&2
  echo "Tried URLs from $URLS_FILE" >&2
  echo "Override with NOAA_STORMEVENTS_DETAILS_URL=https://.../StormEvents_details-ftp_v1.0_d2024_cYYYYMMDD.csv.gz" >&2
  exit 1
fi

printf 'resource_id\turl\tfile\nstormevents_details_2024\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

export TARGET URL DOWNLOAD_DIR MIN_ROWS MAX_FILE_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
required = {
    "BEGIN_LAT",
    "BEGIN_LON",
    "END_LAT",
    "END_LON",
    "MAGNITUDE",
    "INJURIES_DIRECT",
    "INJURIES_INDIRECT",
    "DEATHS_DIRECT",
    "DEATHS_INDIRECT",
    "DAMAGE_PROPERTY",
    "DAMAGE_CROPS",
}

if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:512].lstrip().lower()
if head.startswith(b"<") or b"<html" in head or b"access denied" in head:
    raise SystemExit(f"download looks like HTML/error payload, not gzip CSV: {target}")

rows = 0
header: list[str] | None = None
try:
    with gzip.open(target, "rt", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise SystemExit("missing CSV header")
        missing = sorted(required - {name.strip() for name in header})
        if missing:
            raise SystemExit(f"missing required columns: {missing}")
        for row in reader:
            if row:
                rows += 1
except OSError as exc:
    raise SystemExit(f"malformed gzip: {exc}") from exc

if rows < min_rows:
    raise SystemExit(f"too few detail rows: {rows} < {min_rows}")

inventory = {
    "dataset_id": "noaa_stormevents_details_2024_f64",
    "url": os.environ["URL"],
    "file": target.name,
    "source_bytes": size,
    "rows": rows,
    "columns": header,
    "required_columns": sorted(required),
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok rows={rows} source_bytes={size} columns={len(header)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
