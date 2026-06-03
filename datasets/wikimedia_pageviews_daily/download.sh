#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wikimedia_pageviews_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
START="20240101"
END="20241231"

download_one() {
  local project="$1"
  local article="$2"
  local slug="$3"
  local out="$DOWNLOAD_DIR/${slug}.json"
  if [ -s "$out" ]; then
    echo "cached payload=$slug bytes=$(wc -c < "$out" | tr -d ' ')"
    return
  fi
  curl -fL --retry 3 --retry-delay 2 \
    -H "User-Agent: Mozilla/5.0 (openzl dataset collection)" \
    -H "Accept: application/json" \
    -o "$out" \
    "$BASE_URL/$project/all-access/all-agents/$article/daily/$START/$END"
  python3 - <<'PY' "$out" "$slug"
import json, sys
path, slug = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
items = payload.get("items")
if not isinstance(items, list) or not items:
    raise SystemExit(f"{slug}: empty or missing items")
if any("views" not in item or "timestamp" not in item for item in items):
    raise SystemExit(f"{slug}: malformed pageview items")
print(f"validated payload={slug} items={len(items)}")
PY
}

download_one en.wikipedia Main_Page en_wikipedia_main_page
download_one en.wikipedia Python_%28programming_language%29 en_wikipedia_python_programming_language
download_one en.wikipedia New_York_City en_wikipedia_new_york_city
download_one de.wikipedia Berlin de_wikipedia_berlin
download_one fr.wikipedia Paris fr_wikipedia_paris
download_one es.wikipedia Madrid es_wikipedia_madrid
download_one it.wikipedia Roma it_wikipedia_roma

count="$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
test "$count" = "7"

echo "[$(date -Is)] download done dataset=$DATASET_ID count=$count"
