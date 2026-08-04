#!/usr/bin/env bash
# Download and validate the exact CC BY 4.0 IMAT neutron projection archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_imat_neutron_projections_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_4273969.json"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 180 \
  --output "$RECORD_JSON.part" "https://zenodo.org/api/records/4273969"
python3 - "$RECORD_JSON.part" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text())
expected_title = "Neutron tomography data of high-purity metal rods using golden-ratio angular acquisition (IMAT, ISIS)"
if int(obj.get("id", 0)) != 4273969 or obj.get("metadata", {}).get("title") != expected_title:
    raise SystemExit("unexpected Zenodo record identity")
if obj.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
    raise SystemExit("Zenodo record no longer declares CC BY 4.0")
files = obj.get("files", [])
matching = [item for item in files if item.get("key") == "imat_rod_phantom_white_beam.zip"]
if len(matching) != 1:
    raise SystemExit("pinned archive is absent or ambiguous")
item = matching[0]
if int(item.get("size", 0)) != 168192038 or item.get("checksum") != "md5:9abc2df64fdf58cb4e194cbf29131b27":
    raise SystemExit("pinned archive identity changed")
PY
mv "$RECORD_JSON.part" "$RECORD_JSON"

NAME="imat_rod_phantom_white_beam.zip"
SIZE="168192038"
MD5="9abc2df64fdf58cb4e194cbf29131b27"
URL="https://zenodo.org/api/records/4273969/files/imat_rod_phantom_white_beam.zip/content"
TARGET="$DOWNLOAD_DIR/$NAME"
if [[ -f "$TARGET" ]] && [[ "$(stat -c %s "$TARGET")" == "$SIZE" ]] && [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$MD5" ]]; then
  echo "verified cached $NAME"
else
  rm -f "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 3600 --max-filesize 168192039 \
    --output "$TARGET.part" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$TARGET.part")"
  ACTUAL_MD5="$(md5sum "$TARGET.part" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE" ]] || { echo "size mismatch: $ACTUAL_SIZE != $SIZE" >&2; exit 1; }
  [[ "$ACTUAL_MD5" == "$MD5" ]] || { echo "MD5 mismatch: $ACTUAL_MD5 != $MD5" >&2; exit 1; }
  mv "$TARGET.part" "$TARGET"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
