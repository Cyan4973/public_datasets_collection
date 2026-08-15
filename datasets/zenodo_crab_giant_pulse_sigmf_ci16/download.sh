#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_crab_giant_pulse_sigmf_ci16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_crab_giant_pulse_sigmf_ci16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

record_json="$DOWNLOAD_DIR/record_13143544.json"
curl --fail --silent --show-error --location --retry 3 --max-time 90 \
  --user-agent "openzl-public-datasets/1.0" \
  --output "$record_json.part" "https://zenodo.org/api/records/13143544"
mv "$record_json.part" "$record_json"

python3 - "$record_json" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
metadata = obj.get("metadata", {})
values = []
license_value = metadata.get("license")
if isinstance(license_value, dict):
    values.extend(str(license_value.get(key, "")) for key in ("id", "name", "title"))
normalized = " ".join(values).lower().replace("_", "-")
if "cc-by-4.0" not in normalized and "creative commons attribution 4.0" not in normalized:
    raise SystemExit(f"record does not explicitly declare CC BY 4.0: {values}")
if str(obj.get("id")) != "13143544":
    raise SystemExit(f"unexpected Zenodo record id: {obj.get('id')}")
print("record=13143544 license=CC-BY-4.0")
PY

files=0
data_bytes=0
while IFS=$'\t' read -r kind record_id name expected_size expected_md5 url; do
  [[ "$kind" == "kind" ]] && continue
  [[ -n "$kind" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  valid=false
  if [[ -f "$target" ]] \
    && [[ "$(wc -c < "$target" | tr -d ' ')" == "$expected_size" ]] \
    && [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]]; then
    valid=true
    echo "validated existing $name"
  fi
  if [[ "$valid" != true ]]; then
    rm -f "$target" "$target.part"
    echo "fetch $name bytes=$expected_size"
    curl --fail --location --retry 3 --retry-delay 2 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize 20000000 --output "$target.part" "$url"
    mv "$target.part" "$target"
    actual_size="$(wc -c < "$target" | tr -d ' ')"
    actual_md5="$(md5sum "$target" | awk '{print $1}')"
    if [[ "$actual_size" != "$expected_size" || "$actual_md5" != "$expected_md5" ]]; then
      echo "size/MD5 validation failed for $name" >&2
      exit 1
    fi
  fi
  files=$((files + 1))
  [[ "$kind" == "data" ]] && data_bytes=$((data_bytes + expected_size))
done < "$RECIPE_DIR/selection.tsv"

python3 - "$DOWNLOAD_DIR/crab-giantpulse.sigmf-meta" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
global_meta = obj.get("global", {})
if global_meta.get("core:license") != "https://creativecommons.org/licenses/by-sa/4.0/":
    raise SystemExit(f"embedded SigMF license changed: {global_meta.get('core:license')!r}")
print("embedded_sigmf_license=CC-BY-SA-4.0")
PY

if [[ "$files" -ne 2 || "$data_bytes" -ne 16000000 ]]; then
  echo "selection realization mismatch files=$files data_bytes=$data_bytes" >&2
  exit 1
fi
echo "[$(date -Is)] download done files=$files primary_source_bytes=$data_bytes"
