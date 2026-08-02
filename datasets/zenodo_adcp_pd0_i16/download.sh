#!/usr/bin/env bash
# Download three exact CC BY 4.0 RDI PD0 ADCP recordings.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_adcp_pd0_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_5015459.json"
curl --fail --silent --show-error --location --retry 5 --max-time 120 \
  --output "$RECORD_JSON.part" "https://zenodo.org/api/records/5015459"
python3 - "$RECORD_JSON.part" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text())
if int(obj.get("id", 0)) != 5015459:
    raise SystemExit("unexpected Zenodo record id")
metadata = obj.get("metadata", {})
if metadata.get("title") != "Salinity and Velocity in Lower South San Francisco Bay":
    raise SystemExit("unexpected Zenodo record title")
license_obj = metadata.get("license", {})
license_id = license_obj.get("id", "") if isinstance(license_obj, dict) else ""
if license_id != "cc-by-4.0":
    raise SystemExit(f"record no longer declares CC BY 4.0: {license_obj}")
PY
mv "$RECORD_JSON.part" "$RECORD_JSON"

download_one() {
  local name="$1"
  local size="$2"
  local md5="$3"
  local url="$4"
  local target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] && \
      [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "verified cached $name"
    return
  fi
  rm -f "$target.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 \
    --output "$target.part" "$url"
  local actual_size actual_md5
  actual_size="$(stat -c %s "$target.part")"
  actual_md5="$(md5sum "$target.part" | awk '{print $1}')"
  [[ "$actual_size" == "$size" ]] || {
    echo "size mismatch for $name: $actual_size != $size" >&2
    exit 1
  }
  [[ "$actual_md5" == "$md5" ]] || {
    echo "MD5 mismatch for $name: $actual_md5 != $md5" >&2
    exit 1
  }
  mv "$target.part" "$target"
  echo "downloaded and verified $name"
}

download_one "line3_ADCP2001.000" 10962812 3f8da2d38e4f6783f5fdff1dff82f3a1 \
  "https://zenodo.org/api/records/5015459/files/line3_ADCP2001.000/content"
download_one "line2_ADCP1000.000" 24813664 04c27147b68aecb5e6feef84702d9b5e \
  "https://zenodo.org/api/records/5015459/files/line2_ADCP1000.000/content"
download_one "line2_ADCP1001.000" 46960000 8e1631f12dd8caa61c2dc76a31efb642 \
  "https://zenodo.org/api/records/5015459/files/line2_ADCP1001.000/content"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
