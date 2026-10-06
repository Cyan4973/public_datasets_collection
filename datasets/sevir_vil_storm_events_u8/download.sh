#!/usr/bin/env bash
# Fetch the pinned SEVIR STORMEVENTS VIL material with exact HTTP byte ranges.
#
# Never downloads whole containers (1.39-6.15 GB each). For each of the six
# STORMEVENTS VIL HDF5 files it fetches only the metadata head [0, 2048) and
# the metadata tail (end of the `vil` payload to EOF), parses both locally,
# then fetches exactly 7,225,344 bytes per selected event (one vil[i] cube).
# Every range request carries If-Match with the pinned S3 ETag and must come
# back as 206 with the exact Content-Range; every event must pass the
# semantic checks in scripts/sevir_vil.py before it is kept.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="sevir_vil_storm_events_u8"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER=(python3 "$RECIPE_DIR/scripts/sevir_vil.py")
COMMON=(--recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT")

BASE_URL="https://sevir.s3.amazonaws.com"
UA="openzl-public-datasets-sevir-vil-download/1.0"
CATALOG_URL="$BASE_URL/CATALOG.csv"
CATALOG_SIZE=33838047
CATALOG_ETAG="f3bca535d25b6733647d45e27b59ed41-5"
CATALOG_SHA256="3209386cde96ffa80ccec3c1919090ffc601333cc651116f9fc48f224a5c2f57"
REGISTRY_URL="https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/sevir.yaml"
LICENSE_LINE="License: There are no restrictions on the use of this data."
EVENT_BYTES=7225344
VIL_DATA_ADDRESS=2048

mkdir -p "$DL/containers" "$DL/events" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

CURL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

# --- 1. license evidence: AWS Open Data registry entry (small text file) -------------------
registry="$DL/aws_registry_sevir.yaml"
"${CURL[@]}" --max-time 120 --max-filesize 100000 --output "$registry.part" "$REGISTRY_URL"
mv "$registry.part" "$registry"
grep -Fxq "$LICENSE_LINE" "$registry" || { echo "FATAL: registry license statement changed" >&2; exit 1; }
grep -Fxq "ManagedBy: Mark S. Veillette" "$registry" || { echo "FATAL: registry maintainer changed" >&2; exit 1; }
grep -Fq "arn:aws:s3:::sevir" "$registry" || { echo "FATAL: registry bucket ARN changed" >&2; exit 1; }
echo "license_ok $(grep -F 'License:' "$registry")"

# --- 2. CATALOG.csv (33.8 MB, ETag + SHA-256 pinned, resumable) ----------------------------
catalog="$DL/CATALOG.csv"
if [ -s "$catalog" ] && printf '%s  %s\n' "$CATALOG_SHA256" "$catalog" | sha256sum --check --status; then
  echo "cache_hit CATALOG.csv"
else
  rm -f "$catalog"
  part_size=0
  [ -f "$catalog.part" ] && part_size="$(stat -c %s "$catalog.part")"
  if [ "$part_size" -gt "$CATALOG_SIZE" ]; then rm -f "$catalog.part"; part_size=0; fi
  if [ "$part_size" -lt "$CATALOG_SIZE" ]; then
    "${CURL[@]}" -C - -H "If-Match: \"$CATALOG_ETAG\"" --output "$catalog.part" "$CATALOG_URL"
  fi
  actual="$(stat -c %s "$catalog.part")"
  [ "$actual" = "$CATALOG_SIZE" ] || { echo "FATAL: CATALOG.csv size $actual != $CATALOG_SIZE" >&2; exit 1; }
  printf '%s  %s\n' "$CATALOG_SHA256" "$catalog.part" | sha256sum --check --status \
    || { rm -f "$catalog.part"; echo "FATAL: CATALOG.csv SHA-256 mismatch" >&2; exit 1; }
  mv "$catalog.part" "$catalog"
  echo "fetched CATALOG.csv bytes=$CATALOG_SIZE"
fi
"${HELPER[@]}" check-catalog "${COMMON[@]}"

# --- helper: exact, ETag-guarded byte range -----------------------------------------------
fetch_range() {
  local url="$1" start="$2" end="$3" size="$4" etag="$5" out="$6"
  local want=$((end - start + 1))
  if [ -s "$out" ] && [ -s "$out.hdr" ] && [ "$(stat -c %s "$out")" = "$want" ] \
    && "${HELPER[@]}" check-headers "$out.hdr" "$start" "$end" "$size" "$etag" 2>/dev/null; then
    return 0
  fi
  rm -f "$out" "$out.hdr" "$out.part" "$out.hdr.part"
  "${CURL[@]}" --range "$start-$end" -H "If-Match: \"$etag\"" \
    --dump-header "$out.hdr.part" --output "$out.part" "$url"
  local actual
  actual="$(stat -c %s "$out.part")"
  if [ "$actual" != "$want" ]; then
    echo "FATAL: $url range $start-$end returned $actual bytes, expected $want" >&2
    rm -f "$out.part" "$out.hdr.part"
    exit 1
  fi
  "${HELPER[@]}" check-headers "$out.hdr.part" "$start" "$end" "$size" "$etag" \
    || { rm -f "$out.part" "$out.hdr.part"; exit 1; }
  mv "$out.hdr.part" "$out.hdr"
  mv "$out.part" "$out"
}

# --- 3. container metadata: head [0, 2048) and tail [end of vil payload, EOF) --------------
declare -A KEY SIZE ETAG
while IFS=$'\t' read -r -u 3 stem key size etag last_modified event_count tail_offset tail_bytes; do
  [ "$stem" = "container" ] && continue
  KEY[$stem]="$key"; SIZE[$stem]="$size"; ETAG[$stem]="$etag"
  [ "$tail_offset" = "$((VIL_DATA_ADDRESS + event_count * EVENT_BYTES))" ] \
    || { echo "FATAL: containers.tsv tail_offset inconsistent for $stem" >&2; exit 1; }
  [ "$tail_bytes" = "$((size - tail_offset))" ] \
    || { echo "FATAL: containers.tsv tail_bytes inconsistent for $stem" >&2; exit 1; }
  fetch_range "$BASE_URL/$key" 0 $((VIL_DATA_ADDRESS - 1)) "$size" "$etag" "$DL/containers/$stem.head.bin"
  fetch_range "$BASE_URL/$key" "$tail_offset" $((size - 1)) "$size" "$etag" "$DL/containers/$stem.tail.bin"
  "${HELPER[@]}" check-container "${COMMON[@]}" --container "$stem"
done 3< "$RECIPE_DIR/containers.tsv"
[ "${#KEY[@]}" = 6 ] || { echo "FATAL: expected 6 containers, got ${#KEY[@]}" >&2; exit 1; }

# --- 4. selected events: exactly one vil[i] cube per range ---------------------------------
event_count=0
event_bytes=0
while IFS=$'\t' read -r -u 3 stem file_index sevir_id _rest; do
  [ "$stem" = "container" ] && continue
  [ -n "${KEY[$stem]:-}" ] || { echo "FATAL: unknown container $stem" >&2; exit 1; }
  start=$((VIL_DATA_ADDRESS + file_index * EVENT_BYTES))
  end=$((start + EVENT_BYTES - 1))
  mkdir -p "$DL/events/$stem"
  out="$DL/events/$stem/$(printf '%04d' "$file_index")_${sevir_id}.vil.u8"
  fetch_range "$BASE_URL/${KEY[$stem]}" "$start" "$end" "${SIZE[$stem]}" "${ETAG[$stem]}" "$out"
  "${HELPER[@]}" check-event "${COMMON[@]}" --sevir-id "$sevir_id" \
    || { rm -f "$out" "$out.hdr"; echo "FATAL: event $sevir_id failed semantic validation" >&2; exit 1; }
  event_count=$((event_count + 1))
  event_bytes=$((event_bytes + EVENT_BYTES))
done 3< "$RECIPE_DIR/events.tsv"
[ "$event_count" = 60 ] || { echo "FATAL: expected 60 events, fetched $event_count" >&2; exit 1; }

total_bytes="$(du -sb "$DL" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID events=$event_count event_bytes=$event_bytes download_dir_bytes=$total_bytes"
