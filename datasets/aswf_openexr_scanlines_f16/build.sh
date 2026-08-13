#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/aswf_openexr_scanlines_f16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aswf_openexr_scanlines_f16"
DATA_ROOT="$REPO_ROOT/$DATA_DIR"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TOOL_DIR="$DATA_ROOT/tools/tinyexr_v1.0.12"
FILTERED_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLE_ROOT="$DATA_ROOT/samples/$DATASET_ID"
TEMP_DIR="$DATA_ROOT/extracted/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DECODER="$TOOL_DIR/openzl_exr_half_decode"

mkdir -p "$FILTERED_DIR" "$INDEX_DIR" "$LOG_DIR" "$TOOL_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

export RECIPE_DIR DOWNLOAD_DIR TOOL_DIR SAMPLE_ROOT TEMP_DIR FILTERED_DIR
python3 - <<'PY'
import hashlib,os,shutil
from pathlib import Path
recipe=Path(os.environ["RECIPE_DIR"]);download=Path(os.environ["DOWNLOAD_DIR"]);tool=Path(os.environ["TOOL_DIR"])
for line in (recipe/"selection.tsv").read_text().splitlines()[1:]:
 kind,_,name,size,identity_type,identity,expected_sha,_=line.split("\t")
 root=tool if kind=="tool" else download/"metadata" if kind in {"license","provenance"} else download
 path=root/name
 if not path.is_file() or path.stat().st_size!=int(size):raise SystemExit(f"missing/wrong size {path}")
 blob=hashlib.sha1();sha=hashlib.sha256()
 if identity_type=="git_blob_sha1":blob.update(f"blob {size}\0".encode())
 with path.open("rb") as h:
  while chunk:=h.read(8*1024*1024):blob.update(chunk);sha.update(chunk)
 actual=blob.hexdigest() if identity_type=="git_blob_sha1" else sha.hexdigest()
 if actual!=identity or sha.hexdigest()!=expected_sha:raise SystemExit(f"hash mismatch {path}")
for key in ("SAMPLE_ROOT","TEMP_DIR"):
 p=Path(os.environ[key]);shutil.rmtree(p,ignore_errors=True);p.mkdir(parents=True)
for p in Path(os.environ["FILTERED_DIR"]).glob("decode_*.tsv"):p.unlink()
PY

c++ -std=c++11 -O2 -Wall -Wextra -pedantic -DTINYEXR_USE_MINIZ=0 \
  -I"$TOOL_DIR" "$RECIPE_DIR/scripts/exr_half_decode.cpp" -lz -o "$DECODER.part"
mv "$DECODER.part" "$DECODER"
for source in Blobbies CandleGlass Carrots Desk MtTamWest PrismsLenses StillLife Tree;do
  "$DECODER" "$DOWNLOAD_DIR/$source.exr" "$TEMP_DIR" "$FILTERED_DIR/decode_$source.tsv"
done
python3 "$RECIPE_DIR/scripts/build_index.py" --data-root "$DATA_ROOT" --download-dir "$DOWNLOAD_DIR" \
  --filtered-dir "$FILTERED_DIR" --index-dir "$INDEX_DIR" --sample-root "$SAMPLE_ROOT" --temp-dir "$TEMP_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
