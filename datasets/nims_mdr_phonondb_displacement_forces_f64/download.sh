#!/usr/bin/env bash
# Fetch the pinned phonopy_params.yaml.xz files listed in sources.tsv from the
# NIMS Materials Data Repository (MDR phonon calculation database, CC BY 4.0).
# Only the phonopy_params.yaml.xz fileset of each record is fetched; PNG plots
# and vasp-settings archives are never requested.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nims_mdr_phonondb_displacement_forces_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
XZ_DIR="$DOWNLOAD_DIR/xz"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
PARALLEL="${PARALLEL:-4}"
EXPECTED_FILES=5078
EXPECTED_BYTES=178435928
export UA="openzl-public-datasets-nims-mdr-phonondb-download/1.0"

mkdir -p "$XZ_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID parallel=$PARALLEL"

# Liveness: one-byte range GET on the first pinned fileset.
first_fs="$(awk -F'\t' 'NR==2{print $3}' "$SOURCES")"
curl -fsSL -r 0-0 --max-time 120 -A "$UA" -o /dev/null \
  "https://mdr.nims.go.jp/filesets/$first_fs/download"
echo "liveness ok fileset=$first_fs"

fetch_one() {
  local ds="$1" mp="$2" fs="$3" size="$4" md5="$5" dir="$6"
  local target="$dir/$ds.yaml.xz"
  if [[ -s "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] \
     && [[ "$(md5sum "$target" | cut -d' ' -f1)" == "$md5" ]]; then
    return 0
  fi
  local attempt
  for attempt in 1 2 3 4 5; do
    rm -f "$target.part"
    if curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
         --connect-timeout 60 --speed-limit 512 --speed-time 120 \
         --max-filesize 20000000 -A "$UA" -o "$target.part" \
         "https://mdr.nims.go.jp/filesets/$fs/download"; then
      if [[ "$(stat -c %s "$target.part")" == "$size" ]] \
         && [[ "$(md5sum "$target.part" | cut -d' ' -f1)" == "$md5" ]]; then
        mv "$target.part" "$target"
        echo "fetched $ds $mp bytes=$size"
        return 0
      fi
      echo "checksum/size mismatch $ds $mp attempt=$attempt" >&2
    fi
    sleep $((attempt * 10))
  done
  echo "FAILED $ds $mp fileset=$fs" >&2
  return 1
}
export -f fetch_one

tail -n +2 "$SOURCES" \
  | awk -F'\t' -v d="$XZ_DIR" '{print $1" "$2" "$3" "$4" "$5" "d}' \
  | xargs -P "$PARALLEL" -n 6 bash -c 'fetch_one "$@"' _

# Re-validate the complete pinned set (count, sizes, md5) independent of xargs status.
count=0; bytes=0; bad=0
while IFS=$'\t' read -r ds mp fs size md5; do
  [[ "$ds" == "dataset_id" ]] && continue
  t="$XZ_DIR/$ds.yaml.xz"
  if [[ ! -f "$t" ]] || [[ "$(stat -c %s "$t")" != "$size" ]]; then
    echo "missing or wrong size: $ds $mp" >&2; bad=$((bad + 1)); continue
  fi
  count=$((count + 1)); bytes=$((bytes + size))
done < "$SOURCES"
(cd "$XZ_DIR" && tail -n +2 "$SOURCES" | awk -F'\t' '{print $5"  "$1".yaml.xz"}' | md5sum --check --quiet) \
  || { echo "md5 verification failed" >&2; exit 1; }
[[ "$bad" == 0 ]] || { echo "$bad files missing or wrong size" >&2; exit 1; }
[[ "$count" == "$EXPECTED_FILES" ]] || { echo "unexpected file count $count != $EXPECTED_FILES" >&2; exit 1; }
[[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes != $EXPECTED_BYTES" >&2; exit 1; }

# Semantic payload check: valid xz, phonopy YAML with displacement force sets.
python3 -I "$RECIPE_DIR/scripts/phonondb.py" check-downloads \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_ROOT" --sources "$SOURCES"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
