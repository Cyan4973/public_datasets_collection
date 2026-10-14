#!/usr/bin/env bash
# Fetch the pinned NOAA NEFSC / ONMS Stellwagen Bank MARU array recordings
# (DOI 10.25921/g3vk-v972) from the public NODD Google Cloud bucket
# gs://noaa-passive-bioacoustic (anonymous HTTPS, storage.googleapis.com):
#   1. one-byte range GET on the first pinned AIFF (liveness),
#   2. the NCEI ISO 19115 record NEFSC_SBNMS_Raw_Data (DOI, citation, and
#      no use constraints beyond liability disclaimers + citation),
#   3. 7 deployment metadata JSONs pinned in meta.tsv (size + GCS md5;
#      2 kHz / 12-bit sampling, 10 channels, publisher channel quality),
#   4. 14 AIFF files pinned in files.tsv (36,000,054 bytes each, GCS md5),
#      resumable, each validated for size, md5 and the FORM/AIFF COMM+SSND
#      layout (10 channels, 1,800,000 frames, 16 bits, 2000 Hz).
# Total about 504.2 MB.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_nefsc_sbnms_maru_hydrophone_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
OBJ="https://storage.googleapis.com/noaa-passive-bioacoustic"
ISO_URL="https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncei.pad%3ANEFSC_SBNMS_Raw_Data/xml"
UA="openzl-public-datasets-sbnms-maru/1.0"
PY=(python3 -I "$RECIPE_DIR/scripts/maru.py")

mkdir -p "$DOWNLOAD_DIR/audio" "$DOWNLOAD_DIR/metadata" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

size_of() { if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi; }
curl_common=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

"${PY[@]}" selftest

# 1. liveness
first_obj="$("${PY[@]}" list-files | head -1 | cut -d' ' -f1)"
echo "[$(date -Is)] step=liveness object=$first_obj"
probe="$DOWNLOAD_DIR/.liveness"
curl "${curl_common[@]}" --max-time 60 --range 0-0 --output "$probe" "$OBJ/$first_obj"
if [ "$(head -c1 "$probe")" != "F" ]; then
  echo "FATAL: first byte of $first_obj is not 'F' (FORM)" >&2
  exit 1
fi
rm -f "$probe"

# 2. NCEI ISO record (license / citation evidence); not byte-pinned
#    (geoportal re-serialises), validated by content.
echo "[$(date -Is)] step=iso_record"
ISO="$DOWNLOAD_DIR/NEFSC_SBNMS_Raw_Data.iso.xml"
curl "${curl_common[@]}" --max-time 300 --max-filesize 5000000 --output "$ISO.part" "$ISO_URL"
mv "$ISO.part" "$ISO"
"${PY[@]}" check-iso --file "$ISO"

# 3. deployment metadata JSONs
echo "[$(date -Is)] step=metadata"
while read -r obj size; do
  dest="$DOWNLOAD_DIR/metadata/$(basename "$obj")"
  if [ "$(size_of "$dest")" != "$size" ]; then
    curl "${curl_common[@]}" --max-time 300 --max-filesize 1000000 --output "$dest.part" "$OBJ/$obj"
    mv "$dest.part" "$dest"
  fi
done < <("${PY[@]}" list-meta)
"${PY[@]}" check-meta --dir "$DOWNLOAD_DIR/metadata"

# 4. AIFF recordings (resumable .part, then size + md5 + header check)
echo "[$(date -Is)] step=audio"
i=0
while read -r obj size; do
  i=$((i + 1))
  name="$(basename "$obj")"
  dest="$DOWNLOAD_DIR/audio/$name"
  if [ -f "$dest" ]; then
    if "${PY[@]}" check-aiff --file "$dest" >/dev/null 2>&1; then
      echo "[$(date -Is)] [$i] present and valid: $name"
      continue
    fi
    echo "[$(date -Is)] [$i] existing $name failed validation; refetching"
    rm -f "$dest"
  fi
  part="$dest.part"
  if [ "$(size_of "$part")" -gt "$size" ]; then rm -f "$part"; fi
  echo "[$(date -Is)] [$i] fetch $name ($size bytes, have $(size_of "$part"))"
  if [ "$(size_of "$part")" != "$size" ]; then
    curl "${curl_common[@]}" -C - --max-filesize $((size + 4096)) --output "$part" "$OBJ/$obj"
  fi
  if [ "$(size_of "$part")" != "$size" ]; then
    echo "FATAL: $name: got $(size_of "$part") bytes, expected $size" >&2
    exit 1
  fi
  if ! "${PY[@]}" check-aiff --file "$part" --name "$name"; then
    echo "FATAL: $name failed md5/AIFF validation; removing the partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$dest"
done < <("${PY[@]}" list-files)

n_ok=$(ls "$DOWNLOAD_DIR"/audio/*.aif | wc -l | tr -d ' ')
n_pin=$("${PY[@]}" list-files | wc -l | tr -d ' ')
if [ "$n_ok" != "$n_pin" ]; then
  echo "FATAL: $n_ok AIFF files present, $n_pin pinned" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$n_ok bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
