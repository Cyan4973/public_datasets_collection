#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aswf_openexr_scanlines_f16"
DATA_ROOT="$REPO_ROOT/$DATA_DIR"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TOOL_DIR="$DATA_ROOT/tools/tinyexr_v1.0.12"
FILTERED_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLE_ROOT="$DATA_ROOT/samples/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DECODER="$TOOL_DIR/openzl_exr_half_decode"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export DATA_ROOT FILTERED_DIR INDEX_DIR
python3 - <<'PY'
import hashlib,json,os
from pathlib import Path
data=Path(os.environ["DATA_ROOT"]);filtered=Path(os.environ["FILTERED_DIR"]);index=Path(os.environ["INDEX_DIR"])
stats=json.loads((filtered/"ingest_stats.json").read_text());rows=[json.loads(x) for x in (index/"samples.jsonl").read_text().splitlines() if x]
if stats["sample_count"]!=27 or stats["primary_values"]!=22462336 or stats["primary_bytes"]!=44924672:raise SystemExit(f"stats mismatch {stats}")
if len(rows)!=27:raise SystemExit("index count mismatch")
for r in rows:
 p=data/r["sample_path"]
 if r["bit_width"]!=16 or r["endianness"]!="little" or p.stat().st_size!=r["sample_size_bytes"]:raise SystemExit(f"metadata mismatch {r}")
 d=hashlib.sha256()
 with p.open("rb") as h:
  while chunk:=h.read(8*1024*1024):d.update(chunk)
 if d.hexdigest()!=r["sha256"]:raise SystemExit(f"hash mismatch {p}")
print(f"verified index samples={len(rows)} bytes={stats['primary_bytes']}")
PY

[[ -x "$DECODER" ]]||{ echo "missing decoder $DECODER" >&2;exit 1; }
TMP_DIR="$(mktemp -d "$DATA_ROOT/verify_exr_half.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/out"
for source in Blobbies CandleGlass Carrots Desk MtTamWest PrismsLenses StillLife Tree;do
 "$DECODER" "$DOWNLOAD_DIR/$source.exr" "$TMP_DIR/out" "$TMP_DIR/$source.tsv"
done
rebuilt=0
for path in "$TMP_DIR"/out/*.bin;do
 name="$(basename "$path")";accepted="$(find "$SAMPLE_ROOT" -type f -name "$name" -print -quit)"
 [[ -n "$accepted" ]]||{ echo "unexpected rebuilt $name" >&2;exit 1; }
 cmp --silent "$path" "$accepted"||{ echo "byte mismatch $name" >&2;exit 1; };rebuilt=$((rebuilt+1))
done
[[ "$rebuilt" -eq 27 ]]||{ echo "rebuilt count $rebuilt" >&2;exit 1; }
echo "verified independent_redecode_samples=$rebuilt"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
