#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export DATA_ROOT FILTERED_DIR INDEX_DIR SAMPLE_DIR
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

data_root = Path(os.environ["DATA_ROOT"])
filtered = Path(os.environ["FILTERED_DIR"])
index = Path(os.environ["INDEX_DIR"])
samples = Path(os.environ["SAMPLE_DIR"])
stats = json.loads((filtered / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (index / "samples.jsonl").read_text().splitlines() if line]
if stats["source_count"] != 3 or stats["sample_count"] != 9:
    raise SystemExit(f"unexpected stats: {stats}")
if stats["primary_values"] != 127401984 or stats["primary_bytes"] != 509607936:
    raise SystemExit(f"unexpected aggregate geometry: {stats}")
if len(rows) != 9:
    raise SystemExit(f"expected nine index rows, found {len(rows)}")
seen = set()
for row in rows:
    if row["numeric_kind"] != "float" or row["bit_width"] != 32 or row["endianness"] != "little":
        raise SystemExit(f"type mismatch: {row}")
    if row["channel"] not in {"R", "G", "B"}:
        raise SystemExit(f"unexpected or constant channel retained: {row}")
    path = data_root / row["sample_path"]
    if path.parent != samples or path.stat().st_size != row["sample_size_bytes"]:
        raise SystemExit(f"sample path/size mismatch: {row}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024): digest.update(chunk)
    if digest.hexdigest() != row["sha256"]:
        raise SystemExit(f"sample hash mismatch: {path}")
    key = (row["source_path"], row["channel"])
    if key in seen: raise SystemExit(f"duplicate source/channel: {key}")
    seen.add(key)
print(f"verified index samples={len(rows)} primary_bytes={stats['primary_bytes']}")
PY

[[ -x "$DECODER" ]] || { echo "missing decoder: $DECODER" >&2; exit 1; }
TMP_DIR="$(mktemp -d "$DATA_ROOT/verify_exr.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/samples"
for source in abandoned_greenhouse_1k ph_brown_photostudio_02_8k ph_golden_gate_hills_4k; do
  "$DECODER" "$DOWNLOAD_DIR/$source.exr" "$TMP_DIR/samples" "$TMP_DIR/$source.tsv"
done

rebuilt_count=0
for rebuilt in "$TMP_DIR"/samples/*.bin; do
  accepted="$SAMPLE_DIR/$(basename "$rebuilt")"
  [[ -f "$accepted" ]] || { echo "unexpected rebuilt sample: $rebuilt" >&2; exit 1; }
  cmp --silent "$rebuilt" "$accepted" || { echo "re-decode mismatch: $rebuilt" >&2; exit 1; }
  rebuilt_count=$((rebuilt_count + 1))
done
[[ "$rebuilt_count" -eq 9 ]] || { echo "expected nine rebuilt samples, found $rebuilt_count" >&2; exit 1; }

echo "verified independent_redecode_samples=$rebuilt_count"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
