#!/usr/bin/env bash
# Download and validate the exact CC BY 4.0 Venere ENVI pair.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_venere_nir_hsi_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_8143550.json"
curl --fail --silent --show-error --location --retry 5 --max-time 120 \
  --output "$RECORD_JSON.part" "https://zenodo.org/api/records/8143550"
python3 - "$RECORD_JSON.part" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text())
if int(obj.get("id", 0)) != 8143550:
    raise SystemExit("unexpected Zenodo record id")
metadata = obj.get("metadata", {})
expected_title = 'Push-broom NIR-HSI scanning of painting reconstruction, inspired by Sandro Botticelli\'s "Venus"'
if metadata.get("title") != expected_title:
    raise SystemExit("unexpected Zenodo record title")
license_obj = metadata.get("license", {})
if not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0":
    raise SystemExit(f"record no longer declares CC BY 4.0: {license_obj}")
PY
mv "$RECORD_JSON.part" "$RECORD_JSON"

while IFS=$'\t' read -r name size md5 url; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] && [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "verified cached $name"
    continue
  fi
  rm -f "$target.part"
  echo "downloading $name bytes=$size"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 3600 \
    --output "$target.part" "$url"
  actual_size="$(stat -c %s "$target.part")"
  actual_md5="$(md5sum "$target.part" | awk '{print $1}')"
  [[ "$actual_size" == "$size" ]] || { echo "size mismatch for $name: $actual_size != $size" >&2; exit 1; }
  [[ "$actual_md5" == "$md5" ]] || { echo "MD5 mismatch for $name: $actual_md5 != $md5" >&2; exit 1; }
  mv "$target.part" "$target"
done <<'EOF'
venere.hdr	5918	9c3aaf32039f039143f60b8535a86b61	https://zenodo.org/api/records/8143550/files/venere.hdr/content
venere.raw	90685440	523a952df4261d6f3692df74bdc7c699	https://zenodo.org/api/records/8143550/files/venere.raw/content
EOF

echo "[$(date -Is)] download done dataset=$DATASET_ID"
