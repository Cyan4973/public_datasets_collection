#!/usr/bin/env bash
# Download three exact Apache-2.0 Google Fonts TTFs and their license files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_fonts_glyf_coordinates_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
COMMIT="2796410152d4f9524b68ed46e69c1b60f8e0f7c3"
RAW_ROOT="https://raw.githubusercontent.com/google/fonts/$COMMIT"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID commit=$COMMIT"

download_one() {
  local name="$1"
  local size="$2"
  local sha256="$3"
  local url="$4"
  local target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] && \
      [[ "$(sha256sum "$target" | awk '{print $1}')" == "$sha256" ]]; then
    echo "verified cached $name"
    return
  fi
  rm -f "$target.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 600 \
    --output "$target.part" "$url"
  local actual_size actual_sha256
  actual_size="$(stat -c %s "$target.part")"
  actual_sha256="$(sha256sum "$target.part" | awk '{print $1}')"
  [[ "$actual_size" == "$size" ]] || {
    echo "size mismatch for $name: $actual_size != $size" >&2
    exit 1
  }
  [[ "$actual_sha256" == "$sha256" ]] || {
    echo "SHA-256 mismatch for $name: $actual_sha256 != $sha256" >&2
    exit 1
  }
  mv "$target.part" "$target"
  echo "downloaded and verified $name"
}

download_one "aclonica__Aclonica-Regular.ttf" 68732 \
  774a49351cc62a469b56972e9769679ce818a3de15b409ad5f1b6244ee84d85b \
  "$RAW_ROOT/apache/aclonica/Aclonica-Regular.ttf"
download_one "robotoslab__RobotoSlab_wght_.ttf" 251880 \
  786ae192477447d33c6672c3055fba7cbfe45184c9a79e77a14f15716ca05b16 \
  "$RAW_ROOT/apache/robotoslab/RobotoSlab%5Bwght%5D.ttf"
download_one "specialelite__SpecialElite-Regular.ttf" 166180 \
  a776fcb4ceb8bdf03e2967688ebdad42680de5b91a7e62c17e718ae212d14bc4 \
  "$RAW_ROOT/apache/specialelite/SpecialElite-Regular.ttf"

for family in aclonica robotoslab specialelite; do
  download_one "${family}__LICENSE.txt" 11358 \
    cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 \
    "$RAW_ROOT/apache/$family/LICENSE.txt"
done

python3 - "$DOWNLOAD_DIR" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected_blobs = {
    "aclonica__Aclonica-Regular.ttf": "bbe191d026edc985b049f313f7d3f60a76713a49",
    "robotoslab__RobotoSlab_wght_.ttf": "1c46b300eda3677f604575ede4cd80f0d139c3be",
    "specialelite__SpecialElite-Regular.ttf": "6654876f95f11cb2b55c7c4254727ef68dbea74c",
}
for name, expected in expected_blobs.items():
    data = (root / name).read_bytes()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if actual != expected:
        raise SystemExit(f"Git blob SHA mismatch for {name}: {actual} != {expected}")
for path in root.glob("*__LICENSE.txt"):
    text = path.read_text(encoding="utf-8")
    if "Apache License" not in text or "Version 2.0" not in text:
        raise SystemExit(f"unexpected license text: {path}")
print("Git blob identities and Apache-2.0 license texts verified")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
