#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_water_sites_rdb"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
INVENTORY_DIR="$DOWNLOAD_DIR/site_inventory"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$INVENTORY_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
PLAN_FILE="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
CHECKSUM_FILE="$DOWNLOAD_DIR/collection_checksums.sha256"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

STATE_CODES="${USGS_WATER_SITES_STATE_CODES:-AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY}"
SITE_STATUS="${USGS_WATER_SITES_SITE_STATUS:-all}"
BASE_URL="${USGS_WATER_SITES_BASE_URL:-https://waterservices.usgs.gov/nwis/site/}"
MIN_SOURCE_RECORDS="${USGS_WATER_SITES_MIN_SOURCE_RECORDS:-25000}"
MIN_COMPLETE_RECORDS="${USGS_WATER_SITES_MIN_COMPLETE_RECORDS:-20000}"
UA="${USER_AGENT:-openzl-public-datasets/1.0 (numeric dataset collection)}"

: > "$FAIL_FILE"

if [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_SOURCE_RECORDS" "$MIN_COMPLETE_RECORDS"
import json
import sys

inventory = json.load(open(sys.argv[1], encoding="utf-8"))
source_records = int(inventory.get("source_records", 0))
if source_records < int(sys.argv[2]):
    raise SystemExit(1)
complete_records = int(inventory.get("complete_records", 0))
if complete_records < int(sys.argv[3]):
    raise SystemExit(1)
print(
    f"inventory cache_hit state_count={inventory.get('state_count')} "
    f"source_records={source_records} complete_records={complete_records}"
)
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

rm -rf "$INVENTORY_DIR.tmp"
mkdir -p "$INVENTORY_DIR.tmp"

export STATE_CODES SITE_STATUS BASE_URL PLAN_FILE
python3 - <<'PY'
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode

state_codes = [code.strip().lower() for code in os.environ["STATE_CODES"].split() if code.strip()]
if not state_codes:
    raise SystemExit("USGS_WATER_SITES_STATE_CODES is empty")
site_status = os.environ["SITE_STATUS"]

base_url = os.environ["BASE_URL"]
plan_file = Path(os.environ["PLAN_FILE"])
with plan_file.open("w", encoding="utf-8", newline="") as handle:
    for state_code in state_codes:
        params = {
            "format": "rdb",
            "siteOutput": "expanded",
            "siteType": "ST",
            "siteStatus": site_status,
            "stateCd": state_code,
        }
        sep = "&" if "?" in base_url else "?"
        url = base_url + sep + urlencode(params)
        handle.write(f"{state_code}\t{url}\tsite_inventory_{state_code}.txt\n")
PY

validate_payload() {
  local path="$1"
  python3 - <<'PY' "$path"
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
header = None
row_count = 0
with path.open("r", encoding="utf-8", errors="replace") as handle:
    for line in handle:
        if line.startswith("#") or not line.strip():
            continue
        columns = line.rstrip("\n").split("\t")
        if header is None:
            header = columns
            missing = {
                "site_no",
                "site_tp_cd",
                "dec_lat_va",
                "dec_long_va",
                "alt_va",
                "alt_acy_va",
                "huc_cd",
            }.difference(header)
            if missing:
                raise SystemExit(f"missing required columns in {path}: {sorted(missing)}")
            continue
        if columns and columns[0].endswith("s"):
            continue
        if len(columns) < len(header):
            columns += [""] * (len(header) - len(columns))
        idx = {name: header.index(name) for name in ("site_no", "site_tp_cd", "dec_lat_va", "dec_long_va", "huc_cd")}
        site_no = columns[idx["site_no"]].strip()
        if not site_no.isdigit():
            continue
        if not columns[idx["site_tp_cd"]].strip().startswith("ST"):
            continue
        # Require coordinates and hydrologic unit here. Altitude completeness is enforced by build.sh.
        if not columns[idx["dec_lat_va"]].strip() or not columns[idx["dec_long_va"]].strip():
            continue
        if not columns[idx["huc_cd"]].strip():
            continue
        row_count += 1
if header is None:
    raise SystemExit(f"missing RDB header in {path}")
print(f"validated path={path} usable_rows={row_count}")
PY
}

fetch_state() {
  local url="$1"
  local out="$2"
  local tmp="$out.tmp"
  rm -f "$tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if validate_payload "$out"; then
      return 2
    fi
    rm -f "$out"
  fi
  if command -v curl >/dev/null 2>&1; then
    curl --globoff -fL --retry 3 --retry-delay 3 -A "$UA" -o "$tmp" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="$UA" -O "$tmp" "$url"
  else
    echo "error: need curl or wget" >&2
    exit 1
  fi
  validate_payload "$tmp"
  mv "$tmp" "$out"
  return 0
}

success=0
cached=0
failed=0
while IFS='	' read -r state_code url rel_out; do
  [ -n "$state_code" ] || continue
  out="$INVENTORY_DIR.tmp/$rel_out"
  cached_out="$INVENTORY_DIR/$rel_out"
  if [ -s "$cached_out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    cp "$cached_out" "$out"
  fi
  echo "fetch_state state=$state_code url=$url"
  if fetch_state "$url" "$out"; then
    success=$((success + 1))
    echo "ok_state state=$state_code path=$out"
  else
    status=$?
    if [ "$status" -eq 2 ]; then
      cached=$((cached + 1))
      echo "cached_state state=$state_code path=$out"
    else
      failed=$((failed + 1))
      rm -f "$out" "$out.tmp"
      printf '%s\tcurl_failed\t%s\n' "$state_code" "$url" >> "$FAIL_FILE"
      echo "failed_state state=$state_code"
    fi
  fi
done < "$PLAN_FILE"

if [ "$failed" -gt 0 ]; then
  echo "state fetch completed with failures=$failed"
  exit 1
fi

export INVENTORY_DIR_TMP="$INVENTORY_DIR.tmp" DATASET_ID MIN_SOURCE_RECORDS MIN_COMPLETE_RECORDS INVENTORY
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
from pathlib import Path

inventory_dir = Path(os.environ["INVENTORY_DIR_TMP"])
min_source_records = int(os.environ["MIN_SOURCE_RECORDS"])
min_complete_records = int(os.environ["MIN_COMPLETE_RECORDS"])
inventory_path = Path(os.environ["INVENTORY"])

required = ["agency_cd", "site_no", "site_tp_cd", "dec_lat_va", "dec_long_va", "alt_va", "alt_acy_va", "huc_cd"]
states = []
source_records = 0
complete_records = 0
source_bytes = 0
seen_sites = set()
for path in sorted(inventory_dir.glob("site_inventory_*.txt")):
    state_code = path.stem.rsplit("_", 1)[-1].upper()
    header = None
    rows = 0
    complete = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            columns = line.rstrip("\n").split("\t")
            if header is None:
                header = columns
                indexes = {name: header.index(name) for name in required}
                continue
            if columns and columns[0].endswith("s"):
                continue
            if len(columns) < len(header):
                columns += [""] * (len(header) - len(columns))
            if not columns[indexes["site_no"]].strip().isdigit():
                continue
            if not columns[indexes["site_tp_cd"]].strip().startswith("ST"):
                continue
            rows += 1
            site_key = (columns[indexes["agency_cd"]].strip(), columns[indexes["site_no"]].strip())
            if site_key in seen_sites:
                continue
            seen_sites.add(site_key)
            try:
                dec_lat = float(columns[indexes["dec_lat_va"]].strip())
                dec_long = float(columns[indexes["dec_long_va"]].strip())
                altitude = float(columns[indexes["alt_va"]].strip())
                alt_accuracy = float(columns[indexes["alt_acy_va"]].strip())
                int(columns[indexes["huc_cd"]].strip())
            except Exception:
                continue
            if not (math.isfinite(dec_lat) and -90.0 <= dec_lat <= 90.0):
                continue
            if not (math.isfinite(dec_long) and -180.0 <= dec_long <= 180.0):
                continue
            if not (math.isfinite(altitude) and -1000.0 <= altitude <= 20000.0):
                continue
            if not (math.isfinite(alt_accuracy) and 0.0 <= alt_accuracy <= 20000.0):
                continue
            complete += 1
    source_records += rows
    complete_records += complete
    source_bytes += path.stat().st_size
    states.append(
        {
            "state_code": state_code,
            "record_count": rows,
            "complete_record_count": complete,
            "bytes": path.stat().st_size,
        }
    )

if source_records < min_source_records:
    raise SystemExit(
        f"only {source_records} source records < USGS_WATER_SITES_MIN_SOURCE_RECORDS={min_source_records}"
    )
if complete_records < min_complete_records:
    raise SystemExit(
        f"only {complete_records} complete records < USGS_WATER_SITES_MIN_COMPLETE_RECORDS={min_complete_records}"
    )

inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "site_status": os.environ.get("SITE_STATUS", "all"),
    "state_count": len(states),
    "source_records": source_records,
    "complete_records": complete_records,
    "source_bytes": source_bytes,
    "states": states,
}
inventory_path.parent.mkdir(parents=True, exist_ok=True)
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"semantic_validation=ok states={len(states)} source_records={source_records} "
    f"complete_records={complete_records} source_bytes={source_bytes}"
)
PY

rm -rf "$INVENTORY_DIR"
mv "$INVENTORY_DIR.tmp" "$INVENTORY_DIR"
find "$INVENTORY_DIR" -maxdepth 1 -type f -name 'site_inventory_*.txt' -print0 | sort -z | xargs -0 sha256sum > "$CHECKSUM_FILE"

echo "success=$success"
echo "cached=$cached"
echo "failed=$failed"
echo "inventory=$INVENTORY"
echo "checksums=$CHECKSUM_FILE"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
