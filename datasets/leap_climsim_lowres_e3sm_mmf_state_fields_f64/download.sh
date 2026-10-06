#!/usr/bin/env bash
# Fetch, for each of the 825 pinned ClimSim low-res E3SM-MMF input files, the
# 4,096-byte CDF-5 header prefix and the exact `state_t` byte range declared
# by that file's own header (HTTP Range requests against the pinned
# revision). Every response is checked for 206 + exact Content-Range, the
# pinned LFS sha256 (X-Linked-Etag) and xet hash (CDN ETag); every header is
# parsed and its dims, types, offsets and in-file timestamp checked; every
# state_t payload is decoded and checked for finite, physically plausible,
# non-constant, non-duplicated values.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="leap_climsim_lowres_e3sm_mmf_state_fields_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
REVISION="bab82a2ebdc750a0134ddcd0d5813867b92eed2a"
HF="https://huggingface.co"
API_INFO_URL="$HF/api/datasets/LEAP/ClimSim_low-res/revision/$REVISION?expand%5B%5D=cardData&expand%5B%5D=sha&expand%5B%5D=gated&expand%5B%5D=private&expand%5B%5D=disabled"
README_URL="$HF/datasets/LEAP/ClimSim_low-res/resolve/$REVISION/README.md"
PATHS_INFO_URL="$HF/api/datasets/LEAP/ClimSim_low-res/paths-info/$REVISION"
RESOLVE_BASE="$HF/datasets/LEAP/ClimSim_low-res/resolve/$REVISION"
SELECTION="$RECIPE_DIR/selection.tsv"
HELPER="$RECIPE_DIR/scripts/climsim.py"
HEAD_BYTES=4096
UA="openzl-public-datasets-climsim/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/heads" "$DOWNLOAD_DIR/state_t" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/heads" "$DOWNLOAD_DIR/state_t" "$DOWNLOAD_DIR/canary"
  rm -f "$DOWNLOAD_DIR/state_t_ranges.tsv" "$DOWNLOAD_DIR/DOWNLOAD_OK"
  mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/heads" "$DOWNLOAD_DIR/state_t"
fi
rm -f "$DOWNLOAD_DIR/DOWNLOAD_OK"

python3 "$RECIPE_DIR/scripts/selftest_cdf5.py"

small_get() {  # url output
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
    --max-filesize 20000000 --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. Identity, access and license of the pinned revision.
small_get "$API_INFO_URL" "$DOWNLOAD_DIR/meta/api_info.json"
small_get "$README_URL" "$DOWNLOAD_DIR/meta/README.md"
python3 "$HELPER" check-meta --api-info "$DOWNLOAD_DIR/meta/api_info.json" --readme "$DOWNLOAD_DIR/meta/README.md"

# 2. Every pinned path still exists at the revision with the pinned size,
#    LFS sha256 and xet hash (batched paths-info POSTs).
rm -f "$DOWNLOAD_DIR/meta"/paths_info_*.json "$DOWNLOAD_DIR/meta"/batch_*
tail -n +2 "$SELECTION" | cut -f2 > "$DOWNLOAD_DIR/meta/selected_paths.txt"
split -l 100 -d -a 3 "$DOWNLOAD_DIR/meta/selected_paths.txt" "$DOWNLOAD_DIR/meta/batch_"
for batch in "$DOWNLOAD_DIR/meta"/batch_[0-9][0-9][0-9]; do
  n="${batch##*_}"
  sed -e 's#/#%2F#g' -e 's#^#paths=#' "$batch" | paste -sd '&' - | tr -d '\n' > "$batch.form"
  rm -f "$DOWNLOAD_DIR/meta/paths_info_$n.json.part"
  curl --fail --silent --show-error --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
    --user-agent "$UA" -X POST --data "@$batch.form" \
    --output "$DOWNLOAD_DIR/meta/paths_info_$n.json.part" "$PATHS_INFO_URL"
  mv "$DOWNLOAD_DIR/meta/paths_info_$n.json.part" "$DOWNLOAD_DIR/meta/paths_info_$n.json"
  sleep 0.5
done
python3 "$HELPER" check-paths --selection "$SELECTION" "$DOWNLOAD_DIR/meta"/paths_info_*.json

# Range fetch with resume-by-file: a finished range is kept only when its
# size is exact and its header dump exists; validation passes re-check all.
fetch_range() {  # repo_path start end output
  local url="$RESOLVE_BASE/$1" start="$2" end="$3" out="$4"
  local want=$((end - start + 1)) attempt got
  if [ -s "$out" ] && [ -s "$out.http" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$want" ]; then
    return 0
  fi
  for attempt in 1 2 3 4; do
    rm -f "$out.part" "$out.http.part"
    if curl --fail --silent --show-error --location --proto-redir =https \
        --retry 8 --retry-all-errors --connect-timeout 30 \
        --speed-limit 1024 --speed-time 60 \
        --max-filesize $((want + 4096)) --range "$start-$end" --user-agent "$UA" \
        --dump-header "$out.http.part" --output "$out.part" "$url"; then
      got="$(wc -c < "$out.part" | tr -d ' ')"
      if [ "$got" = "$want" ]; then
        mv "$out.http.part" "$out.http"
        mv "$out.part" "$out"
        sleep 0.15
        return 0
      fi
      echo "WARN: $1 range $start-$end returned $got bytes (want $want); attempt $attempt" >&2
    else
      echo "WARN: curl failed for $1 range $start-$end; attempt $attempt" >&2
    fi
    sleep 60
  done
  echo "FATAL: could not fetch $1 range $start-$end" >&2
  return 1
}

# 3. Header prefixes.
count=0
while IFS=$'\t' read -r ordinal path _rest; do
  [ "$ordinal" = "ordinal" ] && continue
  stem="$(basename "$path" .nc)"
  fetch_range "$path" 0 $((HEAD_BYTES - 1)) "$DOWNLOAD_DIR/heads/$stem.head"
  count=$((count + 1))
  if [ $((count % 100)) -eq 0 ]; then echo "[$(date -Is)] headers fetched: $count"; fi
done < "$SELECTION"
echo "[$(date -Is)] headers fetched: $count"
python3 "$HELPER" validate-heads --selection "$SELECTION" --download-dir "$DOWNLOAD_DIR" \
  --plan "$DOWNLOAD_DIR/state_t_ranges.tsv"

# 4. state_t ranges, offsets taken from each file's own parsed header.
count=0
while IFS=$'\t' read -r ordinal path start end; do
  stem="$(basename "$path" .nc)"
  fetch_range "$path" "$start" "$end" "$DOWNLOAD_DIR/state_t/$stem.state_t.be"
  count=$((count + 1))
  if [ $((count % 100)) -eq 0 ]; then echo "[$(date -Is)] state_t ranges fetched: $count"; fi
done < "$DOWNLOAD_DIR/state_t_ranges.tsv"
echo "[$(date -Is)] state_t ranges fetched: $count"
python3 "$HELPER" validate-data --selection "$SELECTION" --download-dir "$DOWNLOAD_DIR" \
  --plan "$DOWNLOAD_DIR/state_t_ranges.tsv"

# 5. Three whole-file canaries (first and last selected file, plus ordinal
#    759, the one field with a model-top hot spot of 663.6 K; 1,897,632 bytes
#    each): sha256 must equal the pinned LFS oid and the range-fetched bytes
#    must equal the same slices of the verified whole file.
mkdir -p "$DOWNLOAD_DIR/canary"
for ordinal in 0 759 824; do
  path="$(awk -F'\t' -v o="$ordinal" '$1 == o {print $2}' "$SELECTION")"
  out="$DOWNLOAD_DIR/canary/$(basename "$path")"
  if [ ! -s "$out" ] || [ "$(wc -c < "$out" | tr -d ' ')" != "1897632" ]; then
    rm -f "$out"
    if [ -s "$out.part" ] && [ "$(wc -c < "$out.part" | tr -d ' ')" -ge 1897632 ]; then
      rm -f "$out.part"
    fi
    curl --fail --silent --show-error --location --proto-redir =https -C - \
      --retry 8 --retry-all-errors --connect-timeout 30 \
      --speed-limit 1024 --speed-time 120 --max-filesize 1901728 \
      --user-agent "$UA" --output "$out.part" "$RESOLVE_BASE/$path"
    mv "$out.part" "$out"
  fi
done
python3 "$HELPER" check-canaries --selection "$SELECTION" --download-dir "$DOWNLOAD_DIR" \
  --plan "$DOWNLOAD_DIR/state_t_ranges.tsv"

date -Is > "$DOWNLOAD_DIR/DOWNLOAD_OK"
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
