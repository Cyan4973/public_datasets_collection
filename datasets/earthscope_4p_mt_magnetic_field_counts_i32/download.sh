#!/usr/bin/env bash
# Fetch the fdsnws station listings for 4P LFN/LFE/LFZ and the 48 pinned
# channel-epoch dataselect payloads (miniSEED, Steim2) from NSF EarthScope.
set -euo pipefail

DATASET_ID="earthscope_4p_mt_magnetic_field_counts_i32"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DL_DIR="$DATA_ROOT/downloads/$DATASET_ID"
STATION_DIR="$DL_DIR/station"
MSEED_DIR="$DL_DIR/mseed"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SELECTION="$RECIPE_DIR/selection.tsv"
TOOL="$RECIPE_DIR/scripts/mt_mseed.py"
BASE="https://service.earthscope.org/fdsnws"

mkdir -p "$STATION_DIR" "$MSEED_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 -I "$TOOL" selftest

CURL=(curl -fL --retry 10 --retry-delay 5 --retry-all-errors --speed-limit 1024 --speed-time 120 -sS)

# 1. station metadata (gain/sensor/epoch boundaries), one listing per magnetic channel
for cha in LFN LFE LFZ; do
  out="$STATION_DIR/station_4P_${cha}.txt"
  if [[ -s "$out" ]]; then
    echo "cached $(basename "$out")"
    continue
  fi
  "${CURL[@]}" -o "$out.part" "$BASE/station/1/query?net=4P&cha=${cha}&level=channel&format=text&nodata=404"
  head -1 "$out.part" | grep -q '^#Network | Station' || { echo "bad station listing for $cha" >&2; rm -f "$out.part"; exit 1; }
  mv "$out.part" "$out"
  echo "fetched $(basename "$out") bytes=$(stat -c %s "$out")"
done
python3 -I "$TOOL" check-station --station-dir "$STATION_DIR" --selection "$SELECTION"

# 2. one dataselect request per pinned station-channel epoch
n=0
total=0
while IFS=$'\t' read -r sta cha start end _lat _lon _nominal _expected _sha; do
  [[ "$sta" == "station" || -z "$sta" || "$sta" == \#* ]] && continue
  n=$((n + 1))
  stamp="$(echo "${start%%.*}" | tr -d ':-')"
  out="$MSEED_DIR/4P.${sta}..${cha}.${stamp}.mseed"
  if [[ -s "$out" ]] && python3 -I "$TOOL" inspect --selection "$SELECTION" --mseed "$out" > /dev/null; then
    echo "[$n] cached $(basename "$out")"
  else
    rm -f "$out" "$out.part"
    url="$BASE/dataselect/1/query?net=4P&sta=${sta}&loc=--&cha=${cha}&start=${start%%.*}&end=${end%%.*}&nodata=404"
    "${CURL[@]}" -o "$out.part" "$url"
    if ! python3 -I "$TOOL" inspect --selection "$SELECTION" --mseed "$out.part"; then
      echo "rejecting invalid payload for $sta $cha $start" >&2
      rm -f "$out.part"
      exit 1
    fi
    mv "$out.part" "$out"
    echo "[$n] fetched $(basename "$out") bytes=$(stat -c %s "$out")"
  fi
  total=$((total + $(stat -c %s "$out")))
done < "$SELECTION"

[[ "$n" -eq 48 ]] || { echo "expected 48 pinned epochs, found $n" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID epochs=$n mseed_bytes=$total"
