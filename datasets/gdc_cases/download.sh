#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gdc_cases"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# All GDC cases, projected to a few clinical numeric fields + the primary_site / project
# partition keys. JSON keeps the nested diagnoses[]/demographic{} structure unambiguous.
API="https://api.gdc.cancer.gov/cases"
SIZE="${GDC_PAGE_SIZE:-2000}"
FIELDS="${GDC_FIELDS:-case_id,primary_site,project.project_id,diagnoses.age_at_diagnosis,diagnoses.days_to_last_follow_up,diagnoses.year_of_diagnosis,demographic.year_of_birth,demographic.days_to_death}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

fetch_page() {  # from -> outfile ; echoes "<hits_on_page> <total>"
  local frm="$1" out="$2"
  curl --globoff -fsSL --retry 4 --retry-delay 3 --max-time 180 \
    -A "$UA" -H "Accept: application/json" -G \
    --data-urlencode "format=JSON" \
    --data-urlencode "fields=$FIELDS" \
    --data-urlencode "sort=case_id:asc" \
    --data-urlencode "size=$SIZE" \
    --data-urlencode "from=$frm" \
    -o "$out" "$API"
  python3 - "$out" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    hits = d["data"]["hits"]
    total = d["data"]["pagination"]["total"]
except Exception as e:
    print(f"PARSE_ERROR {e}", file=sys.stderr); sys.exit(3)
print(f"{len(hits)} {int(total)}")
PY
}

# ---- fail-fast page-0 guard ----------------------------------------------------------
FIRST="$PAGES_DIR/page_0000000.json"
if [ ! -s "$FIRST" ]; then
  echo "probe page from=0"
  if ! read -r hits total < <(fetch_page 0 "$FIRST"); then
    echo "FATAL: first GDC request failed (network or field projection)."
    rm -f "$FIRST"; exit 1
  fi
  if [ "${total:-0}" -le 0 ] || [ "${hits:-0}" -le 0 ]; then
    echo "FATAL: GDC returned total=$total hits=$hits on first page."
    rm -f "$FIRST"; exit 1
  fi
  echo "page from=0 hits=$hits total=$total"
fi

# learn total from the first page
read -r _h TOTAL < <(python3 - "$FIRST" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(d["data"]["hits"]), int(d["data"]["pagination"]["total"]))
PY
)

# ---- crawl remaining pages -----------------------------------------------------------
pages_fetched=0
frm="$SIZE"
while [ "$frm" -lt "$TOTAL" ]; do
  out="$(printf '%s/page_%07d.json' "$PAGES_DIR" "$frm")"
  if [ -s "$out" ]; then
    frm=$((frm + SIZE)); continue
  fi
  if ! read -r hits total < <(fetch_page "$frm" "$out"); then
    echo "WARN: fetch failed from=$frm (stopping)"; rm -f "$out"; break
  fi
  pages_fetched=$((pages_fetched + 1))
  [ "$hits" -le 0 ] && { rm -f "$out"; break; }
  frm=$((frm + SIZE))
  sleep 0.2
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name 'page_*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID total=$TOTAL pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 1
