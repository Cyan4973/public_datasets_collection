#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/polyhaven_hdri_exr_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_hdri_exr_f32"
SERIES_ID="hdri_float_planes_f32"
DATA_ROOT="$REPO_ROOT/$DATA_DIR"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TOOL_DIR="$DATA_ROOT/tools/tinyexr_v1.0.12"
FILTERED_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLE_DIR="$DATA_ROOT/samples/$DATASET_ID/$SERIES_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DECODER="$TOOL_DIR/openzl_exr_decode"

mkdir -p "$FILTERED_DIR" "$INDEX_DIR" "$LOG_DIR" "$TOOL_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

export RECIPE_DIR DOWNLOAD_DIR TOOL_DIR SAMPLE_DIR FILTERED_DIR
python3 - <<'PY'
import hashlib
import os
from pathlib import Path
import shutil

recipe = Path(os.environ["RECIPE_DIR"])
download = Path(os.environ["DOWNLOAD_DIR"])
tool = Path(os.environ["TOOL_DIR"])
for line in (recipe / "selection.tsv").read_text(encoding="utf-8").splitlines()[1:]:
    kind, name, size_text, expected_md5, expected_sha256, _, _ = line.split("\t")
    path = (tool if kind == "tool" else download) / name
    if not path.is_file() or path.stat().st_size != int(size_text):
        raise SystemExit(f"missing or wrong-size pinned input: {path}")
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            md5.update(chunk); sha256.update(chunk)
    if md5.hexdigest() != expected_md5 or sha256.hexdigest() != expected_sha256:
        raise SystemExit(f"hash mismatch: {path}")
    print(f"validated input name={name} bytes={size_text} sha256={expected_sha256}")

sample_dir = Path(os.environ["SAMPLE_DIR"])
filtered_dir = Path(os.environ["FILTERED_DIR"])
if sample_dir.exists():
    shutil.rmtree(sample_dir)
sample_dir.mkdir(parents=True)
for old in filtered_dir.glob("decode_*.tsv"):
    old.unlink()
PY

c++ -std=c++11 -O2 -Wall -Wextra -pedantic \
  -DTINYEXR_USE_MINIZ=0 -I"$TOOL_DIR" \
  "$RECIPE_DIR/scripts/exr_decode.cpp" -lz -o "$DECODER.part"
mv "$DECODER.part" "$DECODER"

for source in abandoned_greenhouse_1k ph_brown_photostudio_02_8k ph_golden_gate_hills_4k; do
  "$DECODER" "$DOWNLOAD_DIR/$source.exr" "$SAMPLE_DIR" "$FILTERED_DIR/decode_$source.tsv"
done

python3 "$RECIPE_DIR/scripts/build_index.py" \
  --data-root "$DATA_ROOT" \
  --download-dir "$DOWNLOAD_DIR" \
  --filtered-dir "$FILTERED_DIR" \
  --index-dir "$INDEX_DIR" \
  --sample-dir "$SAMPLE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
