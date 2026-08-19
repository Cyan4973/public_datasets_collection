#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_lora24_indoor_rssi_i8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE="https://zenodo.org/api/records/7106074/files"
UA="openzl-public-datasets/1.0"

fetch_pinned() {
  local key="$1" size="$2" md5="$3"
  local output="$DOWNLOAD_DIR/$key"
  if [[ -f "$output" ]] && [[ "$(stat -c %s "$output")" == "$size" ]] && \
     [[ "$(md5sum "$output" | awk '{print $1}')" == "$md5" ]] && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse file=$key bytes=$size"
    return
  fi
  rm -f "$output.part"
  curl --globoff --fail --silent --show-error --location --retry 5 \
    --retry-all-errors --retry-delay 5 --connect-timeout 30 --speed-limit 1024 \
    --speed-time 120 --max-time 1800 --max-filesize 100000000 \
    --user-agent "$UA" --output "$output.part" "$BASE/$key/content"
  if [[ "$(stat -c %s "$output.part")" != "$size" ]] || \
     [[ "$(md5sum "$output.part" | awk '{print $1}')" != "$md5" ]]; then
    echo "FATAL: identity mismatch for $key" >&2
    exit 1
  fi
  mv "$output.part" "$output"
}

fetch_pinned "Test_Exhaustive_experiment.csv" 7316621 a9fb46df3d57f6edb345d7c1dd0da5ab
fetch_pinned "Test_long_run.csv" 18107378 f027322df443cff626b675ce3397587d
fetch_pinned "Readme" 228 f5f7ea0cbac65993d95c9f96ce9dfa56
fetch_pinned "plot_Exhaustive_experiment.py" 20045 7f108ff4259a80b64509a8a458a350bc
fetch_pinned "plot_long_run_test.py" 15157 7f70427a105bd83a5b96c70bb366e394

curl --globoff --fail --silent --show-error --location --retry 5 \
  --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 240 \
  --max-filesize 1000000 --user-agent "$UA" \
  --output "$DOWNLOAD_DIR/zenodo_record_7106074.json" \
  "https://zenodo.org/api/records/7106074"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path


root = Path(os.environ["DOWNLOAD_DIR"])
expected = {
    "Test_Exhaustive_experiment.csv": (7_316_621, "a9fb46df3d57f6edb345d7c1dd0da5ab"),
    "Test_long_run.csv": (18_107_378, "f027322df443cff626b675ce3397587d"),
    "Readme": (228, "f5f7ea0cbac65993d95c9f96ce9dfa56"),
    "plot_Exhaustive_experiment.py": (20_045, "7f108ff4259a80b64509a8a458a350bc"),
    "plot_long_run_test.py": (15_157, "7f70427a105bd83a5b96c70bb366e394"),
}
headers = {
    "Test_Exhaustive_experiment.csv": ["tmst", "chan", "freq", "stat", "modu", "datr", "bw", "codr", "rssi", "lsnr", "size", "data", "real_cr", "time"],
    "Test_long_run.csv": ["tmst", "chan", "freq", "stat", "modu", "datr", "bw", "codr", "rssi", "lsnr", "size", "data", "power", "real_cr", "time"],
}


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


record_path = root / "zenodo_record_7106074.json"
record = json.loads(record_path.read_text(encoding="utf-8"))
metadata = record.get("metadata", {})
if str(record.get("id")) != "7106074" or not isinstance(metadata, dict):
    raise SystemExit("wrong Zenodo record")
if metadata.get("doi") != "10.5281/zenodo.7106074" or metadata.get("license") != {"id": "cc-by-4.0"}:
    raise SystemExit("DOI or CC BY 4.0 evidence changed")
inventory = {"dataset_id": "zenodo_lora24_indoor_rssi_i8", "record_id": 7106074, "license": "CC-BY-4.0", "files": {}}
for name, (size, md5) in expected.items():
    path = root / name
    if path.stat().st_size != size or digest(path, "md5") != md5:
        raise SystemExit(f"pinned identity mismatch: {name}")
    if name in headers:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            actual_header = next(csv.reader(handle), None)
        if actual_header != headers[name]:
            raise SystemExit(f"header mismatch {name}: {actual_header}")
    inventory["files"][name] = {"size_bytes": size, "md5": md5, "sha256": digest(path, "sha256")}
inventory["metadata"] = {"size_bytes": record_path.stat().st_size, "sha256": digest(record_path, "sha256")}
(root / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(inventory, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
