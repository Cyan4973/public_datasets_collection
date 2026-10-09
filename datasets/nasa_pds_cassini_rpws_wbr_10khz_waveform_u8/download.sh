#!/usr/bin/env bash
# Fetch the pinned Cassini RPWS WBR 10-kHz-mode hourly products (.DAT + detached
# .LBL) listed in sources.tsv from the PDS PPI UIowa subnode, plus the dataset
# catalog, row-prefix format and volume README as evidence.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_cassini_rpws_wbr_10khz_waveform_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BASE="https://space.physics.uiowa.edu/pds"
EVID_VOL="CORPWS_0130"
UA="openzl-public-datasets-cassini-rpws/1.0"
EXPECTED_PRODUCTS=88
EXPECTED_DAT_BYTES=297335488
EXPECTED_LBL_BYTES=522796

mkdir -p "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# fetch_small <url> <target> <size>: small file pinned by exact size.
fetch_small() {
  local url="$1" target="$2" size="$3"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size" ]]; then
    return 0
  fi
  rm -f "$target.part"
  curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize 1000000 \
    --user-agent "$UA" --output "$target.part" "$url"
  if [[ "$(stat -c %s "$target.part")" != "$size" ]]; then
    echo "FATAL size mismatch for $url (expected $size, got $(stat -c %s "$target.part"))" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Liveness: one-byte range GET on the first pinned product.
first_url="$(awk -F'\t' 'NR==2 {print $4}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

# Evidence: data-set catalog, row-prefix format, volume README (size-pinned, keyword-checked).
fetch_small "$BASE/$EVID_VOL/CATALOG/WBFULLDS.CAT" "$DOWNLOAD_DIR/evidence/WBFULLDS.CAT" 20907
fetch_small "$BASE/$EVID_VOL/LABEL/RPWS_WBR_WFR_ROW_PREFIX.FMT" "$DOWNLOAD_DIR/evidence/RPWS_WBR_WFR_ROW_PREFIX.FMT" 17684
fetch_small "$BASE/$EVID_VOL/AAREADME.TXT" "$DOWNLOAD_DIR/evidence/AAREADME.TXT" 18788
(cd "$DOWNLOAD_DIR/evidence" && md5sum --check --strict --quiet - <<'EOF'
f83e8e2f931a0881239486b560bc4ffe  WBFULLDS.CAT
26016b3d90af745aa5182d2b37385a53  RPWS_WBR_WFR_ROW_PREFIX.FMT
b20fda952f7df68b049bd8fd019230eb  AAREADME.TXT
EOF
)
grep -q 'CO-V/E/J/S/SS-RPWS-2-REFDR-WBRFULL-V1.0' "$DOWNLOAD_DIR/evidence/WBFULLDS.CAT"
grep -q '10-kHz baseband mode: 0.06 - 10.5 kHz, 36 microsecond sampling' "$DOWNLOAD_DIR/evidence/WBFULLDS.CAT"
grep -q '2 = 10 KHz filter, 36 microsecond sample period' "$DOWNLOAD_DIR/evidence/RPWS_WBR_WFR_ROW_PREFIX.FMT"
grep -q '0 = Ex, electric dipole X-direction' "$DOWNLOAD_DIR/evidence/RPWS_WBR_WFR_ROW_PREFIX.FMT"
grep -q 'encouraged to acknowledge both the PDS' "$DOWNLOAD_DIR/evidence/AAREADME.TXT"
echo "evidence_ok"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'volume\tproduct\tdat_size\tdat_sha256\tkept_values\tlbl_size\n' > "$plan.part"
count=0
dat_bytes=0
lbl_bytes=0
fetched=0
while IFS='|' read -r volume product dat_url dat_size lbl_url lbl_size record_bytes; do
  dir="$DOWNLOAD_DIR/$volume"
  mkdir -p "$dir"
  dat="$dir/$product.DAT"
  lbl="$dir/$product.LBL"

  fetch_small "$lbl_url" "$lbl" "$lbl_size"
  python3 "$CHECK" label "$lbl" "$product" "$dat_size" "$record_bytes"

  result=""
  if [[ -s "$dat" ]]; then
    if [[ "$(stat -c %s "$dat")" != "$dat_size" ]] \
      || ! result="$(python3 "$CHECK" dat "$dat" "$lbl" "$product" "$record_bytes")"; then
      echo "stale_or_invalid_cache product=$product; refetching"
      rm -f "$dat"
      result=""
    fi
  fi
  if [[ ! -s "$dat" ]]; then
    if [[ -s "$dat.part" ]] && (( $(stat -c %s "$dat.part") > dat_size )); then
      rm -f "$dat.part"
    fi
    curl --fail --silent --show-error --location -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 20000000 \
      --user-agent "$UA" --output "$dat.part" "$dat_url"
    actual="$(stat -c %s "$dat.part")"
    if [[ "$actual" != "$dat_size" ]]; then
      echo "FATAL size mismatch product=$product expected=$dat_size actual=$actual" >&2
      rm -f "$dat.part"
      exit 1
    fi
    if ! result="$(python3 "$CHECK" dat "$dat.part" "$lbl" "$product" "$record_bytes")"; then
      echo "FATAL semantic validation failed product=$product" >&2
      rm -f "$dat.part"
      exit 1
    fi
    mv "$dat.part" "$dat"
    fetched=$((fetched + 1))
    echo "fetched product=$product bytes=$dat_size"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$volume" "$product" "$dat_size" "${result%% *}" "${result##* }" \
    "$lbl_size" >> "$plan.part"
  count=$((count + 1))
  dat_bytes=$((dat_bytes + dat_size))
  lbl_bytes=$((lbl_bytes + lbl_size))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2 "|" $4 "|" $5 "|" $7 "|" $8 "|" $9}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_PRODUCTS" || "$dat_bytes" != "$EXPECTED_DAT_BYTES" || "$lbl_bytes" != "$EXPECTED_LBL_BYTES" ]]; then
  echo "FATAL unexpected selection totals products=$count dat_bytes=$dat_bytes lbl_bytes=$lbl_bytes" \
    "(expected $EXPECTED_PRODUCTS / $EXPECTED_DAT_BYTES / $EXPECTED_LBL_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID products=$count dat_bytes=$dat_bytes lbl_bytes=$lbl_bytes fetched_now=$fetched"
