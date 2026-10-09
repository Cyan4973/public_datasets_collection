#!/usr/bin/env bash
# Fetch the 24 pinned LiCSAR *.geo.unw.tif rasters listed in sources.tsv.
# Resumable (curl -C - into .part), stall-bounded (--speed-limit/--speed-time),
# then size-checked and fully decoded/validated before being accepted.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="comet_licsar_s1_unwrapped_phase_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/rasters"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-licsar-download/1.0"
EXPECTED_COUNT=24
EXPECTED_BYTES=776518900

mkdir -p "$RASTER_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/licsar_unw.py" selftest

PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'frame\tpair\tfilename\tsize_bytes\tsha256\turl\n' > "$PLAN.tmp"

count=0
bytes=0
while IFS=$'\t' read -r frame pair filename size_bytes last_modified width height compression predictor probe_zf sha256 url; do
  [[ "$frame" != "frame" ]] || continue
  case "$url" in
    https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products.public/*/"$frame"/interferograms/"$pair"/"$filename") ;;
    *) echo "unexpected url for $filename: $url" >&2; exit 1 ;;
  esac
  [[ "$filename" == *.geo.unw.tif ]] || { echo "not a geo.unw.tif: $filename" >&2; exit 1; }
  target="$RASTER_DIR/$filename"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size_bytes" ]]; then
    echo "cache_hit $filename bytes=$size_bytes"
  else
    rm -f "$target"
    part="$target.part"
    have=0
    [[ -f "$part" ]] && have="$(stat -c %s "$part")"
    if (( have > size_bytes )); then
      echo "oversized partial $part ($have > $size_bytes); restarting"
      rm -f "$part"
      have=0
    fi
    if (( have < size_bytes )); then
      echo "fetch $frame/$pair bytes=$size_bytes resume_from=$have"
      curl --globoff --fail --silent --show-error --location \
        -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$part" "$url"
    fi
    actual="$(stat -c %s "$part")"
    [[ "$actual" == "$size_bytes" ]] || {
      echo "size mismatch $filename expected=$size_bytes actual=$actual" >&2
      exit 1
    }
    mv "$part" "$target"
  fi
  actual_sha="$(sha256sum "$target" | awk '{print $1}')"
  # sources.tsv uses "-" for a not-yet-pinned hash (bash read collapses empty
  # tab-separated fields, so no column may be empty)
  if [[ "$sha256" != "-" && "$sha256" != "$actual_sha" ]]; then
    echo "sha256 mismatch $filename expected=$sha256 actual=$actual_sha" >&2
    exit 1
  fi
  # semantic validation: TIFF layout, float32 single band, pinned raster size,
  # every strip decodes, finite values, zero/no-data fraction <= 0.5, non-constant
  python3 -I "$RECIPE_DIR/scripts/licsar_unw.py" check "$target" --width "$width" --height "$height"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$frame" "$pair" "$filename" "$size_bytes" "$actual_sha" "$url" >> "$PLAN.tmp"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_COUNT" ]] || { echo "unexpected raster count $count" >&2; exit 1; }
[[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "unexpected total bytes $bytes" >&2; exit 1; }
mv "$PLAN.tmp" "$PLAN"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
