#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gutendex_catalog_books"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

BASE_URL="https://gutendex.com/books/"
USER_AGENT="${GUTENDEX_USER_AGENT:-openzl-public-datasets/1.0}"
MAX_PAGES="${GUTENDEX_MAX_PAGES:-5000}"
DELAY_SECONDS="${GUTENDEX_DELAY_SECONDS:-0.1}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'page\tstatus\tdetail\n' > "$FAILURES"
printf 'page\turl\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  for page in 1 2 3 4 5; do
    url="$BASE_URL?sort=ascending&page=$page"
    printf '%s\t%s\n' "$page" "$url" >> "$PLAN"
    echo "dry_run url=$url"
  done
  echo "dry_run note=actual run follows API next links until next=null"
  echo "failure_count=0"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

page=1
next_url="$BASE_URL?sort=ascending&page=1"
while [[ -n "$next_url" ]]; do
  if (( page > MAX_PAGES )); then
    printf '%s\tfailed\tmax_pages_exceeded_%s\n' "$page" "$MAX_PAGES" >> "$FAILURES"
    break
  fi
  name="$(printf 'gutendex_catalog_books_page_%05d.json' "$page")"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%s\n' "$page" "$next_url" >> "$PLAN"
  if [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch page=$page url=$next_url"
    if ! curl --globoff --fail --location --show-error --retry 3 --retry-delay 5 -A "$USER_AGENT" -o "$target.tmp" "$next_url"; then
      printf '%s\tfailed\tcurl_failed\n' "$page" >> "$FAILURES"
      rm -f "$target.tmp"
      break
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit page=$page path=$target"
  fi
  next_url="$(
    python3 - "$target" <<'PY'
import json
import sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(obj.get("results"), list):
    raise SystemExit("missing results")
if "count" not in obj:
    raise SystemExit("missing count")
print(obj.get("next") or "")
PY
  )"
  results_count="$(python3 - "$target" <<'PY'
import json
import sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(obj["results"]))
PY
  )"
  echo "validated_page=$name results=$results_count next_present=$([[ -n "$next_url" ]] && echo 1 || echo 0)"
  page=$((page + 1))
  sleep "$DELAY_SECONDS"
done

python3 - "$DOWNLOAD_DIR" <<'PY'
import json
import sys
from pathlib import Path

download_dir = Path(sys.argv[1])
pages = sorted(download_dir.glob("gutendex_catalog_books_page_*.json"))
if not pages:
    raise SystemExit("no Gutendex pages downloaded")
resources = []
api_counts = set()
row_count = 0
for path in pages:
    obj = json.loads(path.read_text(encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{path.name}: missing results")
    api_counts.add(int(obj["count"]))
    row_count += len(results)
    resources.append(
        {
            "page_file": path.name,
            "bytes": path.stat().st_size,
            "results": len(results),
            "next_present": bool(obj.get("next")),
        }
    )
if len(api_counts) != 1:
    raise SystemExit(f"inconsistent API count values: {sorted(api_counts)}")
api_count = api_counts.pop()
if row_count != api_count:
    raise SystemExit(f"downloaded rows do not match API count: rows={row_count} count={api_count}")
inventory = {
    "dataset_id": "gutendex_catalog_books",
    "page_count": len(pages),
    "row_count": row_count,
    "api_count": api_count,
    "source_bytes": sum(item["bytes"] for item in resources),
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote download_inventory.json pages={len(pages)} rows={row_count} source_bytes={inventory['source_bytes']}")
PY

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
