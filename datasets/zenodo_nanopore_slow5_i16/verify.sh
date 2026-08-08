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
RAW_INVENTORY="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/raw_inventory.tsv"
STATS="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
INDEX="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SOURCE_SHA256="8d1e9caa3712780283fb66609268027e837992de0ba7e106a7a6061f72b34e4a"
PINNED_TOOL_COMMIT="f73fc6b8f65813b7b1f5d787934d790e5d58b90f"
PINNED_LIB_COMMIT="e4bf785d696ce70eec4e54c37cbbdda19c25cc50"
BYTE_CAP=900000000

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

[[ -f "$SOURCE" && -x "$SLOW5TOOLS" && -f "$SLOW5LIB" && -x "$EXTRACTOR" ]] || {
  echo "missing source, proven decoder, or built extractor" >&2
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
"$EXTRACTOR" verify "$SOURCE" "$SAMPLES_DIR" "$RAW_INVENTORY" "$BYTE_CAP"

SLOW5TOOLS_SHA256="$(sha256sum "$SLOW5TOOLS" | awk '{print $1}')"
SLOW5LIB_SHA256="$(sha256sum "$SLOW5LIB" | awk '{print $1}')"
python3 "$RECIPE_DIR/scripts/metadata.py" verify \
  --raw-inventory "$RAW_INVENTORY" \
  --samples-dir "$SAMPLES_DIR" \
  --source "$SOURCE" \
  --index "$INDEX" \
  --stats "$STATS" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --slow5tools-sha256 "$SLOW5TOOLS_SHA256" \
  --slow5lib-sha256 "$SLOW5LIB_SHA256"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
