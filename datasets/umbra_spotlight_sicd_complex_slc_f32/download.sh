#!/usr/bin/env bash
# Fetch the 10 pinned Umbra Open Data spotlight SICD NITF products
# (978,017,309 bytes total) anonymously from the public AWS Open Data bucket
# umbra-open-data-catalog, then reject anything that is not the pinned,
# structurally conforming SICD (size, S3 multipart ETag, NITF/SICD layout,
# processor 0.6.x regime, finite non-degenerate I/Q pixels).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umbra_spotlight_sicd_complex_slc_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Column positions in sources.tsv (header-checked so a reordering fails loudly).
header="$(head -n1 "$SOURCES")"
[[ "$(cut -f1,2,4,5 <<<"$header")" == $'ordinal\tcore\tsize\tetag' && "$(cut -f28 <<<"$header")" == "url" ]] \
  || { echo "unexpected sources.tsv header" >&2; exit 1; }

# Liveness check: one-byte range GET of the first object.
first_url="$(awk -F'\t' 'NR==2 {print $28}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 --output /dev/null "$first_url"

while IFS=$'\t' read -r ordinal core size etag url; do
  [[ "$ordinal" == "ordinal" ]] && continue
  target="$DOWNLOAD_DIR/${core}_SICD.nitf"
  part="$target.part"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit ordinal=$ordinal core=$core bytes=$size"
    continue
  fi
  rm -f "$target"
  if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then rm -f "$part"; fi
  attempt=0
  while [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; do
    attempt=$((attempt + 1))
    if (( attempt > 10 )); then echo "giving up on $core" >&2; exit 1; fi
    echo "fetch ordinal=$ordinal core=$core bytes=$size attempt=$attempt"
    curl --fail --location --silent --show-error -C - --retry 10 --retry-delay 5 \
      --speed-limit 1024 --speed-time 120 --max-filesize 120000000 \
      --output "$part" "$url" || sleep 5
  done
  [[ "$(stat -c %s "$part")" == "$size" ]] || { echo "size mismatch: $core" >&2; rm -f "$part"; exit 1; }
  mv "$part" "$target"
  echo "fetched ordinal=$ordinal core=$core bytes=$size"
done < <(cut -f1,2,4,5,28 "$SOURCES")

# Semantic validation of every file: exact size, S3 multipart ETag recomputed
# with the pinned part size, NITF 2.1 header/segment table, image subheader
# (PVTYPE R, ABPP/NBPP 32, IC NC, NBANDS 2 = I,Q, IMODE P, one block),
# SICD 1.2.1 XML DES (RE32F_IM32F, SPOTLIGHT, MONOSTATIC, PFA, X band,
# processor 0.6.x, NumRows/NumCols == NITF and == pinned), image bytes ==
# rows*cols*8, all pixels finite, non-constant, not zero-dominated.
python3 -I "$RECIPE_DIR/scripts/recipe.py" validate --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR"

du -sb "$DOWNLOAD_DIR" | awk '{print "download_dir_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
