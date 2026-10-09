#!/usr/bin/env bash
# Range-download the STORED <asset>_1K-PNG_NormalGL.png member from each of 119
# pinned ambientCG photogrammetry 1K-PNG zips (CC0). Only the member's local file
# header + PNG bytes are fetched; the rest of each zip is never downloaded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ambientcg_photogrammetry_normalgl_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TABLE="$RECIPE_DIR/scripts/assets.tsv"
TOOL="$RECIPE_DIR/scripts/normalgl.py"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 -I "$TOOL" selftest

mapfile -t JOBS < <(python3 -I "$TOOL" list --table "$TABLE")
echo "selected assets: ${#JOBS[@]}"
[[ "${#JOBS[@]}" -eq 119 ]] || { echo "expected 119 selected assets" >&2; exit 1; }

done_count=0
fetched_bytes=0
for job in "${JOBS[@]}"; do
  IFS=$'\t' read -r asset zip_size start end length <<<"$job"
  target="$DOWNLOAD_DIR/${asset}_1K-PNG_NormalGL.png"
  if [[ -f "$target" ]] && python3 -I "$TOOL" check --table "$TABLE" --asset "$asset" --png "$target"; then
    done_count=$((done_count + 1))
    continue
  fi
  part="$DOWNLOAD_DIR/${asset}.member.part"
  hdr="$DOWNLOAD_DIR/${asset}.headers.part"
  url="https://ambientcg.com/get?file=${asset}_1K-PNG.zip"
  ok=0
  for attempt in 1 2 3; do
    rm -f "$part" "$hdr"
    code="$(curl -fsSL --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
      -r "${start}-${end}" -D "$hdr" -o "$part" -w '%{http_code}' "$url" || true)"
    if [[ "$code" != "206" ]]; then
      echo "attempt $attempt: $asset HTTP $code (expected 206 partial content)" >&2
      sleep 5
      continue
    fi
    # Last Content-Range (after the 302 to the CDN) must be exact and report the pinned zip size.
    cr="$(grep -i '^content-range:' "$hdr" | tail -n 1 | tr -d '\r' | awk '{print $3}')"
    if [[ "$cr" != "${start}-${end}/${zip_size}" ]]; then
      echo "content-range mismatch for $asset: got '$cr' want '${start}-${end}/${zip_size}'" >&2
      exit 1
    fi
    actual="$(stat -c %s "$part")"
    if [[ "$actual" != "$length" ]]; then
      echo "attempt $attempt: $asset got $actual bytes, want $length" >&2
      continue
    fi
    ok=1
    break
  done
  [[ "$ok" == 1 ]] || { echo "failed to fetch $asset" >&2; exit 1; }
  # Validates local header (STORED, name, sizes, CRC32 vs pinned central directory) and IHDR.
  python3 -I "$TOOL" extract --table "$TABLE" --asset "$asset" --range-file "$part" --out "$target"
  rm -f "$part" "$hdr"
  done_count=$((done_count + 1))
  fetched_bytes=$((fetched_bytes + length))
  echo "[$(date -Is)] $done_count/${#JOBS[@]} $asset ok ($length bytes)"
done

png_count="$(find "$DOWNLOAD_DIR" -maxdepth 1 -name '*_1K-PNG_NormalGL.png' | wc -l)"
[[ "$png_count" -eq 119 ]] || { echo "expected 119 PNGs, found $png_count" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID members=$done_count fetched_this_run=$fetched_bytes"
