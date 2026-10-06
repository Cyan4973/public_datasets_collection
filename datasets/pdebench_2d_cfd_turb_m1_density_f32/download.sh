#!/usr/bin/env bash
# Fetch only the pinned byte ranges of the PDEBench 2D_CFD_Turb_M1.0 training
# HDF5 file (DaRUS file 164686, 88,080,392,528 bytes): two 2 KiB metadata
# ranges plus 40 whole /density trajectories of 22,020,096 bytes each.
# The 88 GB file itself is never requested.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="pdebench_2d_cfd_turb_m1_density_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/pdebench_density.py"
PINS="$RECIPE_DIR/trajectory_sha256.tsv"
CATALOG_URL='https://darus.uni-stuttgart.de/api/datasets/:persistentId/?persistentId=doi:10.18419/darus-2986'
# The access API answers with a 303 to a presigned s3.tik.uni-stuttgart.de URL
# that expires; every request goes through the API again with --location.
FILE_URL='https://darus.uni-stuttgart.de/api/access/datafile/164686'
UA="openzl-public-datasets-pdebench-cfd-density/1.0"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-40}"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

if [ -f "$PINS" ]; then
  ETAG_FLAG=""
  PIN_ARGS=(--pins "$PINS")
  echo "trajectory SHA-256 pins: $PINS"
else
  # Without content pins the storage ETag is the object identity proof.
  ETAG_FLAG="--require-etag"
  PIN_ARGS=()
  echo "trajectory SHA-256 pins: absent (first acquisition); observed hashes go to trajectory_sha256.observed.tsv"
fi

file_bytes() { wc -c < "$1" | tr -d ' '; }

# 1. Live catalog: license, release state and exact file identity.
catalog="$DOWNLOAD_DIR/darus_2986_dataset.json"
rm -f "$catalog.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 5 --retry-all-errors --connect-timeout 60 \
  --max-time 300 --max-filesize 20000000 --user-agent "$UA" \
  --header "Accept: application/json" --output "$catalog.part" "$CATALOG_URL"
mv "$catalog.part" "$catalog"
python3 "$PY" catalog "$catalog"

# Fetch bytes [first, last] of the remote file into $out. Resumes from a
# partial "$out.part" by requesting only the missing tail; every response must
# be HTTP 206 with exactly the requested Content-Range before its bytes are
# appended. curl's -C cannot be combined with -r, hence the manual loop.
fetch_range() {
  local first="$1" last="$2" out="$3"
  local want=$((last - first + 1))
  local part="$out.part" chunk="$out.chunk" hdr="$out.hdr"
  local attempt=0 have from rc
  while :; do
    have=0
    [ -f "$part" ] && have="$(file_bytes "$part")"
    if [ "$have" -gt "$want" ]; then
      echo "discarding oversized partial $part ($have > $want bytes)"
      rm -f "$part"
      have=0
    fi
    [ "$have" -eq "$want" ] && break
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: $out still incomplete after $MAX_ATTEMPTS attempts ($have/$want bytes)" >&2
      return 1
    fi
    from=$((first + have))
    rm -f "$chunk" "$hdr"
    set +e
    curl --fail --silent --show-error --location \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((last - from + 1))" --user-agent "$UA" \
      --range "$from-$last" --dump-header "$hdr" --output "$chunk" "$FILE_URL"
    rc=$?
    set -e
    if [ -s "$chunk" ]; then
      # shellcheck disable=SC2086
      if ! python3 "$PY" range-headers "$hdr" "$from" "$last" $ETAG_FLAG; then
        rm -f "$chunk" "$hdr"
        echo "FATAL: server did not return the requested byte range $from-$last" >&2
        return 1
      fi
      cat "$chunk" >> "$part"
    fi
    rm -f "$chunk"
    if [ "$rc" -ne 0 ]; then
      echo "curl exit $rc for $(basename "$out") at byte $from (attempt $attempt); resuming"
      sleep $(( attempt < 6 ? attempt * 5 : 30 ))
    fi
  done
  rm -f "$hdr"
  mv "$part" "$out"
}

# 2. HDF5 metadata: the 2,048-byte prefix before /density (superblock, root
#    group, density/pressure/Vx object headers) and the 2,048-byte metadata
#    island at 66,060,290,048 (root link-name heap and the remaining object
#    headers). Both are SHA-256 pinned; the parser then asserts the layout.
prefix="$DOWNLOAD_DIR/hdf5_prefix.bin"
island="$DOWNLOAD_DIR/hdf5_island.bin"
[ -s "$prefix" ] || fetch_range 0 2047 "$prefix"
[ -s "$island" ] || fetch_range 66060290048 66060292095 "$island"
if ! python3 "$PY" metadata "$prefix" "$island"; then
  rm -f "$prefix" "$island"
  echo "FATAL: HDF5 metadata does not match the pinned /density layout" >&2
  exit 1
fi

# 3. The 40 evenly spaced trajectories 0, 25, ..., 975 of /density, each one
#    contiguous 21 x 512 x 512 little-endian float32 block.
observed="$DOWNLOAD_DIR/trajectory_sha256.observed.tsv"
printf 'trajectory_index\tbyte_start\tbyte_end\tsha256\n' > "$observed"
fetched=0
cached=0
while IFS=$'\t' read -r index first last name; do
  out="$DOWNLOAD_DIR/$name"
  if [ -s "$out" ]; then
    if python3 "$PY" trajectory "$out" "$index" ${PIN_ARGS[@]+"${PIN_ARGS[@]}"} --observed "$observed"; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached $name failed validation; fetching it again"
    rm -f "$out"
  fi
  echo "[$(date -Is)] fetching trajectory $index bytes $first-$last -> $name"
  fetch_range "$first" "$last" "$out"
  if ! python3 "$PY" trajectory "$out" "$index" ${PIN_ARGS[@]+"${PIN_ARGS[@]}"} --observed "$observed"; then
    rm -f "$out"
    echo "FATAL: trajectory $index failed semantic validation" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
done < <(python3 "$PY" selection)

count=$(( $(wc -l < "$observed") - 1 ))
if [ "$count" -ne 40 ]; then
  echo "FATAL: expected 40 validated trajectories, found $count" >&2
  exit 1
fi
echo "trajectories validated=$count fetched=$fetched cached=$cached pinned=$([ -f "$PINS" ] && echo yes || echo no)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
