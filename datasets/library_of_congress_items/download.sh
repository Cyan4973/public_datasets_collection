#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="library_of_congress_items"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

PAGE_COUNT="${LOC_PAGE_COUNT:-150}"
PER_PAGE="${LOC_PER_PAGE:-100}"
BASE_URL="${LOC_BASE_URL:-https://www.loc.gov/items/}"
USER_AGENT="${LOC_USER_AGENT:-openzl-public-datasets/1.0}"
MIN_RECORDS="${LOC_MIN_RECORDS:-10000}"
CURL_MAX_TIME="${LOC_CURL_MAX_TIME:-300}"
CURL_SPEED_LIMIT="${LOC_CURL_SPEED_LIMIT:-1024}"
CURL_SPEED_TIME="${LOC_CURL_SPEED_TIME:-90}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'page\tstatus\tdetail\n' > "$FAILURES"
printf 'page\turl\tlocal_name\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID pages=$PAGE_COUNT per_page=$PER_PAGE"

fetch_url() {
  local url="$1"
  local target="$2"
  rm -f "$target.tmp"
  if ! curl \
    --http1.1 \
    --globoff \
    --fail \
    --location \
    --show-error \
    --retry 6 \
    --retry-delay 5 \
    --retry-all-errors \
    --connect-timeout 30 \
    --max-time "$CURL_MAX_TIME" \
    --speed-limit "$CURL_SPEED_LIMIT" \
    --speed-time "$CURL_SPEED_TIME" \
    -A "$USER_AGENT" \
    -o "$target.tmp" \
    "$url"; then
    rm -f "$target.tmp"
    return 1
  fi
  mv "$target.tmp" "$target"
}

validate_page() {
  local path="$1"
  local page="$2"
  python3 - "$path" "$page" <<'PY'
import json
import sys

path, page = sys.argv[1], sys.argv[2]
obj = json.load(open(path, encoding="utf-8"))
results = obj.get("results")
if not isinstance(results, list):
    raise SystemExit(f"page {page}: missing results list")
if not results:
    raise SystemExit(f"page {page}: empty results list")
pagination = obj.get("pagination") or {}
print(
    f"validated_page={page} results={len(results)} "
    f"pagination_total={pagination.get('total', 'unknown')}"
)
PY
}

failure_count=0
for page in $(seq 1 "$PAGE_COUNT"); do
  name="$(printf 'items_page_%04d.json' "$page")"
  out="$DOWNLOAD_DIR/$name"
  url="${BASE_URL}?fo=json&c=${PER_PAGE}&sp=${page}"
  printf '%s\t%s\t%s\n' "$page" "$url" "$name" >> "$PLAN"

  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run page=$page url=$url target=$out"
    continue
  fi

  if [[ -s "$out" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit page=$page path=$out"
  else
    echo "fetch page=$page url=$url"
    if ! fetch_url "$url" "$out"; then
      printf '%s\tfailed\tcurl_failed\n' "$page" >> "$FAILURES"
      failure_count=$((failure_count + 1))
      continue
    fi
  fi

  if ! validate_page "$out" "$page"; then
    printf '%s\tfailed\tsemantic_validation_failed\n' "$page" >> "$FAILURES"
    failure_count=$((failure_count + 1))
  fi
done

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "failure_count=0"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

python3 - "$DOWNLOAD_DIR" "$MIN_RECORDS" "$PAGE_COUNT" "$PER_PAGE" <<'PY'
import json
import sys
from pathlib import Path

download_dir = Path(sys.argv[1])
min_records = int(sys.argv[2])
page_count = int(sys.argv[3])
per_page = int(sys.argv[4])
resources = []
total_records = 0
for path in sorted(download_dir.glob("items_page_*.json")):
    obj = json.load(open(path, encoding="utf-8"))
    rows = obj.get("results") or []
    if not rows:
        continue
    total_records += len(rows)
    resources.append({"file": path.name, "bytes": path.stat().st_size, "records": len(rows)})

inventory = {
    "dataset_id": "library_of_congress_items",
    "requested_page_count": page_count,
    "requested_per_page": per_page,
    "page_files": len(resources),
    "missing_pages": [
        page
        for page in range(1, page_count + 1)
        if not (download_dir / f"items_page_{page:04d}.json").exists()
    ],
    "records": total_records,
    "source_bytes": sum(item["bytes"] for item in resources),
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
if total_records < min_records:
    raise SystemExit(f"LOC download below repair floor: records={total_records} < {min_records}")
print(
    f"wrote download_inventory.json page_files={len(resources)} "
    f"missing_pages={len(inventory['missing_pages'])} "
    f"records={total_records} source_bytes={inventory['source_bytes']}"
)
PY

echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
