#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ooni_measurements"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

BASE_URL="${OONI_BASE_URL:-https://api.ooni.io/api/v1/measurements}"
TEST_NAME="${OONI_TEST_NAME:-web_connectivity}"
SINCE="${OONI_SINCE:-2024-01-01T00:00:00Z}"
UNTIL="${OONI_UNTIL:-2024-02-01T00:00:00Z}"
LIMIT="${OONI_LIMIT:-1000}"
TARGET_RECORDS="${OONI_TARGET_RECORDS:-20000}"
MIN_COMPLETE_RECORDS="${OONI_MIN_COMPLETE_RECORDS:-10000}"
MAX_PAGES="${OONI_MAX_PAGES:-40}"
DELAY_SECONDS="${OONI_DELAY_SECONDS:-0.2}"
USER_AGENT="${OONI_USER_AGENT:-openzl-public-datasets/1.0}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'page\tstatus\tdetail\n' > "$FAILURES"
printf 'page\toffset\turl\tlocal_name\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID test_name=$TEST_NAME since=$SINCE until=$UNTIL target_records=$TARGET_RECORDS limit=$LIMIT"

make_url() {
  local offset="$1"
  python3 - "$BASE_URL" "$TEST_NAME" "$SINCE" "$UNTIL" "$LIMIT" "$offset" <<'PY'
import sys
from urllib.parse import urlencode

base_url, test_name, since, until, limit, offset = sys.argv[1:]
query = urlencode(
    {
        "test_name": test_name,
        "since": since,
        "until": until,
        "limit": limit,
        "offset": offset,
    }
)
print(f"{base_url}?{query}")
PY
}

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  url="$(make_url 0)"
  printf '1\t0\t%s\t%s\n' "$url" "ooni_measurements_page_00001.json" >> "$PLAN"
  echo "dry_run url=$url"
  echo "dry_run note=actual run advances offset by LIMIT until TARGET_RECORDS or endpoint exhaustion"
  echo "failure_count=0"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

offset=0
page=1
total_records=0
complete_records=0
previous_signature=""
while (( total_records < TARGET_RECORDS )); do
  if (( page > MAX_PAGES )); then
    printf '%s\tfailed\tmax_pages_exceeded_%s\n' "$page" "$MAX_PAGES" >> "$FAILURES"
    break
  fi

  url="$(make_url "$offset")"
  name="$(printf 'ooni_measurements_page_%05d.json' "$page")"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%s\t%s\t%s\n' "$page" "$offset" "$url" "$name" >> "$PLAN"

  if [[ ! -s "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch page=$page offset=$offset url=$url"
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
      "$url"; then
      printf '%s\tfailed\tcurl_failed\n' "$page" >> "$FAILURES"
      rm -f "$target.tmp"
      break
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit page=$page offset=$offset path=$target"
  fi

  page_info="$(
    python3 - "$target" "$TEST_NAME" <<'PY'
import json
import sys

path, expected_test = sys.argv[1:]
obj = json.load(open(path, encoding="utf-8"))
results = obj.get("results")
if not isinstance(results, list):
    raise SystemExit("missing results list")
if not results:
    print("0\t0\t")
    raise SystemExit(0)

complete = 0
signatures = []
for row in results:
    if not isinstance(row, dict):
        continue
    if row.get("test_name") != expected_test:
        raise SystemExit(f"unexpected test_name={row.get('test_name')!r}")
    uid = row.get("measurement_uid") or row.get("report_id") or ""
    signatures.append(str(uid) or f"{row.get('measurement_start_time')}:{row.get('probe_asn')}:{row.get('input')}")
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    if row.get("measurement_start_time") and row.get("probe_asn") and scores.get("blocking_general") is not None:
        complete += 1
signature = f"{signatures[0]}|{signatures[-1]}" if signatures else ""
print(f"{len(results)}\t{complete}\t{signature}")
PY
  )"
  page_records="$(printf '%s' "$page_info" | cut -f1)"
  page_complete="$(printf '%s' "$page_info" | cut -f2)"
  signature="$(printf '%s' "$page_info" | cut -f3-)"
  if [[ "$page_records" == "0" ]]; then
    echo "empty_page page=$page offset=$offset"
    break
  fi
  if [[ -n "$signature" && "$signature" == "$previous_signature" ]]; then
    printf '%s\tfailed\trepeated_page_signature\n' "$page" >> "$FAILURES"
    break
  fi
  previous_signature="$signature"
  total_records=$((total_records + page_records))
  complete_records=$((complete_records + page_complete))
  echo "validated_page=$name records=$page_records complete_records=$page_complete cumulative_records=$total_records cumulative_complete_records=$complete_records"

  offset=$((offset + LIMIT))
  page=$((page + 1))
  sleep "$DELAY_SECONDS"
done

python3 - "$DOWNLOAD_DIR" "$MIN_COMPLETE_RECORDS" "$TARGET_RECORDS" "$LIMIT" "$TEST_NAME" "$SINCE" "$UNTIL" <<'PY'
import json
import sys
from pathlib import Path

download_dir = Path(sys.argv[1])
min_complete = int(sys.argv[2])
target_records = int(sys.argv[3])
limit = int(sys.argv[4])
test_name, since, until = sys.argv[5:]
pages = sorted(download_dir.glob("ooni_measurements_page_*.json"))
if not pages:
    raise SystemExit("no OONI measurement pages downloaded")

resources = []
records = 0
complete_records = 0
for path in pages:
    obj = json.loads(path.read_text(encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{path.name}: missing results list")
    complete = 0
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("test_name") != test_name:
            raise SystemExit(f"{path.name}: unexpected test_name={row.get('test_name')!r}")
        scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        if row.get("measurement_start_time") and row.get("probe_asn") and scores.get("blocking_general") is not None:
            complete += 1
    records += len(results)
    complete_records += complete
    resources.append(
        {
            "page_file": path.name,
            "bytes": path.stat().st_size,
            "records": len(results),
            "complete_records": complete,
        }
    )

failure_count = 0
failures_path = download_dir / "download_failures.tsv"
if failures_path.exists():
    for line in failures_path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) > 1 and parts[1] == "failed":
            failure_count += 1

inventory = {
    "dataset_id": "ooni_measurements",
    "test_name": test_name,
    "since": since,
    "until": until,
    "requested_target_records": target_records,
    "requested_limit": limit,
    "page_count": len(resources),
    "records": records,
    "complete_records": complete_records,
    "source_bytes": sum(item["bytes"] for item in resources),
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
if failure_count:
    raise SystemExit(f"OONI download had failures: {failure_count}")
if complete_records < min_complete:
    raise SystemExit(f"OONI complete records below repair floor: {complete_records} < {min_complete}")
print(
    f"wrote download_inventory.json pages={len(resources)} records={records} "
    f"complete_records={complete_records} source_bytes={inventory['source_bytes']}"
)
PY

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
