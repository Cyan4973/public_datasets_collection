#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_daily_values_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# One family per parameter; one sample per site. Many sites => query several states,
# one (state, parameter) request each (statCd=00003 = daily mean).
STATES="${USGS_STATES:-co or ga ut ia}"
PARAMS="${USGS_PARAMS:-00060 00065 00010}"
START_DT="${USGS_START_DT:-2019-01-01}"
END_DT="${USGS_END_DT:-2024-12-31}"
REQUEST_DELAY="${USGS_REQUEST_DELAY_SECONDS:-1.0}"
MIN_SERIES="${USGS_MIN_SERIES:-50}"
BASE_URL="https://waterservices.usgs.gov/nwis/dv/"

echo "[$(date -Is)] download_start dataset=$DATASET_ID states='$STATES' params='$PARAMS' window=${START_DT}..${END_DT}"

for st in $STATES; do
  for p in $PARAMS; do
    out="$PAGE_DIR/usgs_${p}_${st}.json"
    tmp="$out.tmp"
    if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
      echo "cache_hit param=$p state=$st path=$out"
      continue
    fi
    rm -f "$tmp"
    url="${BASE_URL}?format=json&stateCd=${st}&parameterCd=${p}&statCd=00003&startDT=${START_DT}&endDT=${END_DT}&siteStatus=all"
    echo "fetch param=$p state=$st"
    if ! curl --globoff -fL --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"; then
      echo "skip_failed param=$p state=$st (request error)"
      rm -f "$tmp"
      continue
    fi
    if ! python3 - "$tmp" <<'PY'; then
import json, sys
try:
    obj = json.load(open(sys.argv[1], encoding="utf-8"))
    ts = obj["value"]["timeSeries"]
except Exception as exc:
    raise SystemExit(f"bad payload: {exc}")
PY
      echo "skip_invalid param=$p state=$st"
      rm -f "$tmp"
      continue
    fi
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  done
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_SERIES"
import json
import sys
from collections import defaultdict
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_series = int(sys.argv[3])
per_param_sites = defaultdict(set)
pages = []
for path in sorted(page_dir.glob("usgs_*.json")):
    with path.open(encoding="utf-8") as fh:
        ts = json.load(fh)["value"]["timeSeries"]
    n = 0
    for t in ts:
        param = t["variable"]["variableCode"][0]["value"]
        site = t["sourceInfo"]["siteCode"][0]["value"]
        vals = t.get("values") or []
        has = any(w.get("value") for w in vals)
        if has:
            per_param_sites[param].add(site)
            n += 1
    pages.append({"path": path.name, "nonempty_series": n})

total_site_series = sum(len(s) for s in per_param_sites.values())
if total_site_series < min_series:
    raise SystemExit(f"only {total_site_series} (param,site) series, need {min_series}")

stats = {
    "dataset_id": "usgs_daily_values_large",
    "pages": pages,
    "sites_per_param": {k: len(v) for k, v in sorted(per_param_sites.items())},
    "total_site_series": total_site_series,
    "min_series": min_series,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"pages={len(pages)} sites_per_param={ {k: len(v) for k,v in sorted(per_param_sites.items())} } total={total_site_series}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
