#!/usr/bin/env bash
# Fetch the pinned PB Gladwin strainmeter station-day plan (plan.tsv) from the
# EarthScope FDSN dataselect service: one GET per station-day for the four
# 1-sps gauge channels LS1,LS2,LS3,LS4 (location T0), plus the PB LS? channel
# inventory and the GAGE/EarthScope CC BY 4.0 license page.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="earthscope_pb_borehole_strain_counts_i32"
BASE="${EARTHSCOPE_FDSNWS_BASE:-https://service.earthscope.org/fdsnws}"
LICENSE_URL="https://www.unavco.org/data/policies_forms/data-policy/data-license.html"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-collection/1.0 ($DATASET_ID)"

mkdir -p "$DOWNLOAD_DIR/mseed" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID base=$BASE"

fetch_small() {
  local url="$1" out="$2"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit $out"; return 0
  fi
  curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors \
    --max-time 300 --max-filesize 20000000 --user-agent "$UA" --output "$out.part" "$url"
  mv "$out.part" "$out"
}

fetch_small "$BASE/station/1/query?net=PB&cha=LS?&level=channel&format=text" "$DOWNLOAD_DIR/pb_ls_channels.txt"
fetch_small "$LICENSE_URL" "$DOWNLOAD_DIR/gage_data_license.html"

n=0; fetched=0; cached=0
total="$(($(wc -l < "$RECIPE_DIR/plan.tsv") - 1))"
while IFS=$'\t' read -r sta day; do
  [ "$sta" = "station" ] && continue
  n=$((n + 1))
  next="$(date -u -d "$day + 1 day" +%F)"
  out="$DOWNLOAD_DIR/mseed/PB.$sta.T0.LS_.$day.mseed"
  if [ -e "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    cached=$((cached + 1)); continue
  fi
  url="$BASE/dataselect/1/query?net=PB&sta=$sta&loc=T0&cha=LS1,LS2,LS3,LS4&start=${day}T00:00:00&end=${next}T00:00:00&nodata=404"
  rm -f "$out.part"
  code="$(curl --silent --show-error --location --retry 8 --retry-delay 10 --retry-all-errors \
    --speed-limit 512 --speed-time 120 --max-filesize 50000000 \
    --user-agent "$UA" --output "$out.part" --write-out '%{http_code}' "$url" || true)"
  case "$code" in
    200)
      # semantic check: a miniSEED 2 record starts with a 6-char sequence
      # number and a D/R/Q/M quality indicator
      if ! head -c 7 "$out.part" | LC_ALL=C grep -qE '^[0-9 ]{6}[DRQM]$'; then
        echo "FATAL: $sta $day: HTTP 200 but payload is not miniSEED" >&2; exit 1
      fi ;;
    404|204) : > "$out.part"; echo "no_data $sta $day" ;;
    *) echo "FATAL: $sta $day: HTTP $code" >&2; rm -f "$out.part"; exit 1 ;;
  esac
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  if [ $((n % 20)) -eq 0 ]; then echo "progress $n/$total fetched=$fetched cached=$cached"; fi
done < "$RECIPE_DIR/plan.tsv"
echo "station_days=$n fetched=$fetched cached=$cached"

# Full semantic validation: decode every record (Steim2 with X0/Xn checks),
# confirm stream identity and inventory instrument class, classify each
# gauge-day as complete / gap / fill / no_data.
python3 -I "$RECIPE_DIR/scripts/strain.py" validate --recipe "$RECIPE_DIR" \
  --downloads "$DOWNLOAD_DIR" --outcome "$DOWNLOAD_DIR/download_outcome.tsv"
( cd "$DOWNLOAD_DIR" && find mseed -type f -name '*.mseed' | sort | xargs sha256sum > mseed.sha256 )
echo "bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
