#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_trip_geocoords_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MONTHS=(202401 202402 202403 202404 202405 202406 202407 202408 202409 202410 202411 202412)
BASE_URL="https://s3.amazonaws.com/tripdata"
USER_AGENT="${CITIBIKE_USER_AGENT:-openzl-public-datasets/1.0}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'resource\tstatus\tdetail\n' > "$FAILURES"
printf 'archive\turl\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

validate_archive() {
  local path="$1"
  python3 - "$path" <<'PY'
import csv
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
required = {"start_lat", "start_lng", "end_lat", "end_lng"}
with zipfile.ZipFile(path) as zf:
    names = sorted(n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".csv"))
    if not names:
        raise SystemExit("zip contains no csv")
    for name in names:
        with zf.open(name) as fh:
            header = next(csv.reader([fh.readline().decode("utf-8-sig", errors="replace")]))
        missing = sorted(required - set(header))
        if missing:
            raise SystemExit(f"{name}: missing required columns: {missing}")
print(f"validated_zip={path.name} csv_members={len(names)}")
PY
}

for month in "${MONTHS[@]}"; do
  archive="${month}-citibike-tripdata.zip"
  url="$BASE_URL/$archive"
  target="$DOWNLOAD_DIR/$archive"
  printf '%s\t%s\n' "$archive" "$url" >> "$PLAN"

  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run url=$url"
    continue
  fi

  source_path=""
  if [[ -n "${CITIBIKE_ARCHIVES_DIR:-}" && -f "$CITIBIKE_ARCHIVES_DIR/$archive" ]]; then
    source_path="$CITIBIKE_ARCHIVES_DIR/$archive"
  elif [[ -f "$REPO_ROOT/$DATA_DIR/downloads/citibike_2024_01_trip_geocoords_f64/$archive" ]]; then
    source_path="$REPO_ROOT/$DATA_DIR/downloads/citibike_2024_01_trip_geocoords_f64/$archive"
  elif [[ -f "$REPO_ROOT/$DATA_DIR/downloads/citibike_2024_01_station_ids_u16/$archive" ]]; then
    source_path="$REPO_ROOT/$DATA_DIR/downloads/citibike_2024_01_station_ids_u16/$archive"
  fi

  if [[ -n "$source_path" ]]; then
    echo "using local archive=$source_path"
    cp "$source_path" "$target.tmp"
    mv "$target.tmp" "$target"
  elif [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch url=$url"
    if ! curl -L --fail --show-error --retry 3 --retry-delay 5 -A "$USER_AGENT" -o "$target.tmp" "$url"; then
      printf '%s\tfailed\tcurl_failed\n' "$archive" >> "$FAILURES"
      rm -f "$target.tmp"
      continue
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit $target"
  fi

  if ! validate_archive "$target"; then
    printf '%s\tfailed\tarchive_failed_validation\n' "$archive" >> "$FAILURES"
  fi
done

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  python3 - "$DOWNLOAD_DIR" <<'PY'
import hashlib
import json
import sys
import zipfile
from pathlib import Path

download_dir = Path(sys.argv[1])
expected = [f"2024{month:02d}-citibike-tripdata.zip" for month in range(1, 13)]
resources = []
missing = []
for name in expected:
    path = download_dir / name
    if not path.exists():
        missing.append(name)
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as zf:
        members = sorted(n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".csv"))
    resources.append(
        {
            "archive": name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "csv_members": members,
            "source_url": f"https://s3.amazonaws.com/tripdata/{name}",
        }
    )
inventory = {
    "dataset_id": "citibike_2024_trip_geocoords_f64",
    "expected_archives": expected,
    "missing_archives": missing,
    "resource_count": len(resources),
    "source_bytes": sum(item["bytes"] for item in resources),
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if missing:
    raise SystemExit(f"missing expected archives: {missing}")
print(f"wrote download_inventory.json resources={len(resources)} source_bytes={inventory['source_bytes']}")
PY
fi

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
