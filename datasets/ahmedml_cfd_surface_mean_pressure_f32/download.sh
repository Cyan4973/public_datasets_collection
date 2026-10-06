#!/usr/bin/env bash
# Fetch, for each of the 50 pinned AhmedML boundary VTPs (run_1, run_11, ...,
# run_491 at the pinned HF revision), two HTTP Range slices only:
#   - bytes 0-2047: VTK XML header (VTKFile attributes, NumberOfPolys)
#   - the pMean window [pmean_b64_start - 256, pmean_b64_end + 127]: the
#     complete inline-base64 pMean CellData block with its opening tag and the
#     following static(p)_coeffMean tag (offsets pinned in selection.tsv by
#     discover.sh).
# Every response must be 206 with the exact Content-Range over the pinned file
# size, a CDN ETag equal to the pinned xet hash and an X-Linked-Etag equal to
# the pinned LFS sha256; every window is decoded and its UInt64 prefix, tags
# and values validated. Whole VTPs, volume_*.vtu and slices/ are never fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ahmedml_cfd_surface_mean_pressure_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
REVISION="02688c727cdb8dc8678e28abc6bbbb7e93c5fa15"
HF="https://huggingface.co"
API_INFO_URL="$HF/api/datasets/neashton/ahmedml/revision/$REVISION?expand%5B%5D=cardData&expand%5B%5D=sha&expand%5B%5D=gated&expand%5B%5D=private&expand%5B%5D=disabled"
PATHS_INFO_URL="$HF/api/datasets/neashton/ahmedml/paths-info/$REVISION"
RESOLVE_BASE="$HF/datasets/neashton/ahmedml/resolve/$REVISION"
SELECTION="$RECIPE_DIR/selection.tsv"
HELPER="$RECIPE_DIR/scripts/ahmedml_vtp.py"
HEAD_BYTES=2048
WINDOW_PRE=256
WINDOW_POST=128
UA="openzl-public-datasets-ahmedml/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/heads" "$DOWNLOAD_DIR/pmean"
fi
rm -f "$DOWNLOAD_DIR/DOWNLOAD_OK"
mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/heads" "$DOWNLOAD_DIR/pmean"

python3 "$HELPER" selftest

small_get() {  # url output
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
    --max-filesize 5000000 --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. Identity, access and license of the pinned revision.
small_get "$API_INFO_URL" "$DOWNLOAD_DIR/meta/api_info.json"
small_get "$RESOLVE_BASE/README.md" "$DOWNLOAD_DIR/meta/README.md"
small_get "$RESOLVE_BASE/LICENSE.txt" "$DOWNLOAD_DIR/meta/LICENSE.txt"
python3 "$HELPER" check-meta --api-info "$DOWNLOAD_DIR/meta/api_info.json" \
  --readme "$DOWNLOAD_DIR/meta/README.md" --license "$DOWNLOAD_DIR/meta/LICENSE.txt"

# 2. Every selected VTP still exists at the revision with the pinned size,
#    LFS sha256 and xet hash.
tail -n +2 "$SELECTION" | cut -f2 | sed -e 's#/#%2F#g' -e 's#^#paths=#' | paste -sd '&' - | tr -d '\n' \
  > "$DOWNLOAD_DIR/meta/paths_form.txt"
rm -f "$DOWNLOAD_DIR/meta/paths_info.json.part"
curl --fail --silent --show-error --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
  --user-agent "$UA" -X POST --data "@$DOWNLOAD_DIR/meta/paths_form.txt" \
  --output "$DOWNLOAD_DIR/meta/paths_info.json.part" "$PATHS_INFO_URL"
mv "$DOWNLOAD_DIR/meta/paths_info.json.part" "$DOWNLOAD_DIR/meta/paths_info.json"
python3 "$HELPER" check-paths --selection "$SELECTION" "$DOWNLOAD_DIR/meta/paths_info.json"

# Range fetch with resume-by-file: a finished range is kept only when its size
# is exact and its header dump exists; check-download re-validates all of them.
fetch_range() {  # repo_path start end output
  local url="$RESOLVE_BASE/$1" start="$2" end="$3" out="$4"
  local want=$((end - start + 1)) attempt got
  if [ -s "$out" ] && [ -s "$out.http" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$want" ]; then
    return 0
  fi
  for attempt in 1 2 3 4 5; do
    rm -f "$out.part" "$out.http.part"
    if curl --fail --silent --show-error --location --proto-redir =https \
        --retry 8 --retry-all-errors --retry-delay 5 --connect-timeout 30 \
        --speed-limit 1024 --speed-time 60 \
        --max-filesize $((want + 4096)) --range "$start-$end" --user-agent "$UA" \
        --dump-header "$out.http.part" --output "$out.part" "$url" < /dev/null; then
      got="$(wc -c < "$out.part" | tr -d ' ')"
      if [ "$got" = "$want" ]; then
        mv "$out.http.part" "$out.http"
        mv "$out.part" "$out"
        sleep 0.2
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

# 3. Header prefixes and pMean windows.
count=0
while IFS=$'\t' read -r run path _size _lfs _xet _npoints _npolys b64_start b64_end; do
  [ "$run" = "run" ] && continue
  stem="$(printf 'run_%03d' "$run")"
  fetch_range "$path" 0 $((HEAD_BYTES - 1)) "$DOWNLOAD_DIR/heads/$stem.head.bin"
  fetch_range "$path" $((b64_start - WINDOW_PRE)) $((b64_end + WINDOW_POST - 1)) \
    "$DOWNLOAD_DIR/pmean/$stem.pmean_window.bin"
  count=$((count + 1))
  echo "[$(date -Is)] fetched $path ($count)"
done < "$SELECTION"

# 4. Validate every response and every decoded field.
python3 "$HELPER" check-download --selection "$SELECTION" --download-dir "$DOWNLOAD_DIR"

date -Is > "$DOWNLOAD_DIR/DOWNLOAD_OK"
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
