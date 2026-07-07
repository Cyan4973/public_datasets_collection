#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_author_topic_count_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MAX_RECORDS="${OPENALEX_TOPIC_COUNT_MAX_RECORDS:-5000000}"
MIN_RECORDS="${OPENALEX_TOPIC_COUNT_MIN_RECORDS:-2000000}"
PAGE_SIZE="${OPENALEX_TOPIC_COUNT_PAGE_SIZE:-200}"
REQUEST_DELAY="${OPENALEX_TOPIC_COUNT_REQUEST_DELAY_SECONDS:-0.12}"
MAX_429_SLEEP="${OPENALEX_TOPIC_COUNT_MAX_429_SLEEP_SECONDS:-300}"
MAX_429_RETRIES="${OPENALEX_TOPIC_COUNT_MAX_429_RETRIES:-3}"
STOP_ON_429_AFTER_MIN="${OPENALEX_TOPIC_COUNT_STOP_ON_429_AFTER_MIN:-1}"
BASE_URL="https://api.openalex.org/authors"
STATS_PATH="$DOWNLOAD_DIR/download_stats.json"
COMPLETION_REASON="target_reached"

if [ "$PAGE_SIZE" -lt 1 ] || [ "$PAGE_SIZE" -gt 200 ]; then
  echo "OPENALEX_TOPIC_COUNT_PAGE_SIZE must be between 1 and 200" >&2
  exit 2
fi

echo "[$(date -Is)] download_start dataset=$DATASET_ID max_records=$MAX_RECORDS min_records=$MIN_RECORDS page_size=$PAGE_SIZE"

fetch_page() {
  page=$1
  cursor_value=$2
  out=$3
  tmp=$4
  header_tmp="${tmp}.headers"
  attempt=0

  while :; do
    rm -f "$tmp" "$header_tmp"
    CURL_ARGS=(
      -L
      --get
      --connect-timeout 30
      --max-time 180
      -A "openzl-public-datasets/1.0"
      -D "$header_tmp"
      -w "%{http_code}"
      -o "$tmp"
      --data-urlencode "select=id,topics"
      --data-urlencode "per-page=$PAGE_SIZE"
      --data-urlencode "cursor=$cursor_value"
    )
    if [ -n "${OPENALEX_MAILTO:-}" ]; then
      CURL_ARGS+=(--data-urlencode "mailto=$OPENALEX_MAILTO")
    fi

    status="$(curl "${CURL_ARGS[@]}" "$BASE_URL")"
    if [ "$status" = "200" ]; then
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
      rm -f "$header_tmp"
      return 0
    fi

    if [ "$status" = "429" ]; then
      if [ "$STOP_ON_429_AFTER_MIN" = "1" ] && [ "$rows_downloaded" -ge "$MIN_RECORDS" ]; then
        echo "rate_limited_after_min page=$page rows_downloaded=$rows_downloaded min_records=$MIN_RECORDS"
        rm -f "$tmp" "$header_tmp"
        return 75
      fi
      attempt=$(( attempt + 1 ))
      if [ "$attempt" -gt "$MAX_429_RETRIES" ]; then
        echo "rate_limited_retry_exhausted page=$page attempts=$attempt rows_downloaded=$rows_downloaded"
        rm -f "$tmp" "$header_tmp"
        return 75
      fi
      retry_after="$(python3 - <<'PY' "$header_tmp" "$MAX_429_SLEEP"
from __future__ import annotations

import email.utils
import sys
import time
from pathlib import Path

headers = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
max_sleep = int(sys.argv[2])
retry_after = 60
for line in headers:
    if line.lower().startswith("retry-after:"):
        raw = line.split(":", 1)[1].strip()
        try:
            retry_after = int(raw)
        except ValueError:
            parsed = email.utils.parsedate_to_datetime(raw)
            retry_after = max(1, int(parsed.timestamp() - time.time()))
        break
print(max(1, min(retry_after, max_sleep)))
PY
)"
      echo "rate_limited_retry page=$page attempt=$attempt sleep_seconds=$retry_after rows_downloaded=$rows_downloaded"
      sleep "$retry_after"
      continue
    fi

    echo "fetch_failed page=$page http_status=$status" >&2
    rm -f "$tmp" "$header_tmp"
    return 1
  done
}

cursor="*"
rows_downloaded=0
page=0
while [ "$rows_downloaded" -lt "$MAX_RECORDS" ]; do
  out="$PAGE_DIR/topic_count_page_$(printf '%06d' "$page").json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit page=$page path=$out"
  else
    if fetch_page "$page" "$cursor" "$out" "$tmp"; then
      sleep "$REQUEST_DELAY"
    else
      fetch_status=$?
      if [ "$fetch_status" -eq 75 ] && [ "$rows_downloaded" -ge "$MIN_RECORDS" ]; then
        COMPLETION_REASON="rate_limited_after_min"
        break
      fi
      exit "$fetch_status"
    fi
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
if [ "$rows_downloaded" -lt "$MAX_RECORDS" ] && [ "$COMPLETION_REASON" = "target_reached" ]; then
  COMPLETION_REASON="cursor_exhausted"
fi

python3 - <<'PY' "$PAGE_DIR" "$STATS_PATH" "$MIN_RECORDS" "$MAX_RECORDS" "$COMPLETION_REASON"
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
max_records = int(sys.argv[4])
completion_reason = sys.argv[5]
page_re = re.compile(r"topic_count_page_(\d+)\.json$")
pages = []
seen_ids = set()
duplicate_ids = 0
rows_total = 0
api_total = None
for path in sorted(page_dir.glob("topic_count_page_*.json")):
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

stats = {
    "completion_reason": completion_reason,
    "dataset_id": "openalex_author_topic_count_u8",
    "api_total": api_total,
    "duplicate_ids": duplicate_ids,
    "max_records": max_records,
    "min_records": min_records,
    "pages": pages,
    "rows_downloaded": rows_total,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"downloaded_pages={len(pages)} rows_downloaded={rows_total} duplicate_ids={duplicate_ids} api_total={api_total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
