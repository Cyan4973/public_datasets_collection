#!/usr/bin/env sh
# Accepted recipe independent verification step.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="nasa_naif_de440s_spk_coefficients_f64"
INPUT="${DATA_DIR}/downloads/${DATASET_ID}/de440s.bsp"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"

RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"
mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  status=$?
  trap - EXIT
  cp "${LOG_FILE}" "${LATEST_LOG}"
  exit "${status}"
}
trap sync_latest_log EXIT

python3 - \
  "${SCRIPT_DIR}/scripts/spk_extract.py" \
  "${INPUT}" \
  "${DATA_DIR}" \
  "${SAMPLES_ROOT}" \
  "${INDEX_ROOT}/samples.jsonl" \
  "${FILTERED_ROOT}/segment_stats.json" \
  >>"${LOG_FILE}" 2>&1 <<'PY'
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import statistics
import struct
import sys

module_path, input_arg, data_arg, samples_arg, index_arg, stats_arg = sys.argv[1:]
spec = importlib.util.spec_from_file_location("spk_extract", module_path)
if spec is None or spec.loader is None:
    raise SystemExit("could not load SPK decoder")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

input_path = Path(input_arg)
data_root = Path(data_arg)
samples_root = Path(samples_arg)
index_path = Path(index_arg)
stats_path = Path(stats_arg)

if not input_path.is_file():
    raise SystemExit(f"missing source kernel: {input_path}")
if not index_path.is_file() or not stats_path.is_file():
    raise SystemExit("missing build index or segment stats")

scan = module.scan_spk(input_path)
expected = {}
for segment in scan["segments"]:
    sample_name = module.sample_name(segment)
    path = samples_root / module.SERIES_ID / sample_name
    expected[sample_name] = (segment, path)

records = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(records) != len(expected):
    raise SystemExit(f"index count {len(records)} != decoded segment count {len(expected)}")

seen = set()
counts = []
total_bytes = 0
for record in records:
    if record.get("dataset_id") != module.DATASET_ID or record.get("series_id") != module.SERIES_ID:
        raise SystemExit(f"wrong dataset/series in index: {record}")
    name = Path(record["sample_path"]).name
    if name in seen or name not in expected:
        raise SystemExit(f"unexpected or duplicate sample {name}")
    seen.add(name)
    segment, path = expected[name]
    if path.resolve() != (data_root / record["sample_path"]).resolve():
        raise SystemExit(f"sample path mismatch for {name}")
    raw = path.read_bytes()
    expected_count = len(segment["coefficients"])
    if len(raw) != expected_count * 8:
        raise SystemExit(f"wrong byte size for {path}")
    values = [item[0] for item in struct.iter_unpack("<d", raw)]
    if values != segment["coefficients"]:
        raise SystemExit(f"stored coefficients differ from source decode for {path}")
    if not all(math.isfinite(value) for value in values):
        raise SystemExit(f"non-finite coefficient in {path}")
    if min(values) == max(values):
        raise SystemExit(f"constant coefficient sample {path}")
    if record.get("numeric_kind") != "float" or record.get("bit_width") != 64:
        raise SystemExit(f"wrong numeric metadata for {path}")
    if record.get("endianness") != "little" or record.get("element_size_bytes") != 8:
        raise SystemExit(f"wrong storage metadata for {path}")
    if record.get("value_count") != expected_count or record.get("sample_size_bytes") != len(raw):
        raise SystemExit(f"wrong index counts for {path}")
    counts.append(expected_count)
    total_bytes += len(raw)

if set(expected) != seen:
    raise SystemExit("not every decoded type-2 segment has a sample")
if sum(counts) < 10_000 and total_bytes < 102_400:
    raise SystemExit("primary output is below the aggregate floor")
if statistics.median(counts) < 1_000:
    raise SystemExit("median natural sample is below 1,000 values")
if total_bytes > 1_000_000_000:
    raise SystemExit("primary output exceeds 1 GB")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("primary_value_count") != sum(counts) or stats.get("primary_sample_bytes") != total_bytes:
    raise SystemExit("build stats do not match independently decoded source")

print(f"verified samples={len(counts)} values={sum(counts)} bytes={total_bytes} median_values={statistics.median(counts)}")
PY

cat "${LOG_FILE}"
