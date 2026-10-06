#!/usr/bin/env bash
# Fetch the pinned ExoMol resources for exomol_state_energy_levels_f64:
#   1. the master file exomol.all (version 20260605, SHA-256 pinned)
#   2. every .def it lists (250 files, SHA-256 pinned in master_datasets.tsv)
#      so the one-dataset-per-molecule selection can be re-derived
#   3. the .def.json and .states.bz2 of the 77 selected datasets
#      (exact sizes, SHA-256 and decoded line counts pinned in sources.tsv)
# URLs are re-derived from the master file plus each .def and compared with
# the pinned tables; any mismatch is fatal. Every .states.bz2 is decoded in
# full; its line count must equal the pinned count and its first record must
# have ID 1 and a finite energy. Files whose line count differs from the .def
# state count are valid downloads; build.sh excludes them (def_count rule).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="exomol_state_energy_levels_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
META_DIR="$DOWNLOAD_DIR/meta"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/exomol_states.py"
MASTER_URL="https://www.exomol.com/db/exomol.all"
MASTER_SHA256="3bc26ed45c5483839ee7a17ce4b135bdd5b2230147b6c261e07102884ffe646c"
EXPECTED_STATES_FILES=77
EXPECTED_STATES_BYTES=673432460
UA="openzl-public-datasets-exomol-states/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$META_DIR/def" "$DOWNLOAD_DIR/defjson" "$DOWNLOAD_DIR/states" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

sha_ok() {  # sha_ok <file> <expected-sha256>
  [ -s "$1" ] && [ -n "$2" ] && [ "$(sha256sum "$1" | awk '{print $1}')" = "$2" ]
}

fetch_small() {  # fetch_small <url> <output>
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 300 --max-filesize 5000000 \
    --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

fetch_big() {  # fetch_big <url> <output> <expected-bytes>
  local url="$1" out="$2" size="$3" part="$2.part" attempt have
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$size" ]; then
    echo "cache_hit bytes=$size file=$(basename "$out")"
    return 0
  fi
  rm -f "$out"
  if [ -f "$part" ] && [ "$(stat -c %s "$part")" -gt "$size" ]; then rm -f "$part"; fi
  for attempt in 1 2 3 4 5; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    [ "$have" = "$size" ] && break
    echo "fetch attempt=$attempt resume_from=$have bytes=$size file=$(basename "$out")"
    if curl --fail --silent --show-error --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$url"; then
      :
    else
      echo "curl exit=$? file=$(basename "$out"); retrying" >&2
      sleep 5
    fi
  done
  have="$(stat -c %s "$part" 2>/dev/null || echo 0)"
  if [ "$have" != "$size" ]; then
    echo "FATAL: size mismatch file=$(basename "$out") expected=$size actual=$have" >&2
    exit 1
  fi
  mv "$part" "$out"
}

# 1. Master file.
if sha_ok "$META_DIR/exomol.all" "$MASTER_SHA256"; then
  echo "cache_hit file=exomol.all"
else
  fetch_small "$MASTER_URL" "$META_DIR/exomol.all"
fi
head -c 200 "$META_DIR/exomol.all" | grep -q '^EXOMOL.master' || {
  echo "FATAL: exomol.all is not an ExoMol master file" >&2
  exit 1
}

# 2. Every .def listed by the pinned master table.
def_count=0
while IFS=$'\t' read -r master_order mol_index formula iso_slug dataset dataset_version n_states def_url def_bytes def_sha256; do
  [ "$master_order" != "master_order" ] || continue
  target="$META_DIR/def/${iso_slug}__${dataset}.def"
  if ! sha_ok "$target" "$def_sha256"; then
    fetch_small "$def_url" "$target"
  fi
  def_count=$((def_count + 1))
done < "$RECIPE_DIR/master_datasets.tsv"
echo "def_files=$def_count"

# 3. Re-derive the selection and URLs; fail loudly on any mismatch.
python3 "$HELPER" plan --recipe "$RECIPE_DIR" --meta "$META_DIR" \
  --out "$DOWNLOAD_DIR/download_plan.tsv"

# 4. Selected .def.json and .states.bz2 payloads.
states_count=0
states_bytes=0
while IFS=$'\t' read -r kind filename url size_bytes sha256; do
  [ "$kind" != "kind" ] || continue
  case "$kind" in
    defjson)
      target="$DOWNLOAD_DIR/defjson/$filename"
      sha_ok "$target" "$sha256" || fetch_small "$url" "$target"
      ;;
    states)
      fetch_big "$url" "$DOWNLOAD_DIR/states/$filename" "$size_bytes"
      states_count=$((states_count + 1))
      states_bytes=$((states_bytes + size_bytes))
      ;;
    *)
      echo "FATAL: unknown plan kind $kind" >&2
      exit 1
      ;;
  esac
done < "$DOWNLOAD_DIR/download_plan.tsv"

if [ "$states_count" != "$EXPECTED_STATES_FILES" ] || [ "$states_bytes" != "$EXPECTED_STATES_BYTES" ]; then
  echo "FATAL: plan totals files=$states_count bytes=$states_bytes differ from pinned $EXPECTED_STATES_FILES/$EXPECTED_STATES_BYTES" >&2
  exit 1
fi

# 5. Semantic validation: sizes, pinned SHA-256, .def.json layout, full bz2
#    decode, line count equal to the .def state count, first state ID 1.
python3 "$HELPER" validate --recipe "$RECIPE_DIR" --downloads "$DOWNLOAD_DIR" \
  --out "$DOWNLOAD_DIR/realized_sha256.tsv"

echo "[$(date -Is)] download done dataset=$DATASET_ID states_files=$states_count states_bytes=$states_bytes"
