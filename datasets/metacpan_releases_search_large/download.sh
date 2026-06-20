#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="metacpan_releases_search_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# search_after over date asc walks the whole release index (bypasses the 10000 from/size window).
# _source filtering keeps each page small (only the fields we extract).
MAX_RECORDS="${METACPAN_MAX_RECORDS:-500000}"
MIN_RECORDS="${METACPAN_MIN_RECORDS:-100000}"
PAGE_SIZE="${METACPAN_PAGE_SIZE:-1000}"
REQUEST_DELAY="${METACPAN_REQUEST_DELAY_SECONDS:-0.3}"
URL="https://fastapi.metacpan.org/v1/release/_search"
SOURCE_FIELDS='["version_numified","stat","tests","dependency","provides"]'

# The pagination scheme changed; start from a clean page set for a consistent walk.
rm -f "$PAGE_DIR"/release_page_*.json "$DOWNLOAD_DIR/download_stats.json"

echo "[$(date -Is)] download_start dataset=$DATASET_ID max_records=$MAX_RECORDS min_records=$MIN_RECORDS page_size=$PAGE_SIZE"

search_after=""
page=0
rows_downloaded=0
while [ "$rows_downloaded" -lt "$MAX_RECORDS" ]; do
  out="$PAGE_DIR/release_page_$(printf '%04d' "$page").json"
  tmp="$out.tmp"
  rm -f "$tmp"
  if [ -z "$search_after" ]; then
    body="{\"size\":${PAGE_SIZE},\"_source\":${SOURCE_FIELDS},\"query\":{\"match_all\":{}},\"sort\":[{\"date\":\"asc\"}]}"
  else
    body="{\"size\":${PAGE_SIZE},\"_source\":${SOURCE_FIELDS},\"query\":{\"match_all\":{}},\"sort\":[{\"date\":\"asc\"}],\"search_after\":[${search_after}]}"
  fi
  curl --globoff -fL --retry 3 --retry-delay 2 \
    -A "openzl-public-datasets/1.0" \
    -H "Content-Type: application/json" \
    --data "$body" \
    -o "$tmp" "$URL"

  page_info="$(python3 - <<'PY' "$tmp" "$page"
import json
import sys

path, page = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
hits = obj.get("hits", {}).get("hits")
if not isinstance(hits, list):
    raise SystemExit(f"bad MetaCPAN payload at page={page}: missing hits.hits")
if not hits:
    print("0\t")
else:
    last_sort = hits[-1].get("sort")
    if not last_sort:
        raise SystemExit(f"MetaCPAN page={page} hits lack a sort value for search_after")
    print(f"{len(hits)}\t{last_sort[0]}")
PY
)"
  IFS=$'\t' read -r page_rows next_after <<< "$page_info"

  if [ "$page_rows" -eq 0 ]; then
    rm -f "$tmp"
    echo "end_of_index page=$page"
    break
  fi
  mv "$tmp" "$out"
  rows_downloaded=$(( rows_downloaded + page_rows ))
  search_after="$next_after"
  echo "page_done page=$page rows=$page_rows rows_downloaded=$rows_downloaded"
  if [ "$page_rows" -lt "$PAGE_SIZE" ]; then
    echo "short_page reached end of index"
    break
  fi
  page=$(( page + 1 ))
  sleep "$REQUEST_DELAY"
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_RECORDS"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
page_re = re.compile(r"release_page_(\d+)\.json$")
pages = []
seen_ids = set()
duplicate_ids = 0
rows_total = 0
for path in sorted(page_dir.glob("release_page_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    hits = obj["hits"]["hits"]
    rows_total += len(hits)
    for row in hits:
        rid = row.get("_id")
        if rid in seen_ids:
            duplicate_ids += 1
        elif rid:
            seen_ids.add(rid)
    pages.append({"path": path.name, "page": int(match.group(1)), "rows": len(hits)})

unique_ids = len(seen_ids)
if unique_ids < min_records:
    raise SystemExit(f"downloaded only {unique_ids} unique rows, minimum is {min_records}")

stats = {
    "dataset_id": "metacpan_releases_search_large",
    "pages": pages,
    "rows_downloaded": rows_total,
    "unique_ids": unique_ids,
    "duplicate_ids": duplicate_ids,
    "min_records": min_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"downloaded_pages={len(pages)} rows_downloaded={rows_total} unique_ids={unique_ids} duplicate_ids={duplicate_ids}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
