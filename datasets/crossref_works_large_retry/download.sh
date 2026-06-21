#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_works_large_retry"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# Single large column per field relies on selector sharding, so pull >1M works.
MAX_RECORDS="${CROSSREF_MAX_RECORDS:-1500000}"
MIN_RECORDS="${CROSSREF_MIN_RECORDS:-1000000}"
ROWS="${CROSSREF_ROWS:-1000}"
REQUEST_DELAY="${CROSSREF_REQUEST_DELAY_SECONDS:-0.15}"
FILTER="${CROSSREF_FILTER:-from-pub-date:2024-01-01,until-pub-date:2024-12-31}"
SELECT="DOI,references-count,is-referenced-by-count,created,deposited,indexed,link,license,member"
BASE_URL="https://api.crossref.org/works"

echo "[$(date -Is)] download_start dataset=$DATASET_ID max_records=$MAX_RECORDS min_records=$MIN_RECORDS rows=$ROWS filter=$FILTER"

cursor="*"
rows_downloaded=0
page=0
while [ "$rows_downloaded" -lt "$MAX_RECORDS" ]; do
  out="$PAGE_DIR/works_page_$(printf '%05d' "$page").json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit page=$page path=$out"
  else
    rm -f "$tmp"
    CURL_ARGS=(
      -fL
      --get
      --retry 4
      --retry-delay 3
      -A "openzl-public-datasets/1.0 (https://data.crossref.org; mailto:${CROSSREF_MAILTO:-noreply@example.com})"
      -o "$tmp"
      --data-urlencode "filter=$FILTER"
      --data-urlencode "select=$SELECT"
      --data-urlencode "rows=$ROWS"
      --data-urlencode "cursor=$cursor"
    )
    if [ -n "${CROSSREF_MAILTO:-}" ]; then
      CURL_ARGS+=(--data-urlencode "mailto=$CROSSREF_MAILTO")
    fi
    curl "${CURL_ARGS[@]}" "$BASE_URL"
    python3 - <<'PY' "$tmp" "$page"
import json
import sys

path, page = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
msg = obj.get("message", {})
if "items" not in msg or not isinstance(msg["items"], list):
    raise SystemExit(f"bad Crossref payload at page={page}: missing message.items")
if "next-cursor" not in msg:
    raise SystemExit(f"bad Crossref payload at page={page}: missing next-cursor")
PY
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  fi

  page_stats="$(python3 - <<'PY' "$out"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    msg = json.load(fh)["message"]
print(f"{len(msg['items'])}\t{msg.get('next-cursor') or ''}")
PY
)"
  IFS=$'\t' read -r page_rows cursor <<< "$page_stats"
  rows_downloaded=$(( rows_downloaded + page_rows ))
  echo "page_done page=$page rows=$page_rows rows_downloaded=$rows_downloaded"
  if [ "$page_rows" -eq 0 ] || [ -z "$cursor" ]; then
    break
  fi
  page=$(( page + 1 ))
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_RECORDS"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
page_re = re.compile(r"works_page_(\d+)\.json$")
pages = []
seen = set()
duplicate = 0
rows_total = 0
api_total = None
for path in sorted(page_dir.glob("works_page_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    with path.open(encoding="utf-8") as fh:
        msg = json.load(fh)["message"]
    items = msg["items"]
    rows_total += len(items)
    api_total = int(msg.get("total-results", api_total or 0))
    for item in items:
        doi = item.get("DOI")
        if doi in seen:
            duplicate += 1
        elif doi:
            seen.add(doi)
    pages.append({"path": path.name, "page": int(match.group(1)), "rows": len(items)})

unique = len(seen)
if rows_total < min_records:
    raise SystemExit(f"downloaded only {rows_total} rows, minimum is {min_records}")
# A few cursor-boundary duplicates are harmless; the build de-duplicates by DOI.

stats = {
    "dataset_id": "crossref_works_large_retry",
    "api_total": api_total,
    "pages": pages,
    "rows_downloaded": rows_total,
    "unique_ids": unique,
    "duplicate_ids": duplicate,
    "min_records": min_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"downloaded_pages={len(pages)} rows_downloaded={rows_total} unique={unique} api_total={api_total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
