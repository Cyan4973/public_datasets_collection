#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_nsclc_radiomics_ct_i16"
SERIES_ID="ct_slice_pixels_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
python3 "$REPO_ROOT/tools/numeric16_extract.py" build --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" --format dicom
python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$DATASET_ID" "$SERIES_ID"
from __future__ import annotations

import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
data_dir = sys.argv[2]
dataset_id = sys.argv[3]
series_id = sys.argv[4]
index_path = repo_root / data_dir / "index" / dataset_id / "samples.jsonl"
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("series_id") != series_id:
        raise SystemExit(f"unexpected series_id: {row.get('series_id')}")
    if row.get("numeric_kind") != "uint" or row.get("bit_width") != 16:
        raise SystemExit(f"non-uint16 DICOM sample: {row.get('sample_path')}")
print("uint16_series_validation=ok")
PY
