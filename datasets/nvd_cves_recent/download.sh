#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cves_recent"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

NVD_YEAR="${NVD_YEAR:-2024}"
RESULTS_PER_PAGE="${NVD_RESULTS_PER_PAGE:-2000}"
REQUEST_DELAY="${NVD_REQUEST_DELAY:-6}"
MIN_CVE_RECORDS="${MIN_CVE_RECORDS:-10000}"
MAX_SOURCE_BYTES="${MAX_SOURCE_BYTES:-250000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY_TSV="$DOWNLOAD_DIR/download_inventory.tsv"
INVENTORY_JSON="$DOWNLOAD_DIR/download_inventory.json"

WINDOWS_TSV="$DOWNLOAD_DIR/windows.tsv"
export NVD_YEAR WINDOWS_TSV
python3 - <<'PY'
from __future__ import annotations

import calendar
import os
from pathlib import Path

year = int(os.environ["NVD_YEAR"])
out = Path(os.environ["WINDOWS_TSV"])
with out.open("w", encoding="utf-8") as fh:
    fh.write("window_id\tstart\tend\n")
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        fh.write(
            f"{year}_{month:02d}\t"
            f"{year}-{month:02d}-01T00:00:00.000\t"
            f"{year}-{month:02d}-{last_day:02d}T23:59:59.999\n"
        )
PY

printf "local_name\turl\twindow_id\tpub_start\tpub_end\tstart_index\n" > "$PLAN"
printf "local_name\twindow_id\tpub_start\tpub_end\tstart_index\ttotal_results\tresults_per_page\tresult_count\tsource_bytes\n" > "$INVENTORY_TSV"

curl_args=(
  --globoff
  -fL
  --retry 3
  --retry-delay 5
  -A "openzl-public-datasets/1.0"
)
if [[ -n "${NVD_API_KEY:-}" ]]; then
  curl_args+=(-H "apiKey: ${NVD_API_KEY}")
fi

downloaded_total=0
new_fetches=0

validate_page() {
  local path="$1"
  python3 - "$path" <<'PY'
from __future__ import annotations

import json
import sys

path = sys.argv[1]
obj = json.load(open(path, encoding="utf-8"))
required = ["resultsPerPage", "startIndex", "totalResults", "vulnerabilities"]
missing = [key for key in required if key not in obj]
if missing:
    raise SystemExit(f"bad NVD payload {path}: missing {missing}")
if not isinstance(obj["vulnerabilities"], list):
    raise SystemExit(f"bad NVD payload {path}: vulnerabilities is not a list")
print(f"{int(obj['totalResults'])}\t{int(obj['resultsPerPage'])}\t{len(obj['vulnerabilities'])}")
PY
}

while IFS=$'\t' read -r window_id pub_start pub_end; do
  [[ "$window_id" != "window_id" ]] || continue
  start_index=0
  total_results=-1
  while (( total_results < 0 || start_index < total_results )); do
    local_name="${window_id}_start$(printf '%06d' "$start_index").json"
    url="https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=${RESULTS_PER_PAGE}&startIndex=${start_index}&pubStartDate=${pub_start}&pubEndDate=${pub_end}"
    target="$DOWNLOAD_DIR/$local_name"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$local_name" "$url" "$window_id" "$pub_start" "$pub_end" "$start_index" >> "$PLAN"
    if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
      echo "cache_hit window=$window_id start_index=$start_index path=$target"
    else
      tmp="$target.tmp"
      rm -f "$tmp"
      echo "fetch window=$window_id start_index=$start_index"
      curl "${curl_args[@]}" -o "$tmp" "$url"
      mv "$tmp" "$target"
      new_fetches=$((new_fetches + 1))
      if [[ "$REQUEST_DELAY" != "0" ]]; then
        sleep "$REQUEST_DELAY"
      fi
    fi
    page_info="$(validate_page "$target")"
    IFS=$'\t' read -r total_results results_per_page result_count <<< "$page_info"
    size="$(wc -c < "$target")"
    downloaded_total=$((downloaded_total + size))
    if (( downloaded_total > MAX_SOURCE_BYTES )); then
      echo "downloaded source bytes exceed cap: $downloaded_total > $MAX_SOURCE_BYTES" >&2
      exit 1
    fi
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$local_name" "$window_id" "$pub_start" "$pub_end" "$start_index" \
      "$total_results" "$results_per_page" "$result_count" "$size" >> "$INVENTORY_TSV"
    if (( result_count == 0 )); then
      break
    fi
    start_index=$((start_index + results_per_page))
  done
done < "$WINDOWS_TSV"

export DOWNLOAD_DIR INVENTORY_TSV INVENTORY_JSON MIN_CVE_RECORDS MAX_SOURCE_BYTES NVD_YEAR
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
inventory_tsv = Path(os.environ["INVENTORY_TSV"])
inventory_json = Path(os.environ["INVENTORY_JSON"])
min_cves = int(os.environ["MIN_CVE_RECORDS"])
max_source_bytes = int(os.environ["MAX_SOURCE_BYTES"])
year = int(os.environ["NVD_YEAR"])

records = []
seen_ids: set[str] = set()
duplicate_ids: set[str] = set()
total_cves = 0
source_bytes = 0
with inventory_tsv.open(encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_name"]
        obj = json.load(open(path, encoding="utf-8"))
        ids = []
        for wrapper in obj.get("vulnerabilities", []):
            cve_id = str(wrapper.get("cve", {}).get("id", "")).strip()
            if not cve_id:
                continue
            if cve_id in seen_ids:
                duplicate_ids.add(cve_id)
            seen_ids.add(cve_id)
            ids.append(cve_id)
        count = len(ids)
        total_cves += count
        size = int(row["source_bytes"])
        source_bytes += size
        records.append({**row, "source_bytes": size, "cve_count": count, "first_cve_id": ids[0] if ids else "", "last_cve_id": ids[-1] if ids else ""})

if total_cves < min_cves:
    raise SystemExit(f"NVD download below repair floor: cves={total_cves} < {min_cves}")
if source_bytes > max_source_bytes:
    raise SystemExit(f"NVD source bytes exceed cap: {source_bytes} > {max_source_bytes}")

inventory = {
    "dataset_id": "nvd_cves_recent",
    "nvd_year": year,
    "page_count": len(records),
    "total_cves": total_cves,
    "unique_cves": len(seen_ids),
    "duplicate_cves": len(duplicate_ids),
    "source_bytes": source_bytes,
    "records": records,
}
inventory_json.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"semantic_validation=downloaded pages={len(records)} total_cves={total_cves} "
    f"unique_cves={len(seen_ids)} duplicate_cves={len(duplicate_ids)} source_bytes={source_bytes}"
)
PY

echo "new_fetches=$new_fetches"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
