#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="worldclim_tavg_10m"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import json
import os
from pathlib import Path
import hashlib

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

archive = download_dir / "wc2.1_10m_tavg.zip"
expected_bytes = 37364656
expected_sha256 = "5e567dcfe94379b94229492849ce91078b1c6e5210aaf435fba449fae6b95405"
expected_sample_count = 6
expected_value_count = 2160 * 8
expected_sample_bytes = expected_value_count * 4

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

if not archive.is_file():
    raise SystemExit(f"missing archive: {archive}")
if archive.stat().st_size != expected_bytes:
    raise SystemExit(f"archive size mismatch: {archive.stat().st_size} != {expected_bytes}")
if sha256_file(archive) != expected_sha256:
    raise SystemExit("archive sha256 mismatch")

stats_path = filter_dir / "ingest_stats.json"
index_path = index_dir / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["sample_count"] != expected_sample_count:
    raise SystemExit(f"unexpected sample_count in stats: {stats['sample_count']}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != expected_sample_count:
    raise SystemExit(f"unexpected index row count: {len(rows)}")

for row in rows:
    if row["dataset_id"] != "worldclim_tavg_10m" or row["series_id"] != "worldclim_tavg_f32":
        raise SystemExit(f"unexpected row ids: {row}")
    if row["numeric_kind"] != "float" or row["bit_width"] != 32 or row["endianness"] != "little":
        raise SystemExit(f"unexpected row metadata: {row}")
    if row["value_count"] != expected_value_count:
        raise SystemExit(f"unexpected value_count: {row['value_count']}")
    if row["sample_size_bytes"] != expected_sample_bytes:
        raise SystemExit(f"unexpected sample_size_bytes: {row['sample_size_bytes']}")
    sample_path = data_root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    if sample_path.stat().st_size != expected_sample_bytes:
        raise SystemExit(f"bad sample byte size for {sample_path}: {sample_path.stat().st_size}")

print(f"verified_samples={len(rows)}")
print(f"verified_archive={archive}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
