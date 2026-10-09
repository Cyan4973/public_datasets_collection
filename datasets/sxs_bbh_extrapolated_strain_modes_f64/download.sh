#!/usr/bin/env bash
# Range-fetch only the HDF5 metadata and the Extrapolated_N2 l<=4 mode chunks
# of 51 pinned SXS:BBH rhOverM_Asymptotic_GeometricUnits_CoM.h5 files from
# their CC BY 4.0 Zenodo records, plus each record's JSON and metadata.json,
# plus one complete control file (SXS:BBH:1180) for a whole-file MD5 check of
# the range-block assembly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="sxs_bbh_extrapolated_strain_modes_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SIMS="$RECIPE_DIR/sims.tsv"
API="https://zenodo.org/api/records"
UA="openzl-public-datasets-sxs-bbh/1.0"
MAX_ROUNDS=40
PARALLEL=2
CONTROL_TAG="SXS_BBH_1180"

mkdir -p "$DOWNLOAD_DIR/records" "$DOWNLOAD_DIR/metadata" "$DOWNLOAD_DIR/blocks" "$DOWNLOAD_DIR/control" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 -I "$RECIPE_DIR/scripts/sxs_modes.py")
die() { echo "ERROR: $*" >&2; exit 1; }

python3 -I "$RECIPE_DIR/scripts/selftest_sxs_h5.py"
echo "sims.tsv sha256=$(sha256sum "$SIMS" | cut -d' ' -f1) rows=$(($(wc -l < "$SIMS") - 1))"

small_get() {  # small_get URL OUT MAXBYTES
  curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors \
    --max-time 180 --max-filesize "$3" --user-agent "$UA" --output "$2.part" "$1" < /dev/null
  mv "$2.part" "$2"
}

# 1. Per-record identity, license (cc-by-4.0) and pinned file size/MD5; then metadata.json.
tail -n +2 "$SIMS" | while IFS=$'\t' read -r sxs rid lev h5key h5size h5md5 metakey metasize metamd5; do
  tag="${sxs//:/_}"
  rec="$DOWNLOAD_DIR/records/$tag.json"
  if [ ! -s "$rec" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    small_get "$API/$rid" "$rec" 20000000
    sleep 0.5
  fi
  "${TOOL[@]}" validate-record --sims "$SIMS" --tag "$tag" --record "$rec"
  meta="$DOWNLOAD_DIR/metadata/$tag.json"
  if [ ! -s "$meta" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    small_get "$API/$rid/files/$metakey/content" "$meta" 1000000
    sleep 0.5
  fi
  "${TOOL[@]}" validate-meta --sims "$SIMS" --tag "$tag" --meta "$meta"
done

# 2. Liveness: one-byte range GET of the first pinned HDF5 file.
first="$(sed -n 2p "$SIMS")"
first_url="$API/$(echo "$first" | cut -f2)/files/$(echo "$first" | cut -f4)/content"
code="$(curl --silent --location --output /dev/null --write-out '%{http_code}' --range 0-0 \
  --max-time 60 --retry 3 --user-agent "$UA" "$first_url" < /dev/null || true)"
[ "$code" = "206" ] || die "liveness range GET of $first_url returned HTTP $code"

# 3. Planner rounds: each round walks every file's HDF5 metadata through the
#    local 64 KiB block cache and lists the (coalesced) block ranges still
#    needed: superblock/root group, N2 symbol table, the 21 l<=4 dataset
#    headers and chunk B-trees, then their shuffle+deflate chunks.
complete=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  set +e
  "${TOOL[@]}" plan --sims "$SIMS" --downloads "$DOWNLOAD_DIR" --requests "$DOWNLOAD_DIR/block_requests.tsv"
  status=$?
  set -e
  if [ "$status" = 0 ]; then complete=1; break; fi
  [ "$status" = 3 ] || exit "$status"
  echo "round=$round range_requests=$(wc -l < "$DOWNLOAD_DIR/block_requests.tsv")"
  tr '\t' '\n' < "$DOWNLOAD_DIR/block_requests.tsv" \
    | xargs -d '\n' -n 6 -P "$PARALLEL" bash "$RECIPE_DIR/scripts/fetch_range.sh"
done
[ "$complete" = 1 ] || die "block plan did not converge within $MAX_ROUNDS rounds"

# 4. Control: the complete smallest pinned file, resumable, MD5-checked.
line="$(awk -F'\t' -v s="${CONTROL_TAG//_/:}" '$1 == s' "$SIMS")"
[ -n "$line" ] || die "control simulation missing from sims.tsv"
c_url="$API/$(echo "$line" | cut -f2)/files/$(echo "$line" | cut -f4)/content"
c_size="$(echo "$line" | cut -f5)"
c_md5="$(echo "$line" | cut -f6)"
c_out="$DOWNLOAD_DIR/control/$CONTROL_TAG.h5"
if [ ! -f "$c_out" ] || [ "$(stat -c %s "$c_out")" != "$c_size" ]; then
  curl --fail --silent --show-error --location --continue-at - \
    --retry 10 --retry-delay 5 --retry-all-errors --speed-limit 1024 --speed-time 120 \
    --user-agent "$UA" --output "$c_out.part" "$c_url" < /dev/null
  [ "$(stat -c %s "$c_out.part")" = "$c_size" ] || die "control size mismatch"
  echo "$c_md5  $c_out.part" | md5sum --check --status || { rm -f "$c_out.part"; die "control MD5 mismatch"; }
  mv "$c_out.part" "$c_out"
fi
echo "$c_md5  $c_out" | md5sum --check --status || die "control MD5 mismatch"
echo "control_ok $CONTROL_TAG bytes=$c_size md5=$c_md5"

blocks="$(find "$DOWNLOAD_DIR/blocks" -name 'blk_*.bin' | wc -l)"
echo "blocks=$blocks bytes_total=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
