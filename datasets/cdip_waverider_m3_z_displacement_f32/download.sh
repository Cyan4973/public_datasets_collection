#!/usr/bin/env bash
# Fetch the 128 pinned CDIP DWR-M3 heave windows (windows.tsv) via OPeNDAP
# server-side hyperslab projection, plus each deployment's .das (instrument
# title + license), and validate every payload semantically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cdip_waverider_m3_z_displacement_f32"
BASE="${CDIP_THREDDS_BASE:-https://thredds.cdip.ucsd.edu/thredds/dodsC}"
WINDOWS="$RECIPE_DIR/windows.tsv"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-cdip-m3/1.0"
EXPECTED_WINDOWS=128
EXPECTED_VALUES=331776
# DDS header (270 bytes, fixed for 31-character url paths) + XDR payload:
# 3 scalars (12) + 2 Byte arrays (8 + 331776 each) + Float32 array (8 + 4*331776)
EXPECTED_DODS_BYTES=1990962

mkdir -p "$DL/das" "$DL/dods" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

nrows="$(tail -n +2 "$WINDOWS" | grep -c .)"
if [ "$nrows" != "$EXPECTED_WINDOWS" ]; then
  echo "FATAL: windows.tsv has $nrows rows, expected $EXPECTED_WINDOWS" >&2
  exit 1
fi

fetch() {
  # fetch <url> <dest> <max_time>; -g disables curl globbing of [a:1:b]
  local url="$1" dest="$2" max_time="$3"
  rm -f "$dest.part"
  curl -g --fail --silent --show-error --location \
    --retry 8 --retry-delay 10 --retry-all-errors \
    --connect-timeout 60 --max-time "$max_time" \
    --speed-limit 1024 --speed-time 120 \
    --user-agent "$UA" --output "$dest.part" "$url" || return 1
  mv "$dest.part" "$dest"
}

i=0
total_bytes=0
while IFS=$'\t' read -r -u 3 station deployment url_path xyz_count start_index value_count window_start site; do
  [ "$station" = "station" ] && continue
  i=$((i + 1))
  if [ "$value_count" != "$EXPECTED_VALUES" ] || [ "${#url_path}" != 31 ]; then
    echo "FATAL: unexpected windows.tsv row for $deployment" >&2
    exit 1
  fi
  end_index=$((start_index + value_count - 1))
  if [ "$end_index" -ge "$xyz_count" ]; then
    echo "FATAL: window exceeds xyzCount for $deployment" >&2
    exit 1
  fi

  das="$DL/das/$deployment.das"
  if [ ! -s "$das" ] || ! python3 -I "$RECIPE_DIR/scripts/cdip_m3.py" check-das "$das" "$deployment" >/dev/null 2>&1; then
    fetch "$BASE/$url_path.das" "$das" 300
  fi
  python3 -I "$RECIPE_DIR/scripts/cdip_m3.py" check-das "$das" "$deployment" >/dev/null

  dods="$DL/dods/${deployment}_${start_index}_${value_count}.dods"
  query="xyzStartTime,xyzSampleRate,xyzFilterDelay,xyzFlagPrimary[$start_index:1:$end_index],xyzFlagSecondary[$start_index:1:$end_index],xyzZDisplacement[$start_index:1:$end_index]"
  ok=0
  for attempt in 1 2 3 4; do
    if [ -s "$dods" ] && [ "$(wc -c < "$dods" | tr -d ' ')" = "$EXPECTED_DODS_BYTES" ]; then
      rc=0
      msg="$(python3 -I "$RECIPE_DIR/scripts/cdip_m3.py" check-dods "$dods" "$start_index" "$value_count")" || rc=$?
      if [ "$rc" = 0 ]; then
        ok=1
        break
      fi
      if [ "$rc" = 3 ]; then
        echo "FATAL: semantically invalid window for $deployment (see message above)" >&2
        exit 1
      fi
    fi
    [ -e "$dods" ] && echo "refetch $deployment attempt=$attempt (size $(wc -c < "$dods" | tr -d ' '))"
    rm -f "$dods"
    fetch "$BASE/$url_path.dods?$query" "$dods" 900 || { echo "fetch failed $deployment attempt=$attempt"; sleep $((attempt * 20)); }
  done
  if [ "$ok" != 1 ]; then
    echo "FATAL: could not obtain a valid window for $deployment" >&2
    exit 1
  fi
  total_bytes=$((total_bytes + EXPECTED_DODS_BYTES))
  echo "[$i/$EXPECTED_WINDOWS] $deployment ($site) start=$start_index $msg"
done 3< "$WINDOWS"

if [ "$i" != "$EXPECTED_WINDOWS" ]; then
  echo "FATAL: processed $i windows, expected $EXPECTED_WINDOWS" >&2
  exit 1
fi
echo "windows_ok=$i dods_bytes=$total_bytes"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
