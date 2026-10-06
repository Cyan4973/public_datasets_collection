#!/usr/bin/env bash
# Download the 150 pinned summer_vv_COH12 tiles listed in sources.tsv.
# Each file is fetched with resumable curl into a .part file, then checked for
# exact size, S3 ETag MD5, and the pinned GeoTIFF layout (classic LE TIFF,
# 1200x1200, uint8, LZW, 200 strips of 6 rows, nodata "0", tile-origin
# tiepoint) before it is renamed into place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="earthbigdata_s1_global_coherence_vv_coh12_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TILE_DIR="$DOWNLOAD_DIR/tiles"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECKER="$RECIPE_DIR/scripts/s1coh.py"
UA="openzl-public-datasets-earthbigdata-coherence-download/1.0"
EXPECTED_FILES=150
EXPECTED_BYTES=161185497

mkdir -p "$TILE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Liveness: one-byte range GET on the first pinned object.
first_url="$(awk -F'\t' 'NR==2{print $6}' "$SOURCES")"
code="$(curl --globoff --silent --show-error --location --range 0-0 --max-time 60 \
  --retry 5 --retry-delay 5 --user-agent "$UA" --output /dev/null --write-out '%{http_code}' "$first_url")"
[[ "$code" = "206" || "$code" = "200" ]] || { echo "liveness check failed http=$code url=$first_url" >&2; exit 1; }
echo "liveness ok http=$code"

validate() {  # path tile size md5 -> 0 if the local file matches the pin
  local path="$1" tile="$2" size="$3" md5="$4"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" = "$size" ]] || { echo "size mismatch tile=$tile got=$(stat -c %s "$path") want=$size" >&2; return 1; }
  [[ "$(md5sum "$path" | awk '{print $1}')" = "$md5" ]] || { echo "md5 mismatch tile=$tile" >&2; return 1; }
  python3 "$CHECKER" check-header "$path" "$tile" >/dev/null || { echo "TIFF layout check failed tile=$tile" >&2; return 1; }
  return 0
}

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'tile\tfilename\tsize_bytes\tmd5\tsha256\turl\n' > "$plan.tmp"
count=0
bytes=0
fetched=0
while IFS=$'\t' read -r tile filename size md5 last_modified url; do
  [[ "$tile" != "tile" ]] || continue
  target="$TILE_DIR/$filename"
  if validate "$target" "$tile" "$size" "$md5" 2>/dev/null; then
    :
  else
    rm -f "$target"
    part="$target.part"
    ok=0
    for attempt in 1 2 3 4 5; do
      if [[ -f "$part" ]]; then
        psize="$(stat -c %s "$part")"
        if (( psize > size )); then rm -f "$part"; fi
      fi
      if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
        curl --globoff --fail --silent --show-error --location -C - \
          --retry 10 --retry-delay 5 --retry-all-errors \
          --speed-limit 1024 --speed-time 120 --max-filesize 5000000 \
          --user-agent "$UA" --output "$part" "$url" \
          || { echo "curl failed tile=$tile attempt=$attempt" >&2; sleep 5; continue; }
      fi
      if validate "$part" "$tile" "$size" "$md5"; then
        mv "$part" "$target"
        ok=1
        break
      fi
      echo "invalid payload tile=$tile attempt=$attempt; discarding partial file" >&2
      rm -f "$part"
    done
    (( ok == 1 )) || { echo "giving up on tile=$tile" >&2; exit 1; }
    fetched=$((fetched + 1))
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$tile" "$filename" "$size" "$md5" "$sha" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
  if (( count % 25 == 0 )); then echo "progress files=$count bytes=$bytes fetched_this_run=$fetched"; fi
done < "$SOURCES"

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "unexpected file count $count (want $EXPECTED_FILES)" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes (want $EXPECTED_BYTES)" >&2; exit 1; }
stray="$(find "$TILE_DIR" -type f ! -name '*_summer_vv_COH12.tif' | wc -l)"
[[ "$stray" = "0" ]] || { echo "unexpected extra files in $TILE_DIR" >&2; exit 1; }
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_this_run=$fetched"
