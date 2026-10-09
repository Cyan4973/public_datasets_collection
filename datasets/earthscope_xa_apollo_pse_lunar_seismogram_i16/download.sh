#!/usr/bin/env bash
# Fetch the pinned Apollo PSE station-day plan (plan.tsv) from the EarthScope
# FDSN dataselect service: one GET per station-day for XA.<sta>.00.MHZ (the
# peaked-mode long-period vertical), pinned inside 1971-1977 because the XA
# network code is reused by later temporary networks. Also fetches the XA
# channel inventory, the FDSN XA_1969 network page and the NASA SMD science
# information policy page (license basis).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="earthscope_xa_apollo_pse_lunar_seismogram_i16"
BASE="${EARTHSCOPE_FDSNWS_BASE:-https://service.earthscope.org/fdsnws}"
POLICY_URL="https://science.nasa.gov/researchers/science-data/science-information-policy/"
NETWORK_URL="https://www.fdsn.org/networks/detail/XA_1969/"
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

fetch_small "$BASE/station/1/query?net=XA&starttime=1969-07-01&endtime=1977-12-31&level=channel&format=text" \
  "$DOWNLOAD_DIR/xa_channels.txt"
fetch_small "$POLICY_URL" "$DOWNLOAD_DIR/nasa_smd_science_information_policy.html"
fetch_small "$NETWORK_URL" "$DOWNLOAD_DIR/fdsn_xa_1969.html"

n=0; fetched=0; cached=0; nodata=0
total="$(($(wc -l < "$RECIPE_DIR/plan.tsv") - 1))"
while IFS=$'\t' read -r sta day; do
  [ "$sta" = "station" ] && continue
  n=$((n + 1))
  case "$day" in 197[1-7]-*) ;; *) echo "FATAL: plan day $day outside 1971-1977" >&2; exit 1 ;; esac
  next="$(date -u -d "$day + 1 day" +%F)"
  out="$DOWNLOAD_DIR/mseed/XA.$sta.00.MHZ.$day.mseed"
  if [ -e "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    cached=$((cached + 1)); continue
  fi
  url="$BASE/dataselect/1/query?net=XA&sta=$sta&loc=00&cha=MHZ&start=${day}T00:00:00&end=${next}T00:00:00&nodata=404"
  rm -f "$out.part"
  code="$(curl --silent --show-error --location --retry 8 --retry-delay 10 --retry-all-errors \
    --speed-limit 512 --speed-time 120 --max-filesize 20000000 \
    --user-agent "$UA" --output "$out.part" --write-out '%{http_code}' "$url" || true)"
  case "$code" in
    200)
      # semantic check: non-empty, whole 512-byte multiples, and a miniSEED 2
      # fixed header (6-char sequence number + D/R/Q/M quality + XA station id)
      sz="$(wc -c < "$out.part")"
      if [ "$sz" -lt 512 ] || [ $((sz % 512)) -ne 0 ]; then
        echo "FATAL: $sta $day: HTTP 200 but payload size $sz is not whole miniSEED records" >&2; exit 1
      fi
      if ! head -c 20 "$out.part" | LC_ALL=C grep -qaE "^[0-9 ]{6}[DRQM] $sta {1,2}00MHZXA$"; then
        echo "FATAL: $sta $day: HTTP 200 but payload is not XA.$sta.00.MHZ miniSEED" >&2; exit 1
      fi ;;
    404|204) : > "$out.part"; nodata=$((nodata + 1)); echo "no_data $sta $day" ;;
    *) echo "FATAL: $sta $day: HTTP $code" >&2; rm -f "$out.part"; exit 1 ;;
  esac
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  if [ $((n % 20)) -eq 0 ]; then echo "progress $n/$total fetched=$fetched cached=$cached no_data=$nodata"; fi
done < "$RECIPE_DIR/plan.tsv"
echo "station_days=$n fetched=$fetched cached=$cached no_data=$nodata"

# Full semantic validation: Steim2 self-test, then decode every record (X0/Xn
# checks), confirm stream identity and inventory, classify each station-day.
python3 -I "$RECIPE_DIR/scripts/selftest_steim2.py"
python3 -I "$RECIPE_DIR/scripts/apollo.py" validate --recipe "$RECIPE_DIR" \
  --downloads "$DOWNLOAD_DIR" --outcome "$DOWNLOAD_DIR/download_outcome.tsv"
( cd "$DOWNLOAD_DIR" && find mseed -type f -name '*.mseed' | sort | xargs sha256sum > mseed.sha256 )
echo "bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
