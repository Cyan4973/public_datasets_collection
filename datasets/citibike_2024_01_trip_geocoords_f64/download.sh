#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_01_trip_geocoords_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

ARCHIVE_NAME="202401-citibike-tripdata.zip"
SOURCE_URL="https://s3.amazonaws.com/tripdata/$ARCHIVE_NAME"
EXPECTED_BYTES="369035302"
EXPECTED_SHA256="0a2e81eacd7bf3890712de8f2a1b56bda985c17d9e61b08acf5e7c7ec9f20eb0"
TARGET="$DOWNLOAD_DIR/$ARCHIVE_NAME"
SHARED_CACHE="$REPO_ROOT/$DATA_DIR/downloads/citibike_2024_01_station_ids_u16/$ARCHIVE_NAME"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
printf 'resource\tstatus\tdetail\n' > "$FAILURES"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

validate_archive() {
  local path="$1" bytes sha
  bytes="$(wc -c < "$path" | tr -d ' ')"
  [[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "size mismatch path=$path actual=$bytes expected=$EXPECTED_BYTES"; return 1; }
  sha="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$sha" == "$EXPECTED_SHA256" ]] || { echo "sha256 mismatch path=$path actual=$sha expected=$EXPECTED_SHA256"; return 1; }
  python3 - "$path" <<'PY'
import csv, sys, zipfile
path = sys.argv[1]
required = {"start_lat", "start_lng", "end_lat", "end_lng"}
with zipfile.ZipFile(path) as zf:
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise SystemExit("zip contains no csv")
    with zf.open(names[0]) as fh:
        header = next(csv.reader([fh.readline().decode("utf-8-sig", errors="replace")]))
missing = sorted(required - set(header))
if missing:
    raise SystemExit(f"missing required columns: {missing}")
print(f"validated_zip_members={len(names)} first_member={names[0]}")
PY
}

if [[ -n "${CITIBIKE_ARCHIVE:-}" ]]; then
  echo "using local CITIBIKE_ARCHIVE=$CITIBIKE_ARCHIVE"
  cp "$CITIBIKE_ARCHIVE" "$TARGET.tmp"
  mv "$TARGET.tmp" "$TARGET"
elif [[ -f "$SHARED_CACHE" ]]; then
  echo "using existing shared cache $SHARED_CACHE"
  cp "$SHARED_CACHE" "$TARGET.tmp"
  mv "$TARGET.tmp" "$TARGET"
elif [[ ! -f "$TARGET" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  echo "fetch url=$SOURCE_URL"
  curl -L --fail --show-error --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$TARGET.tmp" "$SOURCE_URL"
  mv "$TARGET.tmp" "$TARGET"
else
  echo "cache_hit $TARGET"
fi

if ! validate_archive "$TARGET"; then
  printf 'january_2024_zip\tfailed\tarchive failed validation\n' >> "$FAILURES"
  exit 1
fi

echo "failure_count=0"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
