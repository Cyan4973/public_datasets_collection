#!/usr/bin/env bash
# Fetch the pinned subset of the MIMII valve recordings (6 dB SNR product;
# Hitachi, Zenodo record 3384388 "public 1.0", CC BY-SA 4.0) by HTTP range
# requests against the single 6,915,951,837-byte ZIP64 archive
# 6_dB_valve.zip:
#   1. a one-byte range GET (liveness, range support, pinned archive size),
#   2. the Zenodo record JSON (license cc-by-sa-4.0, file key, size, md5),
#   3. the archive tail [cd_offset, end): central directory + ZIP64 EOCD
#      record + locator + EOCD (492,374 bytes, sha256-pinned),
#   4. the 160 member spans pinned in members.tsv (local header + deflate
#      data, 265,037,035 bytes in total), each validated by Content-Range,
#      local header vs central directory, a full inflate, CRC32, and a
#      RIFF/WAVE EXTENSIBLE PCM 8 ch 16 kHz 16-bit 2,560,000-byte data check.
# The 6.9 GB archive is never downloaded whole.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_mimii_valve_mic_array_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-mimii/1.0"
PY=(python3 "$RECIPE_DIR/scripts/mimii.py")
MAX_PASSES="${MIMII_MAX_PASSES:-8}"
PARALLEL="${MIMII_PARALLEL:-2}"
RECORD_URL="https://zenodo.org/api/records/3384388"
ZIP_URL="https://zenodo.org/api/records/3384388/files/6_dB_valve.zip/content"

mkdir -p "$DOWNLOAD_DIR/members" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

size_of() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

curl_common=(--fail --silent --show-error --location --retry 10 --retry-delay 10 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

read -r TAIL_FIRST TAIL_LAST TAIL_BYTES < <("${PY[@]}" tail-bytes)

# 1. liveness: one-byte range GET; the Content-Range total must equal the
#    pinned archive size.
echo "[$(date -Is)] step=liveness"
probe="$DOWNLOAD_DIR/.liveness"
curl "${curl_common[@]}" --max-filesize 4096 --range 0-0 --dump-header "$probe.hdr" --output "$probe.bin" "$ZIP_URL"
"${PY[@]}" check-range --header "$probe.hdr" --first 0 --last 0
if [ "$(od -An -tx1 -N1 "$probe.bin" | tr -d ' ')" != "50" ]; then
  echo "FATAL: archive does not start with a ZIP local header ('P')" >&2
  exit 1
fi
rm -f "$probe.hdr" "$probe.bin"

# 2. record metadata: license, version and pinned file identity. Not
#    byte-pinned (view/download counters change); validated field by field.
echo "[$(date -Is)] step=record_json"
RECORD_JSON="$DOWNLOAD_DIR/record_3384388.json"
curl "${curl_common[@]}" --max-filesize 2000000 --output "$RECORD_JSON.part" "$RECORD_URL"
mv "$RECORD_JSON.part" "$RECORD_JSON"
"${PY[@]}" check-record --record "$RECORD_JSON"

# 3. archive tail: central directory and (ZIP64) end records.
echo "[$(date -Is)] step=archive_tail range=$TAIL_FIRST-$TAIL_LAST"
TAIL="$DOWNLOAD_DIR/archive_tail.bin"
if [ "$(size_of "$TAIL")" != "$TAIL_BYTES" ]; then
  rm -f "$TAIL" "$TAIL.part" "$TAIL.hdr"
  curl "${curl_common[@]}" --max-filesize $((TAIL_BYTES + 4096)) --range "$TAIL_FIRST-$TAIL_LAST" \
    --dump-header "$TAIL.hdr" --output "$TAIL.part" "$ZIP_URL"
  "${PY[@]}" check-range --header "$TAIL.hdr" --first "$TAIL_FIRST" --last "$TAIL_LAST"
  if [ "$(size_of "$TAIL.part")" != "$TAIL_BYTES" ]; then
    echo "FATAL: archive tail returned $(size_of "$TAIL.part") bytes, expected $TAIL_BYTES" >&2
    rm -f "$TAIL.part" "$TAIL.hdr"
    exit 1
  fi
  mv "$TAIL.part" "$TAIL"
  rm -f "$TAIL.hdr"
fi
# Tail sha256, EOCD/ZIP64 EOCD fields, central-directory parse and a
# re-derivation of the member selection, which must equal members.tsv.
"${PY[@]}" check-metadata --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] metadata_ok license=cc-by-sa-4.0 archive=6_dB_valve.zip"

# 4. member spans: several passes; each pass promotes validated .part files,
#    deletes invalid ones, and refetches whatever is still missing.
export MIMII_DOWNLOAD_DIR="$DOWNLOAD_DIR" MIMII_UA="$UA" MIMII_URL="$ZIP_URL"
PLAN="$DOWNLOAD_DIR/.member_plan.txt"
PENDING_FILE="$DOWNLOAD_DIR/.member_pending"
pass=0
while :; do
  "${PY[@]}" check-members --download-dir "$DOWNLOAD_DIR"
  "${PY[@]}" plan-members --download-dir "$DOWNLOAD_DIR" --plan "$PLAN" --pending-out "$PENDING_FILE"
  pending="$(cat "$PENDING_FILE")"
  if [ "$pending" = "0" ]; then
    break
  fi
  pass=$((pass + 1))
  if [ "$pass" -gt "$MAX_PASSES" ]; then
    echo "FATAL: $pending member spans still missing or invalid after $MAX_PASSES passes" >&2
    exit 1
  fi
  if [ "$pass" -gt 1 ]; then
    echo "[$(date -Is)] waiting 60 s before pass $pass (rate-limit window)"
    sleep 60
  fi
  echo "[$(date -Is)] member fetch pass=$pass pending=$pending parallel=$PARALLEL"
  xargs -r -P "$PARALLEL" -L 1 bash "$RECIPE_DIR/scripts/fetch_span.sh" < "$PLAN"
done
rm -f "$PLAN" "$PENDING_FILE"

"${PY[@]}" check-downloads --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
