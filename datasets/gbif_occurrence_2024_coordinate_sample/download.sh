#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gbif_occurrence_2024_coordinate_sample"
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
printf 'local_name\toffset\tlimit\turl\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="https://api.gbif.org/v1/occurrence/search"
LIMIT="${GBIF_LIMIT:-300}"
MAX_PAGES="${GBIF_MAX_PAGES:-40}"
DELAY_SECONDS="${GBIF_DELAY_SECONDS:-1}"
QUERY="hasCoordinate=true&occurrenceStatus=PRESENT&eventDate=2024-01-01,2024-01-31"
USER_AGENT="${GBIF_USER_AGENT:-openzl-public-datasets/1.0}"

for ((page = 0; page < MAX_PAGES; page++)); do
  offset=$((page * LIMIT))
  name="$(printf 'gbif_occurrence_2024_jan_offset_%06d.json' "$offset")"
  url="$BASE_URL?$QUERY&limit=$LIMIT&offset=$offset"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%d\t%d\t%s\n' "$name" "$offset" "$LIMIT" "$url" >> "$PLAN"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run url=$url"
    continue
  fi
  if [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch page=$page offset=$offset url=$url"
    if ! curl --globoff --fail --location --show-error --retry 3 --retry-delay 5 -A "$USER_AGENT" -o "$target.tmp" "$url"; then
      printf '%s\tfailed\tcurl_failed\n' "$name" >> "$FAILURES"
      rm -f "$target.tmp"
      break
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit $target"
  fi
  result_count="$(
    python3 - "$target" <<'PY'
import json
import sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
results = obj.get("results")
if not isinstance(results, list):
    raise SystemExit("missing results")
print(len(results))
PY
  )"
  echo "validated_page=$name results=$result_count"
  if (( result_count != LIMIT )); then
    printf '%s\tfailed\tunexpected_result_count_%s\n' "$name" "$result_count" >> "$FAILURES"
    echo "expected exactly $LIMIT results for fixed page sample, got $result_count for $name" >&2
    break
  fi
  sleep "$DELAY_SECONDS"
done

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
