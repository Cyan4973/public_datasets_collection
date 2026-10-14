#!/usr/bin/env bash
# Fetch the pinned DWWSSN station-day plan (plan.tsv) from the EarthScope FDSN
# dataselect service: one GET per station-day for DW.<sta>..LHZ (the
# Sprengnether S-5007-V long-period vertical, 1 sps, DWWSSN 16-bit encoding).
# Also fetches the DW channel inventory (sensor epochs), the DW network-level
# StationXML (restrictedStatus), the FDSN DW network page and the USGS
# data-licensing page (license basis).
#
# Access caveat: EarthScope has announced that user authentication will be
# required for all data downloads from 2026-12-15. This script uses anonymous
# access only; after that date it may need a free EarthScope login, which the
# recipe does not supply.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="earthscope_dw_dwwssn_lp_seismogram_i16"
BASE="${EARTHSCOPE_FDSNWS_BASE:-https://service.earthscope.org/fdsnws}"
USGS_LICENSE_URL="https://www.usgs.gov/data-management/data-licensing"
NETWORK_URL="https://www.fdsn.org/networks/detail/DW/"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-collection/1.0 ($DATASET_ID)"
# www.usgs.gov (CloudFront) answers 403 to curl's default user agent and to
# agents without a browser-style token; this compatible string is accepted.
UA_WEB="Mozilla/5.0 (compatible; openzl-public-datasets-collection/1.0)"

mkdir -p "$DOWNLOAD_DIR/mseed" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID base=$BASE"

fetch_small() {
  local url="$1" out="$2" ua="${3:-$UA}"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit $out"; return 0
  fi
  curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors \
    --max-time 300 --max-filesize 20000000 --user-agent "$ua" --output "$out.part" "$url"
  mv "$out.part" "$out"
}

fetch_small "$BASE/station/1/query?net=DW&level=channel&format=text" "$DOWNLOAD_DIR/dw_channels.txt"
fetch_small "$BASE/station/1/query?net=DW&level=network&format=xml" "$DOWNLOAD_DIR/dw_network.xml"
fetch_small "$NETWORK_URL" "$DOWNLOAD_DIR/fdsn_dw.html"
fetch_small "$USGS_LICENSE_URL" "$DOWNLOAD_DIR/usgs_data_licensing.html" "$UA_WEB"

n=0; fetched=0; cached=0; nodata=0
total="$(($(wc -l < "$RECIPE_DIR/plan.tsv") - 1))"
while IFS=$'\t' read -r sta day; do
  [ "$sta" = "station" ] && continue
  n=$((n + 1))
  case "$sta" in [A-Z][A-Z][A-Z]) ;; *) echo "FATAL: plan station $sta is not a 3-letter DW code" >&2; exit 1 ;; esac
  case "$day" in 198[0-9]-*|199[0-4]-*) ;; *) echo "FATAL: plan day $day outside 1980-1994" >&2; exit 1 ;; esac
  next="$(date -u -d "$day + 1 day" +%F)"
  out="$DOWNLOAD_DIR/mseed/DW.$sta..LHZ.$day.mseed"
  if [ -e "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    cached=$((cached + 1)); continue
  fi
  url="$BASE/dataselect/1/query?net=DW&sta=$sta&loc=--&cha=LHZ&start=${day}T00:00:00&end=${next}T00:00:00&nodata=404"
  rm -f "$out.part"
  code="$(curl --silent --show-error --location --retry 8 --retry-delay 10 --retry-all-errors \
    --speed-limit 512 --speed-time 120 --max-filesize 20000000 \
    --user-agent "$UA" --output "$out.part" --write-out '%{http_code}' "$url" || true)"
  case "$code" in
    200)
      # semantic check: whole 512-byte multiples and a miniSEED 2 fixed header
      # (6-char sequence number + D/R/Q/M quality + DW.<sta>..LHZ identity)
      sz="$(wc -c < "$out.part")"
      if [ "$sz" -lt 512 ] || [ $((sz % 512)) -ne 0 ]; then
        echo "FATAL: $sta $day: HTTP 200 but payload size $sz is not whole miniSEED records" >&2; exit 1
      fi
      if ! head -c 20 "$out.part" | LC_ALL=C grep -qaE "^[0-9 ]{6}[DRQM] $sta {4}LHZDW$"; then
        echo "FATAL: $sta $day: HTTP 200 but payload is not DW.$sta..LHZ miniSEED" >&2; exit 1
      fi ;;
    404|204) : > "$out.part"; nodata=$((nodata + 1)); echo "no_data $sta $day" ;;
    *) echo "FATAL: $sta $day: HTTP $code" >&2; rm -f "$out.part"; exit 1 ;;
  esac
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  if [ $((n % 50)) -eq 0 ]; then echo "progress $n/$total fetched=$fetched cached=$cached no_data=$nodata"; fi
done < "$RECIPE_DIR/plan.tsv"
echo "station_days=$n fetched=$fetched cached=$cached no_data=$nodata"

# Full semantic validation: decoder self-test, then decode every record,
# confirm stream identity / encoding 32 / 1 sps / inventory epoch, check the
# license pages, classify each station-day.
python3 -I "$RECIPE_DIR/scripts/selftest_mseed.py"
python3 -I "$RECIPE_DIR/scripts/dw.py" validate --recipe "$RECIPE_DIR" \
  --downloads "$DOWNLOAD_DIR" --outcome "$DOWNLOAD_DIR/download_outcome.tsv"
( cd "$DOWNLOAD_DIR" && find mseed -type f -name '*.mseed' | sort | xargs sha256sum > mseed.sha256 )
echo "bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
