#!/usr/bin/env bash
# Fetch the 150 pinned GSE290585 MM285 IDAT.gz files (first 75 GSMs: Grn+Red)
# plus three small metadata files, then reject semantically invalid payloads.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ncbi_geo_mm285_methylation_idat_mean_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
IDAT_DIR="$DOWNLOAD_DIR/idat"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PINS="$RECIPE_DIR/scripts/pinned_files.tsv"
HELPER="$RECIPE_DIR/scripts/mm285_idat.py"
NCBI_FTP="https://ftp.ncbi.nlm.nih.gov"
GEO="$NCBI_FTP/geo"
SERIES_URL="$GEO/series/GSE290nnn/GSE290585"
UA="openzl-public-datasets-mm285-idat/1.0"
EXPECTED_FILES=150
EXPECTED_IDAT_BYTES=400141383

mkdir -p "$DOWNLOAD_DIR" "$IDAT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$HELPER" selftest

# Small metadata documents: always re-fetched (a few KB) so the license and
# listing checks run against the live upstream text.
fetch_small() {
  local url="$1" out="$2"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 300 --max-filesize 20000000 \
    --user-agent "$UA" --output "$out.part" "$url"
  mv "$out.part" "$out"
  echo "fetched $(basename "$out") bytes=$(wc -c < "$out" | tr -d ' ') sha256=$(sha256sum "$out" | cut -d' ' -f1)"
}

fetch_small "$NCBI_FTP/README.ftp" "$DOWNLOAD_DIR/README.ftp"
python3 "$HELPER" check-license --readme "$DOWNLOAD_DIR/README.ftp"

fetch_small "$SERIES_URL/suppl/filelist.txt" "$DOWNLOAD_DIR/filelist.txt"
python3 "$HELPER" check-filelist --filelist "$DOWNLOAD_DIR/filelist.txt" --pins "$PINS"

fetch_small "$SERIES_URL/matrix/GSE290585_series_matrix.txt.gz" "$DOWNLOAD_DIR/GSE290585_series_matrix.txt.gz"
gzip -t "$DOWNLOAD_DIR/GSE290585_series_matrix.txt.gz"
python3 "$HELPER" check-matrix --matrix "$DOWNLOAD_DIR/GSE290585_series_matrix.txt.gz" --pins "$PINS"

file_size() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

# Resumable, stall-bounded fetch of one pinned IDAT.gz (no --max-time).
fetch_idat() {
  local url="$1" out="$2" expected="$3"
  local part="$out.part" have attempt rc
  if [ -f "$out" ]; then
    have="$(file_size "$out")"
    if [ "$have" = "$expected" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
      CACHED=$((CACHED + 1))
      return 0
    fi
    echo "refetch $(basename "$out"): local bytes=$have pinned=$expected"
    rm -f "$out"
  fi
  if [ "$(file_size "$part")" -gt "$expected" ]; then
    rm -f "$part"
  fi
  for attempt in 1 2 3 4 5; do
    if [ "$(file_size "$part")" = "$expected" ]; then
      break
    fi
    rc=0
    curl --fail --location --continue-at - --silent --show-error \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$url" || rc=$?
    if [ "$rc" != 0 ]; then
      echo "curl attempt=$attempt rc=$rc url=$url partial_bytes=$(file_size "$part")"
      if [ "$(file_size "$part")" -gt "$expected" ]; then
        rm -f "$part"
      fi
      sleep 5
    fi
  done
  have="$(file_size "$part")"
  if [ "$have" != "$expected" ]; then
    echo "FATAL: $(basename "$out") size mismatch after retries: expected=$expected got=$have" >&2
    exit 1
  fi
  mv "$part" "$out"
  FETCHED=$((FETCHED + 1))
}

CACHED=0
FETCHED=0
PINNED=0
PINNED_BYTES=0
while IFS=$'\t' read -r gsm name size barcode position channel _sha256 <&3; do
  if [ "$gsm" = "gsm" ]; then
    continue
  fi
  case "$name" in
    "${gsm}_${barcode}_${position}_${channel}.idat.gz") ;;
    *) echo "FATAL: malformed pin row: $gsm $name" >&2; exit 1 ;;
  esac
  url="$GEO/samples/${gsm%???}nnn/$gsm/suppl/$name"
  fetch_idat "$url" "$IDAT_DIR/$name" "$size"
  PINNED=$((PINNED + 1))
  PINNED_BYTES=$((PINNED_BYTES + size))
done 3< "$PINS"

if [ "$PINNED" != "$EXPECTED_FILES" ] || [ "$PINNED_BYTES" != "$EXPECTED_IDAT_BYTES" ]; then
  echo "FATAL: pin list covers files=$PINNED bytes=$PINNED_BYTES; expected $EXPECTED_FILES / $EXPECTED_IDAT_BYTES" >&2
  exit 1
fi
echo "idat_transfer=ok pinned=$PINNED fetched=$FETCHED cached=$CACHED bytes=$PINNED_BYTES"

# Semantic validation: gzip integrity, IDAT v3 magic/version, N=361821,
# field-offset geometry, barcode/position vs file name, chip type, a single
# IlluminaID order across all files, Grn != Red per array. Files whose gzip
# stream is corrupt are deleted so a re-run refetches them.
python3 "$HELPER" check-idats --idat-dir "$IDAT_DIR" --pins "$PINS" --delete-corrupt

echo "[$(date -Is)] download done dataset=$DATASET_ID"
