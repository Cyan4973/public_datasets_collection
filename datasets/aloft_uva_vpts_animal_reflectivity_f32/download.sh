#!/usr/bin/env bash
# Download the frozen UVA_VPTS Zenodo deposit pieces used by this recipe:
# record metadata (license/size/checksum pins), coverage.csv, the VPTS CSV
# table schema, and the German country archive de.tgz (1,231,349,011 bytes).
# Belgian/Dutch archives and the Aloft bucket's baltrad/ prefix are never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="aloft_uva_vpts_animal_reflectivity_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

RECORD_ID=14711244
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
ARCHIVE_NAME="de.tgz"
ARCHIVE_BYTES=1231349011
ARCHIVE_MD5="77459683bb0d30c16af21ab2d706b260"
COVERAGE_NAME="coverage.csv"
COVERAGE_BYTES=920447
COVERAGE_MD5="cdc339b008122fcebc9d3414969c07a4"
SCHEMA_NAME="vpts-csv-table-schema.json"
SCHEMA_BYTES=7238
SCHEMA_MD5="f94e2865bb363c56f37e1b4cd87edba2"
UA="openzl-public-datasets-uva-vpts/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID record=$RECORD_ID"

file_ok() {
  # file_ok <path> <bytes> <md5>
  [ -f "$1" ] || return 1
  [ "$(wc -c < "$1" | tr -d ' ')" = "$2" ] || return 1
  printf '%s  %s\n' "$3" "$1" | md5sum --check --status
}

# 1. Record metadata: identity, CC0 license, and exact size/MD5 of every file used.
metadata="$DOWNLOAD_DIR/record.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 20 --retry-delay 30 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 - "$metadata" "$RECORD_ID" \
  "$ARCHIVE_NAME" "$ARCHIVE_BYTES" "$ARCHIVE_MD5" \
  "$COVERAGE_NAME" "$COVERAGE_BYTES" "$COVERAGE_MD5" \
  "$SCHEMA_NAME" "$SCHEMA_BYTES" "$SCHEMA_MD5" <<'PY'
import json
import sys

path, record_id = sys.argv[1], int(sys.argv[2])
pins = [(sys.argv[i], int(sys.argv[i + 1]), sys.argv[i + 2]) for i in (3, 6, 9)]
record = json.load(open(path, encoding="utf-8"))
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
metadata = record.get("metadata") or {}
title = str(metadata.get("title", ""))
if not title.startswith("UVA_VPTS") or "Germany" not in title:
    raise SystemExit(f"record title does not identify UVA_VPTS: {title!r}")
if metadata.get("publication_date") != "2025-01-25":
    raise SystemExit(f"record publication date changed: {metadata.get('publication_date')!r}")
license_value = metadata.get("license")
license_id = str((license_value or {}).get("id", "")) if isinstance(license_value, dict) else str(license_value or "")
if license_id.lower() != "cc-zero":
    raise SystemExit(f"record license is not cc-zero: {license_id!r}")
files = {item.get("key"): item for item in record.get("files", []) if isinstance(item, dict)}
for name, size, md5 in pins:
    item = files.get(name)
    if item is None:
        raise SystemExit(f"record has no file {name!r}")
    if int(item.get("size") or 0) != size or str(item.get("checksum", "")).lower() != f"md5:{md5}":
        raise SystemExit(f"file pin changed for {name}: size={item.get('size')} checksum={item.get('checksum')}")
print(f"metadata_ok record={record_id} license=cc-zero title={title!r}")
PY

# 2. Small deposit files.
fetch_small() {
  local name="$1" bytes="$2" md5="$3"
  local out="$DOWNLOAD_DIR/$name"
  if file_ok "$out" "$bytes" "$md5"; then
    echo "cache_hit $name"
    return 0
  fi
  rm -f "$out" "$out.part"
  curl --fail --silent --show-error --location \
    --retry 20 --retry-delay 30 --retry-all-errors \
    --max-time 300 --max-filesize "$((bytes + 1024))" \
    --user-agent "$UA" --output "$out.part" "$FILE_BASE/$name/content"
  if ! file_ok "$out.part" "$bytes" "$md5"; then
    echo "FATAL: $name size/MD5 mismatch" >&2
    rm -f "$out.part"
    exit 1
  fi
  mv "$out.part" "$out"
  echo "fetched $name bytes=$bytes md5=$md5"
}
fetch_small "$COVERAGE_NAME" "$COVERAGE_BYTES" "$COVERAGE_MD5"
fetch_small "$SCHEMA_NAME" "$SCHEMA_BYTES" "$SCHEMA_MD5"

python3 - "$DOWNLOAD_DIR/$SCHEMA_NAME" <<'PY'
import json
import sys

schema = json.load(open(sys.argv[1], encoding="utf-8"))
names = [field["name"] for field in schema["fields"]]
expected = [
    "radar", "datetime", "height", "u", "v", "w", "ff", "dd", "sd_vvp", "gap", "eta",
    "dens", "dbz", "dbz_all", "n", "n_dbz", "n_all", "n_dbz_all", "rcs",
    "sd_vvp_threshold", "vcp", "radar_latitude", "radar_longitude", "radar_height",
    "radar_wavelength", "source_file",
]
if names != expected:
    raise SystemExit(f"VPTS CSV schema field list changed: {names}")
if schema.get("missingValues") != ["", "NA", "NaN"]:
    raise SystemExit(f"VPTS CSV missingValues changed: {schema.get('missingValues')}")
eta = schema["fields"][names.index("eta")]
if eta.get("type") != "number" or "cm^2/km^3" not in eta.get("description", ""):
    raise SystemExit(f"eta field definition changed: {eta}")
print("schema_ok fields=26 missingValues=['', 'NA', 'NaN'] eta=number cm^2/km^3")
PY

# 3. German country archive: resumable, stall-bounded transfer, then size + MD5.
archive="$DOWNLOAD_DIR/$ARCHIVE_NAME"
if file_ok "$archive" "$ARCHIVE_BYTES" "$ARCHIVE_MD5"; then
  echo "cache_hit $ARCHIVE_NAME"
else
  rm -f "$archive"
  part="$archive.part"
  for attempt in $(seq 1 20); do
    have=0
    [ -f "$part" ] && have="$(wc -c < "$part" | tr -d ' ')"
    if [ "$have" -gt "$ARCHIVE_BYTES" ]; then
      echo "partial file larger than expected; restarting"
      rm -f "$part"
      have=0
    fi
    if [ "$have" -eq "$ARCHIVE_BYTES" ]; then
      break
    fi
    echo "attempt=$attempt resume_from=$have expected=$ARCHIVE_BYTES"
    curl --fail --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$FILE_BASE/$ARCHIVE_NAME/content" || {
      echo "curl exited with status $?; retrying"
      sleep 30
    }
  done
  if ! file_ok "$part" "$ARCHIVE_BYTES" "$ARCHIVE_MD5"; then
    echo "FATAL: $ARCHIVE_NAME size/MD5 mismatch after download" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$archive"
  echo "fetched $ARCHIVE_NAME bytes=$ARCHIVE_BYTES md5=$ARCHIVE_MD5"
fi

# 4. Semantic check: the archive's radar-month members must equal the German
#    radar-months listed in the deposit's coverage.csv (465 members, 18 radars).
python3 "$RECIPE_DIR/scripts/vpts.py" inventory \
  --archive "$archive" --coverage "$DOWNLOAD_DIR/$COVERAGE_NAME"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
