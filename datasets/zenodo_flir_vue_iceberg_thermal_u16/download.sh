#!/usr/bin/env bash
# Range-download 360 selected TIFF members (every 8th 1 Hz frame per flight session)
# from five pinned Zenodo zips of record 10641368 (CC BY 4.0). Only each member's
# local file header + deflated data + data descriptor is fetched (~82 MB in total);
# the full zips (1.06 GB, incl. AVI renders) are never downloaded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_flir_vue_iceberg_thermal_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TABLE="$RECIPE_DIR/scripts/frames.tsv"
TOOL="$RECIPE_DIR/scripts/flir.py"
BASE_URL="https://zenodo.org/records/10641368/files"
EXPECTED=360
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 -I "$TOOL" selftest

# Liveness: one-byte range GET (follows redirects).
probe="$(curl -fsSL --retry 5 --retry-delay 5 --max-time 60 -r 0-0 -o /dev/null -w '%{http_code}' \
  "$BASE_URL/20180820_035505.zip?download=1" || true)"
if [[ "$probe" != "206" ]]; then
  echo "liveness probe failed: HTTP $probe (expected 206)" >&2
  exit 1
fi

mapfile -t JOBS < <(python3 -I "$TOOL" list --table "$TABLE")
echo "selected frames: ${#JOBS[@]}"
[[ "${#JOBS[@]}" -eq "$EXPECTED" ]] || { echo "expected $EXPECTED selected frames" >&2; exit 1; }

done_count=0
fetched_bytes=0
for job in "${JOBS[@]}"; do
  IFS=$'\t' read -r session frame zip_size start end length <<<"$job"
  mkdir -p "$DOWNLOAD_DIR/$session"
  target="$DOWNLOAD_DIR/$session/$frame.zipmember"
  if [[ -f "$target" ]] && python3 -I "$TOOL" check --table "$TABLE" --session "$session" --frame "$frame" --range-file "$target" 2>/dev/null; then
    done_count=$((done_count + 1))
    continue
  fi
  part="$target.part"
  hdr="$target.headers.part"
  url="$BASE_URL/$session.zip?download=1"
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$part" "$hdr"
    code="$(curl -fsSL --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
      -r "${start}-${end}" -D "$hdr" -o "$part" -w '%{http_code}' "$url" || true)"
    if [[ "$code" != "206" ]]; then
      echo "attempt $attempt: $session/$frame HTTP $code (expected 206 partial content)" >&2
      sleep $((attempt * 5))
      continue
    fi
    # The final Content-Range must be exact and report the pinned zip size.
    cr="$(grep -i '^content-range:' "$hdr" | tail -n 1 | tr -d '\r' | awk '{print $3}')"
    if [[ "$cr" != "${start}-${end}/${zip_size}" ]]; then
      echo "content-range mismatch for $session/$frame: got '$cr' want '${start}-${end}/${zip_size}'" >&2
      exit 1
    fi
    actual="$(stat -c %s "$part")"
    if [[ "$actual" != "$length" ]]; then
      echo "attempt $attempt: $session/$frame got $actual bytes, want $length" >&2
      continue
    fi
    ok=1
    break
  done
  [[ "$ok" == 1 ]] || { echo "failed to fetch $session/$frame" >&2; exit 1; }
  # Local header (name, method 8, flags), raw inflate, CRC32 + sizes vs the pinned
  # central directory, data descriptor, and TIFF IFD (640x512, 16-bit, uncompressed,
  # 1 sample/pixel, FLIR Vue Pro R 640). Invalid payloads are fatal.
  python3 -I "$TOOL" check --table "$TABLE" --session "$session" --frame "$frame" --range-file "$part"
  mv -f "$part" "$target"
  rm -f "$hdr"
  done_count=$((done_count + 1))
  fetched_bytes=$((fetched_bytes + length))
  if (( done_count % 20 == 0 )); then
    echo "[$(date -Is)] $done_count/$EXPECTED frames ($fetched_bytes bytes fetched this run)"
  fi
done

member_count="$(find "$DOWNLOAD_DIR" -mindepth 2 -maxdepth 2 -name '*.tiff.zipmember' | wc -l)"
[[ "$member_count" -eq "$EXPECTED" ]] || { echo "expected $EXPECTED members, found $member_count" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID members=$done_count fetched_this_run=$fetched_bytes"
