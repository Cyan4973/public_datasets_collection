#!/usr/bin/env bash
# Fetch only the PRIMARY + IMAGE prefix (first 16,675,200 bytes) of the 30 SPHEREx QR3
# Level-2 detector-1 spectral-image FITS files pinned in sources.tsv, via HTTP Range GETs
# guarded by If-Match on the pinned S3 ETag, plus the license / acknowledgement pages as
# rights evidence. The FLAGS, VARIANCE, ZODI, PSF and WCS-WAVE extensions are never fetched.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="irsa_spherex_qr3_l2_spectral_image_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
PREFIX_DIR="$DOWNLOAD_DIR/image_prefix"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
EXPECTED_FILES=30
EXPECTED_BYTES=500256000
LICENSE_URL="https://science.data.nasa.gov/about/license"
IRSA_URL="https://irsa.ipac.caltech.edu/Missions/spherex.html"
UA="openzl-public-datasets-spherex-qr3/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$PREFIX_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Rights evidence (best effort on transport; a fetched page with changed terms is fatal).
fetch_evidence() {
  local url="$1" out="$2" mode="$3"
  if curl --fail --silent --show-error --location --retry 3 --retry-delay 3 \
    --max-time 120 --max-filesize 5000000 --user-agent "$UA" --output "$out.part" "$url"; then
    mv "$out.part" "$out"
    python3 "$CHECK" "$mode" "$out"
  else
    rm -f "$out.part"
    echo "WARNING evidence_unavailable url=$url (transport failure); rights rest on the README citation"
  fi
}
fetch_evidence "$LICENSE_URL" "$DOWNLOAD_DIR/evidence/nasa_science_data_license.html" evidence-license
fetch_evidence "$IRSA_URL" "$DOWNLOAD_DIR/evidence/irsa_spherex.html" evidence-irsa

# Liveness: one-byte range GET on the first pinned object.
first_url="$(awk -F'\t' 'NR==2 {print $3}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'name\tprefix_bytes\tetag\tsha256\n' > "$plan.part"
count=0
bytes=0
fetched=0
while IFS='|' read -r name url etag prefix_bytes; do
  target="$PREFIX_DIR/${name%.fits}.primary_image.fits"
  sha=""
  if [[ -s "$target" ]]; then
    if [[ "$(stat -c %s "$target")" != "$prefix_bytes" ]] \
      || ! sha="$(python3 "$CHECK" prefix "$target" "$SOURCES" "$name" </dev/null)"; then
      echo "stale_or_invalid_cache file=$name; refetching"
      rm -f "$target"
    else
      echo "cached file=$name sha256=$sha"
    fi
  fi
  if [[ ! -s "$target" ]]; then
    part="$target.part"
    chunk="$target.chunk"
    [[ -f "$part" ]] || : > "$part"
    if (( $(stat -c %s "$part") > prefix_bytes )); then : > "$part"; fi
    # Resumable range fetch: each pass requests the missing tail of the prefix; whatever
    # arrives (even from a failed transfer) is a contiguous continuation and is appended.
    # If-Match pins the S3 object (ETag) so a reprocessed object yields HTTP 412, not mixed bytes.
    attempt=0
    while (( $(stat -c %s "$part") < prefix_bytes )); do
      attempt=$((attempt + 1))
      if (( attempt > 8 )); then
        echo "FATAL could not complete file=$name after $((attempt - 1)) passes" >&2
        exit 1
      fi
      have="$(stat -c %s "$part")"
      rm -f "$chunk"
      if ! curl --fail --silent --show-error --location \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --range "$have-$((prefix_bytes - 1))" --header "If-Match: \"$etag\"" \
        --user-agent "$UA" --output "$chunk" "$url" </dev/null; then
        echo "WARNING partial transfer file=$name pass=$attempt; resuming"
      fi
      if [[ -s "$chunk" ]]; then
        if (( have + $(stat -c %s "$chunk") > prefix_bytes )); then
          echo "FATAL server returned more than the requested range file=$name" >&2
          rm -f "$chunk" "$part"
          exit 1
        fi
        cat "$chunk" >> "$part"
      fi
      rm -f "$chunk"
    done
    if ! sha="$(python3 "$CHECK" prefix "$part" "$SOURCES" "$name" </dev/null)"; then
      echo "FATAL semantic validation failed file=$name" >&2
      rm -f "$part"
      exit 1
    fi
    mv "$part" "$target"
    fetched=$((fetched + 1))
    echo "fetched file=$name bytes=$prefix_bytes sha256=$sha"
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$prefix_bytes" "$etag" "$sha" >> "$plan.part"
  count=$((count + 1))
  bytes=$((bytes + prefix_bytes))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $3 "|" $4 "|" $8}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FILES" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL unexpected selection totals files=$count bytes=$bytes (expected $EXPECTED_FILES / $EXPECTED_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_now=$fetched"
