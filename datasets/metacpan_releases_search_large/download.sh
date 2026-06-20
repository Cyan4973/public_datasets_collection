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

# MetaCPAN runs Elasticsearch; from+size must stay within the result window (10000).
TARGET_RECORDS="${METACPAN_TARGET_RECORDS:-9000}"
PAGE_SIZE="${METACPAN_PAGE_SIZE:-1000}"
REQUEST_DELAY="${METACPAN_REQUEST_DELAY_SECONDS:-0.3}"
RESULT_WINDOW=10000
URL="https://fastapi.metacpan.org/v1/release/_search"

echo "[$(date -Is)] download_start dataset=$DATASET_ID target_records=$TARGET_RECORDS page_size=$PAGE_SIZE"

from=0
page=0
rows_downloaded=0
while [ "$rows_downloaded" -lt "$TARGET_RECORDS" ]; do
  if [ $(( from + PAGE_SIZE )) -gt "$RESULT_WINDOW" ]; then
    echo "result_window_reached from=$from page_size=$PAGE_SIZE window=$RESULT_WINDOW"
    break
  fi
  out="$PAGE_DIR/release_page_$(printf '%04d' "$page").json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit page=$page path=$out"
  else
    rm -f "$tmp"
    body="{\"size\":${PAGE_SIZE},\"from\":${from},\"query\":{\"match_all\":{}},\"sort\":[{\"date\":\"desc\"}]}"
    curl --globoff -fL --retry 3 --retry-delay 2 \
      -A "openzl-public-datasets/1.0" \
      -H "Content-Type: application/json" \
      --data "$body" \
      -o "$tmp" "$URL"
    python3 - <<'PY' "$tmp" "$page"
import json
import sys

path, page = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
hits = obj.get("hits", {}).get("hits")
if not isinstance(hits, list):
    raise SystemExit(f"bad MetaCPAN payload at page={page}: missing hits.hits")
if not hits:
    raise SystemExit(f"empty MetaCPAN page at page={page}")
PY
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  fi

  page_rows="$(python3 - <<'PY' "$out"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    obj = json.load(fh)
print(len(obj["hits"]["hits"]))
PY
)"
  rows_downloaded=$(( rows_downloaded + page_rows ))
  echo "page_done page=$page rows=$page_rows rows_downloaded=$rows_downloaded"
  if [ "$page_rows" -lt "$PAGE_SIZE" ]; then
    echo "short_page reached end of index"
    break
  fi
  from=$(( from + PAGE_SIZE ))
  page=$(( page + 1 ))
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$TARGET_RECORDS"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
target_records = int(sys.argv[3])
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
if rows_total < target_records:
    raise SystemExit(f"downloaded only {rows_total} rows, target is {target_records}")

stats = {
    "dataset_id": "metacpan_releases_search_large",
    "pages": pages,
    "rows_downloaded": rows_total,
    "unique_ids": unique_ids,
    "duplicate_ids": duplicate_ids,
    "target_records": target_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"downloaded_pages={len(pages)} rows_downloaded={rows_total} unique_ids={unique_ids} duplicate_ids={duplicate_ids}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
