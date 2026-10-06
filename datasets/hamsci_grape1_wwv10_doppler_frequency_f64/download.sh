#!/usr/bin/env bash
# Download the 920 pinned Grape V1 (G1) WWV10 station-day files from Zenodo
# record 6590283, verify size + Zenodo md5 per file, then semantically
# validate every payload. Network I/O is curl only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hamsci_grape1_wwv10_doppler_frequency_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILE_DIR="$DOWNLOAD_DIR/csv_gz"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
RECORD_URL="https://zenodo.org/api/records/6590283"
EXPECTED_FILES=920
EXPECTED_BYTES=614396212
PACE_SECONDS="${GRAPE_PACE_SECONDS:-1}"
UA="openzl-public-datasets-hamsci-grape1-wwv10/1.0"

mkdir -p "$FILE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# 1. Live record metadata: identity, CC-BY-4.0 license, open access, and the
#    exact size/md5 of every pinned file.
record="$DOWNLOAD_DIR/record_6590283.json"
rm -f "$record.part"
curl --fail --silent --show-error --location \
  --retry 8 --retry-delay 15 --retry-all-errors --connect-timeout 30 \
  --max-time 300 --max-filesize 20000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$record.part" "$RECORD_URL"
mv "$record.part" "$record"
python3 "$RECIPE_DIR/scripts/grape_sources.py" check "$record" "$SOURCES"

# 2. Per-file fetch with resumable .part files, pacing, and md5 checks.
file_ok() {  # <path> <size> <md5>
  [[ -f "$1" ]] && [[ "$(stat -c %s "$1")" = "$2" ]] \
    && printf '%s  %s\n' "$3" "$1" | md5sum --check --status
}

count=0
bytes=0
fetched=0
cached=0
while IFS=$'\t' read -r order key node receiver grid beacon start size md5 url status; do
  [[ "$order" != "sample_order" ]] || continue
  [[ "$receiver" = "G1" && "$beacon" = "WWV10" ]] || { echo "unexpected source row: $key" >&2; exit 1; }
  target="$FILE_DIR/$key"
  if file_ok "$target" "$size" "$md5"; then
    cached=$((cached + 1))
  else
    rm -f "$target"
    attempt=1
    while :; do
      if file_ok "$target.part" "$size" "$md5"; then
        mv "$target.part" "$target"  # completed by an interrupted earlier run
        break
      fi
      if [[ -f "$target.part" ]] && [[ "$(stat -c %s "$target.part")" -ge "$size" ]]; then
        rm -f "$target.part"  # full-size but wrong md5, or oversized: cannot resume
      fi
      if curl --fail --silent --show-error --location --globoff \
          --continue-at - --retry 10 --retry-delay 20 --retry-all-errors \
          --connect-timeout 30 --speed-limit 1024 --speed-time 120 --max-time 900 \
          --max-filesize 5000000 --user-agent "$UA" \
          --output "$target.part" "$url" \
        && file_ok "$target.part" "$size" "$md5"; then
        mv "$target.part" "$target"
        break
      fi
      echo "fetch attempt $attempt failed or md5 mismatch: $key" >&2
      if [[ "$attempt" -ge 4 ]]; then
        echo "FATAL: giving up on $key after $attempt attempts" >&2
        exit 1
      fi
      attempt=$((attempt + 1))
      sleep 60
    done
    fetched=$((fetched + 1))
    echo "fetched order=$order bytes=$size key=$key"
    sleep "$PACE_SECONDS"
  fi
  count=$((count + 1))
  bytes=$((bytes + size))
done < "$SOURCES"

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "FATAL: source count $count != $EXPECTED_FILES" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "FATAL: source bytes $bytes != $EXPECTED_BYTES" >&2; exit 1; }
echo "files=$count bytes=$bytes fetched=$fetched cached=$cached"

# 3. Semantic validation of every payload (gzip, identity line, beacon, columns).
python3 "$RECIPE_DIR/scripts/grape_sources.py" payloads "$SOURCES" "$FILE_DIR" "$DOWNLOAD_DIR/payload_summary.tsv"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
