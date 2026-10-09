#!/usr/bin/env bash
# Fetch the pinned Juno JunoCam perijove lossless colour EDRs from the PDS Imaging Node
# (planetarydata.jpl.nasa.gov, public anonymous HTTPS):
#   1. evidence: JNOJNC_0033 AAREADME.TXT and the EDR/RDR SIS (HTML), size + MD5 pinned
#   2. all 35 volume INDEX.TAB files (size + MD5 pinned in volumes.tsv); the candidate list
#      (highest product version across volumes) is re-derived from them and must equal candidates.tsv
#   3. the 531 candidate PDS3 labels, each checked against the INDEX.TAB label MD5; the
#      per-perijove selection is re-derived from them and must equal sources.tsv
#   4. the 22 selected IMG files (resumable), checked by size, MD5 and label consistency
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_juno_junocam_perijove_rgb_framelets_u8"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BASE="https://planetarydata.jpl.nasa.gov/img/data/juno"
UA="openzl-public-datasets-junocam/1.0"
EXPECTED_VOLUMES=35
EXPECTED_CANDIDATES=531
EXPECTED_IMAGES=22
EXPECTED_IMG_BYTES=549298176

mkdir -p "$DL/evidence" "$DL/index" "$DL/labels" "$DL/img" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

md5_of() { md5sum "$1" | cut -d' ' -f1; }

# fetch_pinned <url> <target> <size|-> <md5> <max_bytes>: resumable fetch validated by MD5 (and size when given).
fetch_pinned() {
  local url="$1" target="$2" size="$3" md5="$4" max="$5"
  if [[ -s "$target" && "$(md5_of "$target")" == "$md5" ]]; then
    return 0
  fi
  rm -f "$target"
  if [[ -s "$target.part" && "$size" != "-" ]] && (( $(stat -c %s "$target.part") >= size )); then
    rm -f "$target.part"
  fi
  if [[ "$size" == "-" ]]; then
    rm -f "$target.part"
  fi
  curl --fail --silent --show-error --location -C - --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize "$max" \
    --user-agent "$UA" --output "$target.part" "$url"
  if [[ "$size" != "-" && "$(stat -c %s "$target.part")" != "$size" ]]; then
    echo "FATAL size mismatch $url expected=$size actual=$(stat -c %s "$target.part")" >&2
    rm -f "$target.part"
    exit 1
  fi
  if [[ "$(md5_of "$target.part")" != "$md5" ]]; then
    echo "FATAL MD5 mismatch $url expected=$md5 actual=$(md5_of "$target.part")" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Liveness: one-byte range GET on the first pinned image.
first_url="$(awk -F'\t' 'NR==2 {print $7}' "$RECIPE_DIR/sources.tsv")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

# 1. Evidence (rights/citation context, format and lossless-compression definitions).
fetch_pinned "$BASE/JNOJNC_0033/AAREADME.TXT" "$DL/evidence/AAREADME.TXT" 9911 78a1c7371648ae57ddd7943dbaf83923 100000
fetch_pinned "$BASE/JNOJNC_0033/DOCUMENT/JUNO_JNC_EDR_RDR_DPSIS.HTM" "$DL/evidence/JUNO_JNC_EDR_RDR_DPSIS.HTM" \
  52771 d93d404258be3431006c8a1dd367ee91 1000000
python3 "$CHECK" evidence "$DL/evidence/AAREADME.TXT" "$DL/evidence/JUNO_JNC_EDR_RDR_DPSIS.HTM"

# 2. Volume index tables (version de-duplication and candidate derivation).
n=0
while IFS=$'\t' read -r volume url size md5; do
  fetch_pinned "$url" "$DL/index/${volume}_INDEX.TAB" "$size" "$md5" 20000000
  n=$((n + 1))
done < <(awk -F'\t' 'NR > 1' "$RECIPE_DIR/volumes.tsv")
[[ "$n" == "$EXPECTED_VOLUMES" ]] || { echo "FATAL volumes=$n expected=$EXPECTED_VOLUMES" >&2; exit 1; }
python3 "$CHECK" candidates "$DL/index" "$RECIPE_DIR/candidates.tsv"

# 3. Candidate labels (MD5 from the INDEX.TAB PRODUCT_LABEL_MD5CHECKSUM column).
n=0
while IFS=$'\t' read -r pid url md5; do
  fetch_pinned "$url" "$DL/labels/$pid.LBL" - "$md5" 100000
  n=$((n + 1))
done < <(awk -F'\t' 'NR > 1 {print $1 "\t" $6 "\t" $7}' "$RECIPE_DIR/candidates.tsv")
[[ "$n" == "$EXPECTED_CANDIDATES" ]] || { echo "FATAL candidates=$n expected=$EXPECTED_CANDIDATES" >&2; exit 1; }
echo "labels_ok n=$n"
python3 "$CHECK" selection "$DL/index" "$DL/labels" "$RECIPE_DIR/candidates.tsv" "$RECIPE_DIR/sources.tsv"

# 4. Selected images (resumable), size + MD5 pinned, then label-consistency decode check.
plan="$DL/download_plan.tsv"
printf 'product_id\torbit\timg_size\timg_md5\timg_sha256\n' > "$plan.part"
n=0
bytes=0
while IFS=$'\t' read -r pid orbit url size md5; do
  img="$DL/img/$pid.IMG"
  fetch_pinned "$url" "$img" "$size" "$md5" 40000000
  if ! digests="$(python3 "$CHECK" image "$img" "$DL/labels/$pid.LBL" "$pid" "$orbit")"; then
    echo "FATAL semantic validation failed product=$pid; removing" >&2
    rm -f "$img"
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$pid" "$orbit" "$size" "$md5" "${digests##* }" >> "$plan.part"
  echo "image_ok product=$pid orbit=$orbit bytes=$size"
  n=$((n + 1))
  bytes=$((bytes + size))
done < <(awk -F'\t' 'NR > 1 {print $1 "\t" $3 "\t" $7 "\t" $8 "\t" $9}' "$RECIPE_DIR/sources.tsv")
mv "$plan.part" "$plan"
if [[ "$n" != "$EXPECTED_IMAGES" || "$bytes" != "$EXPECTED_IMG_BYTES" ]]; then
  echo "FATAL images=$n bytes=$bytes expected $EXPECTED_IMAGES / $EXPECTED_IMG_BYTES" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID images=$n img_bytes=$bytes"
