#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_nanopore_slow5_i16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_nanopore_slow5_i16"
SOURCE="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/SIRV_from_MNXKXX240359.blow5"
TOOL_SOURCE="$REPO_ROOT/$DATA_DIR/tools/slow5tools_probe/source"
SLOW5TOOLS="$TOOL_SOURCE/slow5tools"
SLOW5LIB="$TOOL_SOURCE/slow5lib/lib/libslow5.a"
EXTRACTOR="$REPO_ROOT/$DATA_DIR/tools/$DATASET_ID/nanopore_extract"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID/nanopore_raw_signal_i16"
FILTERED_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl"
RAW_INVENTORY="$FILTERED_DIR/raw_inventory.tsv"
STATS="$FILTERED_DIR/ingest_stats.json"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SOURCE_SHA256="8d1e9caa3712780283fb66609268027e837992de0ba7e106a7a6061f72b34e4a"
PINNED_TOOL_COMMIT="f73fc6b8f65813b7b1f5d787934d790e5d58b90f"
PINNED_LIB_COMMIT="e4bf785d696ce70eec4e54c37cbbdda19c25cc50"
BYTE_CAP=900000000

mkdir -p "$LOG_DIR" "$REPO_ROOT/$DATA_DIR/tools/$DATASET_ID"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

for tool in cc git sha256sum python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing required local tool: $tool" >&2; exit 1; }
done
[[ -f "$SOURCE" && -x "$SLOW5TOOLS" && -f "$SLOW5LIB" ]] || {
  echo "missing validated source or proven slow5tools build" >&2
  exit 1
}
[[ "$(sha256sum "$SOURCE" | awk '{print $1}')" == "$SOURCE_SHA256" ]] || {
  echo "pinned BLOW5 source SHA256 mismatch" >&2
  exit 1
}
[[ "$(git -C "$TOOL_SOURCE" rev-parse HEAD)" == "$PINNED_TOOL_COMMIT" ]] || {
  echo "slow5tools checkout is not the pinned commit" >&2
  exit 1
}
[[ "$(git -C "$TOOL_SOURCE/slow5lib" rev-parse HEAD)" == "$PINNED_LIB_COMMIT" ]] || {
  echo "slow5lib checkout is not the pinned commit" >&2
  exit 1
}
"$SLOW5TOOLS" quickcheck "$SOURCE"

cc -O2 -std=c11 -Wall -Wextra -Werror \
  -I "$TOOL_SOURCE/slow5lib/include" \
  "$RECIPE_DIR/scripts/nanopore_extract.c" "$SLOW5LIB" -lm -lz -o "$EXTRACTOR"

# These are generated outputs owned by this recipe; rebuild them from the pinned source.
rm -rf "$SAMPLES_DIR"
rm -f "$INDEX" "$RAW_INVENTORY" "$STATS"
mkdir -p "$SAMPLES_DIR" "$FILTERED_DIR" "$(dirname "$INDEX")"

"$EXTRACTOR" extract "$SOURCE" "$SAMPLES_DIR" "$RAW_INVENTORY" "$BYTE_CAP"
SLOW5TOOLS_SHA256="$(sha256sum "$SLOW5TOOLS" | awk '{print $1}')"
SLOW5LIB_SHA256="$(sha256sum "$SLOW5LIB" | awk '{print $1}')"
python3 "$RECIPE_DIR/scripts/metadata.py" build \
  --raw-inventory "$RAW_INVENTORY" \
  --samples-dir "$SAMPLES_DIR" \
  --source "$SOURCE" \
  --index "$INDEX" \
  --stats "$STATS" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --slow5tools-sha256 "$SLOW5TOOLS_SHA256" \
  --slow5lib-sha256 "$SLOW5LIB_SHA256"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
