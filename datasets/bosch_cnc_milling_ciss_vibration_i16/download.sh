#!/usr/bin/env bash
# Download the pinned Bosch CNC_Machining vibration runs of machines M01 and M02.
#
# Resources (all anonymous, no GitHub API calls):
#   * 1,163 HDF5 run files listed in sources.tsv, fetched from
#     raw.githubusercontent.com at commit d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1
#     and checked against their pinned byte size and git blob SHA-1
#     (sha1("blob <size>\0" + bytes)), which is exactly the object id in the
#     repository tree at that commit.
#   * README.md at the same commit (CC BY 4.0 data-license statement), checked
#     against its git blob SHA-1.
# Files are small (133 KB .. 1.6 MB), so each is fetched whole into a .part file
# and renamed only after verification; re-runs skip verified files (resume at
# file granularity).  After the transfer, every file's HDF5 metadata is parsed
# (no chunk decompression) and must match the pinned shape and container dtype.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="bosch_cnc_milling_ciss_vibration_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
COMMIT="d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1"
RAW_BASE="https://raw.githubusercontent.com/boschresearch/CNC_Machining/$COMMIT"
UA="openzl-public-datasets/1.0 ($DATASET_ID)"
EXPECTED_FILES=1163
EXPECTED_BYTES=642164273
README_SIZE=3201
README_BLOB_SHA1="76e64e205cf889ae10a2ffdbb9c29e4205cb1738"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID commit=$COMMIT data_root=$DATA_ROOT"

blob_sha1() {
  # git blob object id: sha1 over "blob <size>\0" followed by the file bytes
  { printf 'blob %s\0' "$(stat -c %s "$1")"; cat "$1"; } | sha1sum | awk '{print $1}'
}

valid_file() {
  local file="$1" size="$2" sha="$3"
  [[ -f "$file" ]] || return 1
  [[ "$(stat -c %s "$file")" == "$size" ]] || return 1
  [[ "$(blob_sha1 "$file")" == "$sha" ]]
}

fetch_verified() {
  local url="$1" target="$2" size="$3" sha="$4"
  local attempt
  if valid_file "$target" "$size" "$sha"; then
    return 0
  fi
  mkdir -p "$(dirname "$target")"
  for attempt in 1 2 3 4 5; do
    rm -f "$target.part"
    if curl --globoff --fail --silent --show-error --location \
         --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
         --speed-limit 1024 --speed-time 120 --max-filesize 5000000 \
         --user-agent "$UA" --output "$target.part" "$url"; then
      if valid_file "$target.part" "$size" "$sha"; then
        mv "$target.part" "$target"
        return 0
      fi
      echo "identity mismatch attempt=$attempt url=$url got_size=$(stat -c %s "$target.part" 2>/dev/null || echo 0)" >&2
    else
      echo "curl failed attempt=$attempt url=$url" >&2
    fi
    sleep $((attempt * 5))
  done
  rm -f "$target.part"
  echo "FATAL: could not fetch a verified copy of $url" >&2
  return 1
}

# ---------------------------------------------------------------- license evidence
fetch_verified "$RAW_BASE/README.md" "$DOWNLOAD_DIR/README.md" "$README_SIZE" "$README_BLOB_SHA1"
grep -qF 'located in the directory [data](data) are licensed under a [Creative Commons Attribution 4.0 International' \
  "$DOWNLOAD_DIR/README.md" || { echo "FATAL: upstream README lacks the CC BY 4.0 data statement" >&2; exit 1; }
grep -qF '(CC-BY-4.0)' "$DOWNLOAD_DIR/README.md" || { echo "FATAL: upstream README lacks CC-BY-4.0" >&2; exit 1; }
echo "license evidence ok: README.md blob=$README_BLOB_SHA1 states CC BY 4.0 for data/"

# ------------------------------------------------------------------- run files
count=0
bytes=0
fetched=0
reused=0
header="path	size_bytes	git_blob_sha1	machine	operation	label	timeframe	run_index	rows	cols	container_dtype"
[[ "$(head -n 1 "$RECIPE_DIR/sources.tsv")" == "$header" ]] || { echo "FATAL: sources.tsv header changed" >&2; exit 1; }
while IFS=$'\t' read -r path size sha machine operation label timeframe run_index rows cols dtype; do
  [[ "$path" == "path" ]] && continue
  [[ "$path" =~ ^data/M0[12]/OP[0-9]{2}/(good|bad)/M0[12]_[A-Z][a-z]{2}_20[0-9]{2}_OP[0-9]{2}_[0-9]{3}\.h5$ ]] || {
    echo "FATAL: unexpected path in sources.tsv: $path" >&2; exit 1; }
  target="$DOWNLOAD_DIR/$path"
  if valid_file "$target" "$size" "$sha"; then
    reused=$((reused + 1))
  else
    fetch_verified "$RAW_BASE/$path" "$target" "$size" "$sha"
    fetched=$((fetched + 1))
  fi
  count=$((count + 1))
  bytes=$((bytes + size))
  if (( count % 100 == 0 )); then
    echo "[$(date -Is)] progress files=$count/$EXPECTED_FILES bytes=$bytes fetched=$fetched reused=$reused"
  fi
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_FILES" ]] || { echo "FATAL: file count $count != $EXPECTED_FILES" >&2; exit 1; }
[[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "FATAL: byte total $bytes != $EXPECTED_BYTES" >&2; exit 1; }
echo "transfer ok files=$count bytes=$bytes fetched=$fetched reused=$reused"

# Reject stray files (e.g. from an older selection) so build sees exactly the pinned set.
stray="$(find "$DOWNLOAD_DIR/data" -type f \( -name '*.part' -o -name '*.h5' \) | wc -l)"
[[ "$stray" == "$EXPECTED_FILES" ]] || { echo "FATAL: $stray files under downloads/data, expected $EXPECTED_FILES" >&2; exit 1; }

# ------------------------------------------------------- semantic HDF5 validation
PYTHONDONTWRITEBYTECODE=1 python3 "$RECIPE_DIR/scripts/validate_download.py" \
  --sources "$RECIPE_DIR/sources.tsv" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
