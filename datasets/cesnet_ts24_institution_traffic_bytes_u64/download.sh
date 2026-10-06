#!/usr/bin/env bash
# Fetch the pinned CESNET-TimeSeries24 institution archive, the 10-minute time
# grid and the Zenodo record metadata, then validate identity and structure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="cesnet_ts24_institution_traffic_bytes_u64"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

RECORD_URL="https://zenodo.org/api/records/13382427"
ARCHIVE_URL="https://zenodo.org/api/records/13382427/files/institutions.tar.gz/content"
ARCHIVE_BYTES=479428489
ARCHIVE_MD5="ab3e15fb8dc9b7120ddb2318795b6812"
ARCHIVE_SHA256="f112548546ae8124dd62aa55c0628a5646dc72427f280c7cf27cfde658da6ff2"
TIMES_URL="https://zenodo.org/api/records/13382427/files/times.tar.gz/content"
TIMES_BYTES=211467
TIMES_MD5="a03813763e07646ca38f17ffd53e549e"
TIMES_SHA256="f1b0c8e20127df0646379d583dd798f84b252c9e1c82595eed207c4a3d5e1280"
UA="openzl-public-datasets-cesnet-ts24/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

identity_ok() {
  local path="$1" bytes="$2" md5="$3"
  [[ -f "$path" ]] \
    && [[ "$(stat -c %s "$path")" == "$bytes" ]] \
    && [[ "$(md5sum "$path" | awk '{print $1}')" == "$md5" ]]
}

# Small metadata object: the live record JSON carries changing download/view
# statistics, so it is validated by field (license, DOI, file sizes and MD5s)
# in the preflight step instead of being pinned by hash.
record="$DOWNLOAD_DIR/zenodo_record_13382427.json"
if [[ ! -s "$record" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  rm -f "$record.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 30 --max-time 180 --max-filesize 5000000 \
    --user-agent "$UA" --output "$record.part" "$RECORD_URL"
  mv "$record.part" "$record"
fi
echo "record bytes=$(stat -c %s "$record")"

# Small pinned 10-minute time grid (id_time -> timestamp).
times="$DOWNLOAD_DIR/times.tar.gz"
if ! identity_ok "$times" "$TIMES_BYTES" "$TIMES_MD5" || [[ "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  rm -f "$times" "$times.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 30 --max-time 600 --max-filesize 1000000 \
    --user-agent "$UA" --output "$times.part" "$TIMES_URL"
  mv "$times.part" "$times"
fi
identity_ok "$times" "$TIMES_BYTES" "$TIMES_MD5" || { echo "FATAL: times.tar.gz size/MD5 mismatch" >&2; exit 1; }
printf '%s  %s\n' "$TIMES_SHA256" "$times" | sha256sum --check --status \
  || { echo "FATAL: times.tar.gz SHA-256 mismatch" >&2; exit 1; }
echo "times_ok bytes=$TIMES_BYTES md5=$TIMES_MD5"

# Large archive: resumable, stall-bounded transfer into a .part file.
archive="$DOWNLOAD_DIR/institutions.tar.gz"
if [[ "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  rm -f "$archive" "$archive.part"
fi
if [[ -f "$archive" ]]; then
  echo "cache_hit path=$archive"
else
  attempt=0
  while :; do
    have=0
    [[ -f "$archive.part" ]] && have="$(stat -c %s "$archive.part")"
    if (( have > ARCHIVE_BYTES )); then
      echo "partial file larger than expected ($have > $ARCHIVE_BYTES); restarting"
      rm -f "$archive.part"
      have=0
    fi
    (( have == ARCHIVE_BYTES )) && break
    attempt=$((attempt + 1))
    if (( attempt > 8 )); then
      echo "FATAL: giving up after $((attempt - 1)) curl attempts at $have/$ARCHIVE_BYTES bytes" >&2
      exit 1
    fi
    echo "[$(date -Is)] curl attempt=$attempt resume_from=$have expected=$ARCHIVE_BYTES"
    curl --fail --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --connect-timeout 30 \
      --no-progress-meter --user-agent "$UA" \
      --output "$archive.part" "$ARCHIVE_URL" \
      || echo "curl exit=$? at $(stat -c %s "$archive.part" 2>/dev/null || echo 0) bytes; resuming"
  done
  mv "$archive.part" "$archive"
fi
if ! identity_ok "$archive" "$ARCHIVE_BYTES" "$ARCHIVE_MD5"; then
  echo "FATAL: institutions.tar.gz size/MD5 mismatch (got $(stat -c %s "$archive") bytes); removing corrupt file" >&2
  rm -f "$archive"
  exit 1
fi
printf '%s  %s\n' "$ARCHIVE_SHA256" "$archive" | sha256sum --check --status \
  || { echo "FATAL: institutions.tar.gz SHA-256 mismatch" >&2; exit 1; }
gzip -t "$archive"
echo "archive_ok bytes=$ARCHIVE_BYTES md5=$ARCHIVE_MD5 sha256=$ARCHIVE_SHA256"

# Semantic validation: CC-BY-4.0 record, contiguous 40,298-window grid, and an
# archive whose agg_10_minutes CSVs match identifiers.csv and carry id_time and
# n_bytes columns.
python3 "$RECIPE_DIR/scripts/build_samples.py" preflight \
  --record "$record" --times "$times" --archive "$archive" \
  --profile "$LOG_DIR/source_profile.json"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
