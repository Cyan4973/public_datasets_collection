#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_sources_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# MAX_RECORDS caps the pull; default is effectively "the whole index" (loop stops when the cursor ends).
MAX_RECORDS="${OPENALEX_MAX_RECORDS:-10000000}"
MIN_RECORDS="${OPENALEX_MIN_RECORDS:-150000}"
PAGE_SIZE="${OPENALEX_PAGE_SIZE:-200}"
REQUEST_DELAY="${OPENALEX_REQUEST_DELAY_SECONDS:-0.12}"
BASE_URL="https://api.openalex.org/sources"

if [ "$PAGE_SIZE" -lt 1 ] || [ "$PAGE_SIZE" -gt 200 ]; then
  echo "OPENALEX_PAGE_SIZE must be between 1 and 200" >&2
  exit 2
fi

echo "[$(date -Is)] download_start dataset=$DATASET_ID max_records=$MAX_RECORDS min_records=$MIN_RECORDS page_size=$PAGE_SIZE"

cursor="*"
rows_downloaded=0
page=0
while [ "$rows_downloaded" -lt "$MAX_RECORDS" ]; do
  out="$PAGE_DIR/sources_page_$(printf '%04d' "$page").json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit page=$page path=$out"
  else
    rm -f "$tmp"
    CURL_ARGS=(
      -fL
      --get
      --retry 3
      --retry-delay 2
      -A "openzl-public-datasets/1.0"
      -o "$tmp"
      --data-urlencode "select=id,works_count,oa_works_count,cited_by_count,summary_stats,first_publication_year,last_publication_year,topics"
      --data-urlencode "per-page=$PAGE_SIZE"
      --data-urlencode "cursor=$cursor"
    )
    if [ -n "${OPENALEX_MAILTO:-}" ]; then
      CURL_ARGS+=(--data-urlencode "mailto=$OPENALEX_MAILTO")
    fi
    curl "${CURL_ARGS[@]}" "$BASE_URL"
    python3 - <<'PY' "$tmp" "$page"
import json
import sys

path, page = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
if "results" not in obj or not isinstance(obj["results"], list):
    raise SystemExit(f"bad OpenAlex payload at page={page}: missing results")
if "meta" not in obj or "next_cursor" not in obj["meta"]:
    raise SystemExit(f"bad OpenAlex payload at page={page}: missing next_cursor")
if not obj["results"]:
    raise SystemExit(f"empty OpenAlex page at page={page}")
PY
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  fi

  page_stats="$(python3 - <<'PY' "$out"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    obj = json.load(fh)
print(f"{len(obj['results'])}\t{obj['meta'].get('next_cursor') or ''}")
PY
)"
  IFS=$'\t' read -r page_rows cursor <<< "$page_stats"
  rows_downloaded=$(( rows_downloaded + page_rows ))
  echo "page_done page=$page rows=$page_rows rows_downloaded=$rows_downloaded"
  if [ -z "$cursor" ]; then
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
page_re = re.compile(r"sources_page_(\d+)\.json$")
pages = []
seen_ids = set()
duplicate_ids = 0
rows_total = 0
api_total = None
for path in sorted(page_dir.glob("sources_page_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    results = obj["results"]
    rows_total += len(results)
    api_total = int(obj["meta"].get("count", api_total or 0))
    for row in results:
        entity_id = row.get("id")
        if entity_id in seen_ids:
            duplicate_ids += 1
        elif entity_id:
            seen_ids.add(entity_id)
    pages.append({"path": path.name, "page": int(match.group(1)), "rows": len(results)})

if rows_total < min_records:
    raise SystemExit(f"downloaded only {rows_total} rows, minimum is {min_records}")
# A few cursor-boundary duplicates are harmless; the build de-duplicates by id.

stats = {
    "dataset_id": "openalex_sources_large",
    "api_total": api_total,
    "pages": pages,
    "rows_downloaded": rows_total,
    "min_records": min_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"downloaded_pages={len(pages)} rows_downloaded={rows_total} api_total={api_total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
