#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="arxiv_cs_lg_2024q1_metadata"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'page\tstatus\tdetail\n' > "$FAILURES"
printf 'local_name\tstart\tmax_results\turl\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="https://export.arxiv.org/api/query"
SEARCH_QUERY="cat:cs.LG+AND+submittedDate:[202401010000+TO+202403312359]"
PAGE_SIZE="${ARXIV_PAGE_SIZE:-1000}"
MAX_PAGES="${ARXIV_MAX_PAGES:-50}"
DELAY_SECONDS="${ARXIV_DELAY_SECONDS:-3}"
completed=0

for ((page = 0; page < MAX_PAGES; page++)); do
  start=$((page * PAGE_SIZE))
  name="$(printf 'arxiv_cs_lg_2024q1_start_%06d.xml' "$start")"
  url="$BASE_URL?search_query=$SEARCH_QUERY&start=$start&max_results=$PAGE_SIZE&sortBy=submittedDate&sortOrder=ascending"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%d\t%d\t%s\n' "$name" "$start" "$PAGE_SIZE" "$url" >> "$PLAN"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run url=$url"
    continue
  fi
  if [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch page=$page start=$start url=$url"
    if ! curl --globoff --fail --location --show-error --retry 3 --retry-delay 10 -o "$target.tmp" "$url"; then
      printf '%s\tfailed\tcurl_failed\n' "$name" >> "$FAILURES"
      rm -f "$target.tmp"
      break
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit $target"
  fi
  entry_count="$(
    python3 - "$target" <<'PY'
import sys
import xml.etree.ElementTree as ET
path = sys.argv[1]
root = ET.parse(path).getroot()
entries = [elem for elem in root.iter() if elem.tag.endswith("entry")]
print(len(entries))
PY
  )"
  echo "validated_page=$name entries=$entry_count"
  if [[ "$entry_count" == "0" ]]; then
    rm -f "$target"
    completed=1
    break
  fi
  if (( entry_count < PAGE_SIZE )); then
    completed=1
    break
  fi
  sleep "$DELAY_SECONDS"
done

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
if [[ "${DRY_RUN:-0}" != "1" && "$completed" != "1" && "$failure_count" == "0" ]]; then
  printf 'max_pages\tfailed\tpossible_truncated_window\n' >> "$FAILURES"
  failure_count=1
  echo "reached ARXIV_MAX_PAGES=$MAX_PAGES without an empty or partial final page; refusing partial window" >&2
fi
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
