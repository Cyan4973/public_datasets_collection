#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="census_acs_pums_ca_person_2023_i64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

ARCHIVE_NAME="csv_pca.zip"
SOURCE_URL="https://www2.census.gov/programs-surveys/acs/data/pums/2023/1-Year/$ARCHIVE_NAME"
TARGET="$DOWNLOAD_DIR/$ARCHIVE_NAME"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
printf 'resource\tstatus\tdetail\n' > "$FAILURES"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ ! -f "$TARGET" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  echo "fetch url=$SOURCE_URL"
  if ! curl -L --fail --show-error --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$TARGET.tmp" "$SOURCE_URL"; then
    printf 'csv_pca_zip\tfailed\tcurl_failed\n' >> "$FAILURES"
    rm -f "$TARGET.tmp"
    exit 1
  fi
  mv "$TARGET.tmp" "$TARGET"
else
  echo "cache_hit $TARGET"
fi

if ! python3 - "$TARGET" <<'PY'
import csv, sys, zipfile
path = sys.argv[1]
required = {"PWGTP", "PINCP", "WAGP", "WKWN"}
with zipfile.ZipFile(path) as zf:
    names = [n for n in zf.namelist() if n.lower().endswith(".csv") and n.lower().split("/")[-1].startswith("psam_p")]
    if not names:
        raise SystemExit("zip contains no ACS person CSV")
    with zf.open(sorted(names)[0]) as fh:
        header = next(csv.reader([fh.readline().decode("utf-8-sig", errors="replace")]))
missing = sorted(required - set(header))
if missing:
    raise SystemExit(f"missing required columns: {missing}")
print(f"validated_zip={path} person_csv_members={len(names)} first_member={sorted(names)[0]}")
PY
then
  printf 'csv_pca_zip\tfailed\tsemantic_validation_failed\n' >> "$FAILURES"
  exit 1
fi

echo "failure_count=0"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
