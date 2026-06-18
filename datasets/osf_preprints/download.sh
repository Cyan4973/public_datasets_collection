#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="osf_preprints"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

BASE_URL="${OSF_PREPRINTS_BASE_URL:-https://api.osf.io/v2/preprints/}"
PAGE_SIZE="${OSF_PREPRINTS_PAGE_SIZE:-100}"
TARGET_RECORDS="${OSF_PREPRINTS_TARGET_RECORDS:-20000}"
MIN_RECORDS="${OSF_PREPRINTS_MIN_RECORDS:-10000}"
MAX_PAGES="${OSF_PREPRINTS_MAX_PAGES:-250}"
DELAY_SECONDS="${OSF_PREPRINTS_DELAY_SECONDS:-0.1}"
USER_AGENT="${OSF_PREPRINTS_USER_AGENT:-openzl-public-datasets/1.0}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'page\tstatus\tdetail\n' > "$FAILURES"
printf 'page\turl\tlocal_name\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID target_records=$TARGET_RECORDS page_size=$PAGE_SIZE"

initial_url="${BASE_URL}?page[size]=${PAGE_SIZE}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "dry_run url=$initial_url"
  echo "dry_run note=actual run follows OSF JSON:API links.next until target_records or next=null"
  printf '1\t%s\t%s\n' "$initial_url" "osf_preprints_page_00001.json" >> "$PLAN"
  echo "failure_count=0"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

page=1
next_url="$initial_url"
total_records=0
while [[ -n "$next_url" && "$total_records" -lt "$TARGET_RECORDS" ]]; do
  if (( page > MAX_PAGES )); then
    printf '%s\tfailed\tmax_pages_exceeded_%s\n' "$page" "$MAX_PAGES" >> "$FAILURES"
    break
  fi

  name="$(printf 'osf_preprints_page_%05d.json' "$page")"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%s\t%s\n' "$page" "$next_url" "$name" >> "$PLAN"

  if [[ ! -s "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch page=$page url=$next_url"
    rm -f "$target.tmp"
    if ! curl \
      --globoff \
      --fail \
      --location \
      --show-error \
      --retry 5 \
      --retry-delay 5 \
      --retry-all-errors \
      --connect-timeout 30 \
      --max-time 300 \
      -A "$USER_AGENT" \
      -o "$target.tmp" \
      "$next_url"; then
      printf '%s\tfailed\tcurl_failed\n' "$page" >> "$FAILURES"
      rm -f "$target.tmp"
      break
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit page=$page path=$target"
  fi

  page_info="$(
    python3 - "$target" <<'PY'
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
data = obj.get("data")
if not isinstance(data, list):
    raise SystemExit("missing data list")
if not data:
    raise SystemExit("empty data list")
links = obj.get("links") or {}
next_url = links.get("next") or ""
complete_rows = 0
for row in data:
    attrs = row.get("attributes") if isinstance(row, dict) else None
    if not isinstance(attrs, dict):
        continue
    if attrs.get("date_created") and attrs.get("date_modified") and attrs.get("date_published"):
        complete_rows += 1
print(f"{len(data)}\t{complete_rows}\t{next_url}")
PY
  )"
  page_records="$(printf '%s' "$page_info" | cut -f1)"
  page_complete="$(printf '%s' "$page_info" | cut -f2)"
  next_url="$(printf '%s' "$page_info" | cut -f3-)"
  total_records=$((total_records + page_records))
  echo "validated_page=$name records=$page_records complete_timestamp_rows=$page_complete cumulative_records=$total_records next_present=$([[ -n "$next_url" ]] && echo 1 || echo 0)"
  page=$((page + 1))
  sleep "$DELAY_SECONDS"
done

python3 - "$DOWNLOAD_DIR" "$MIN_RECORDS" "$TARGET_RECORDS" "$PAGE_SIZE" <<'PY'
import json
import sys
from pathlib import Path

download_dir = Path(sys.argv[1])
min_records = int(sys.argv[2])
target_records = int(sys.argv[3])
page_size = int(sys.argv[4])
pages = sorted(download_dir.glob("osf_preprints_page_*.json"))
if not pages:
    raise SystemExit("no OSF preprint pages downloaded")

resources = []
total_records = 0
complete_timestamp_records = 0
for path in pages:
    obj = json.loads(path.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list) or not data:
        raise SystemExit(f"{path.name}: missing non-empty data list")
    complete = 0
    for row in data:
        attrs = row.get("attributes") if isinstance(row, dict) else None
        if isinstance(attrs, dict) and attrs.get("date_created") and attrs.get("date_modified") and attrs.get("date_published"):
            complete += 1
    total_records += len(data)
    complete_timestamp_records += complete
    resources.append(
        {
            "page_file": path.name,
            "bytes": path.stat().st_size,
            "records": len(data),
            "complete_timestamp_records": complete,
            "next_present": bool((obj.get("links") or {}).get("next")),
        }
    )

inventory = {
    "dataset_id": "osf_preprints",
    "requested_target_records": target_records,
    "requested_page_size": page_size,
    "page_count": len(resources),
    "records": total_records,
    "complete_timestamp_records": complete_timestamp_records,
    "source_bytes": sum(item["bytes"] for item in resources),
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
if complete_timestamp_records < min_records:
    raise SystemExit(
        "OSF complete timestamp records below repair floor: "
        f"{complete_timestamp_records} < {min_records}"
    )
print(
    f"wrote download_inventory.json pages={len(resources)} "
    f"records={total_records} complete_timestamp_records={complete_timestamp_records} "
    f"source_bytes={inventory['source_bytes']}"
)
PY

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
