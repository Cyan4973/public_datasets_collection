#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/evaluation/aras_blender_openexr_eval"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aras_blender_openexr_eval"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
DOWNLOAD_DIR="$EVAL_ROOT/downloads"
TOOL_DIR="$EVAL_ROOT/tools/tinyexr_v1.0.12"
FILTERED_DIR="$EVAL_ROOT/filtered"
INDEX_DIR="$EVAL_ROOT/index"
SAMPLE_DIR="$EVAL_ROOT/samples"
LOG_DIR="$EVAL_ROOT/logs"
DECODER="$TOOL_DIR/openzl_aras_exr_decode"

mkdir -p "$FILTERED_DIR" "$INDEX_DIR" "$LOG_DIR" "$TOOL_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] evaluation build start dataset=$DATASET_ID"

python3 - "$RECIPE_DIR/selection.tsv" "$DOWNLOAD_DIR" "$TOOL_DIR" <<'PY'
import csv
import hashlib
import sys
from pathlib import Path

selection, download, tool = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rows = list(csv.DictReader(selection.open(encoding="utf-8"), delimiter="\t"))
if len(rows) != 9:
    raise SystemExit("expected eight EXRs and one tool")
for row in rows:
    path = (tool if row["kind"] == "tool" else download) / row["name"]
    if not path.is_file() or path.stat().st_size != int(row["size_bytes"]):
        raise SystemExit(f"missing or wrong-size pinned input: {path}")
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
    if md5.hexdigest() != row["md5"] or sha256.hexdigest() != row["sha256"]:
        raise SystemExit(f"hash mismatch: {path}")
    print(f"validated input name={path.name} bytes={path.stat().st_size}")
PY

rm -rf "$SAMPLE_DIR"
rm -f "$FILTERED_DIR"/decode_*.tsv "$FILTERED_DIR/ingest_stats.json" "$INDEX_DIR/samples.jsonl"
mkdir -p "$SAMPLE_DIR/blender_exr_channel_plane_f16" \
  "$SAMPLE_DIR/blender_exr_channel_plane_f32"

c++ -std=c++11 -O2 -Wall -Wextra -pedantic \
  -DTINYEXR_USE_MINIZ=0 -I"$TOOL_DIR" \
  "$RECIPE_DIR/scripts/exr_decode.cpp" -lz -o "$DECODER.part"
mv "$DECODER.part" "$DECODER"

while IFS=$'\t' read -r kind name _rest; do
  [[ "$kind" == "kind" ]] && continue
  [[ "$kind" == "exr" ]] || continue
  stem="${name%.exr}"
  "$DECODER" "$DOWNLOAD_DIR/$name" "$SAMPLE_DIR" "$FILTERED_DIR/decode_$stem.tsv"
done < "$RECIPE_DIR/selection.tsv"

python3 "$RECIPE_DIR/scripts/build_index.py" \
  --selection "$RECIPE_DIR/selection.tsv" \
  --eval-root "$EVAL_ROOT"

echo "[$(date -Is)] evaluation build done dataset=$DATASET_ID"
