#!/usr/bin/env bash
# Fetch the 12 pinned JWST NIRCam short-wave uncal FITS files listed in sources.tsv from the
# anonymous MAST public bucket (stpubdata), version-pinned, and best-effort the MAST
# data-use policy page as rights evidence.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mast_jwst_nircam_sw_uncal_ramps_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
UNCAL_DIR="$DOWNLOAD_DIR/uncal"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
EXPECTED_FILES=12
EXPECTED_BYTES=906681600
EVIDENCE_URL="https://archive.stsci.edu/publishing/data-use"
UA="openzl-public-datasets-jwst-nircam-uncal/1.0"

mkdir -p "$UNCAL_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Rights evidence (best effort). archive.stsci.edu has been unreachable from some networks
# (proxy 403 on 2026-10-05), so a transport failure only logs a warning; a page that is
# fetched but no longer carries the public-domain default (or names JWST as copyrighted)
# is fatal.
evidence="$DOWNLOAD_DIR/evidence/mast_data_use.html"
if curl --fail --silent --show-error --location --retry 3 --retry-delay 3 \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
  --output "$evidence.part" "$EVIDENCE_URL"; then
  mv "$evidence.part" "$evidence"
  python3 "$CHECK" evidence "$evidence"
else
  rm -f "$evidence.part"
  echo "WARNING evidence_unavailable url=$EVIDENCE_URL (transport failure); rights rest on the README citation"
fi

# Liveness: one-byte range GET on the first pinned (version-specific) object.
first_url="$(awk -F'\t' 'NR==2 {print $2}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'filename\tsize_bytes\tcrc64nvme\tsha256\n' > "$plan.part"
count=0
bytes=0
fetched=0
while IFS='|' read -r filename url size_bytes crc64; do
  target="$UNCAL_DIR/$filename"
  sha=""
  if [[ -s "$target" ]]; then
    if [[ "$(stat -c %s "$target")" != "$size_bytes" ]] \
      || ! sha="$(python3 "$CHECK" uncal "$target" "$SOURCES" "$filename" </dev/null)"; then
      echo "stale_or_invalid_cache file=$filename; refetching"
      rm -f "$target"
    else
      echo "cached file=$filename sha256=$sha"
    fi
  fi
  if [[ ! -s "$target" ]]; then
    if [[ -s "$target.part" ]] && (( $(stat -c %s "$target.part") > size_bytes )); then
      rm -f "$target.part"
    fi
    # A .part that already has the pinned size (run interrupted before the rename) is
    # validated as-is; resuming it would only draw an HTTP 416.
    if [[ ! -s "$target.part" ]] || (( $(stat -c %s "$target.part") < size_bytes )); then
      curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --max-filesize 80000000 \
        --user-agent "$UA" --output "$target.part" "$url" </dev/null
    fi
    actual="$(stat -c %s "$target.part")"
    if [[ "$actual" != "$size_bytes" ]]; then
      echo "FATAL size mismatch file=$filename expected=$size_bytes actual=$actual" >&2
      rm -f "$target.part"
      exit 1
    fi
    if ! sha="$(python3 "$CHECK" uncal "$target.part" "$SOURCES" "$filename" </dev/null)"; then
      echo "FATAL semantic validation failed file=$filename" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
    fetched=$((fetched + 1))
    echo "fetched file=$filename bytes=$size_bytes crc64nvme=$crc64 sha256=$sha"
  fi
  printf '%s\t%s\t%s\t%s\n' "$filename" "$size_bytes" "$crc64" "$sha" >> "$plan.part"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2 "|" $5 "|" $6}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FILES" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL unexpected selection totals files=$count bytes=$bytes (expected $EXPECTED_FILES / $EXPECTED_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_now=$fetched"
