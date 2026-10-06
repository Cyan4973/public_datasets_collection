#!/usr/bin/env bash
# Fetch the pinned AOMIC-ID1000 DTI selection from the public OpenNeuro S3
# bucket (anonymous HTTPS): 32 WLS diffusion-tensor volumes plus their 32
# companion FA maps (validation only), each checked by byte size and MD5
# (single-part S3 ETag pinned in selection.tsv), then semantically validated
# (NIfTI header, payload length, finite values, FA recomputed from the tensor).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="openneuro_ds003097_aomic_dti_tensor_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
KEY_PREFIX="ds003097/derivatives/dwipreproc/"
SELECTION="$RECIPE_DIR/selection.tsv"
EXPECTED_SELECTION_SHA256="ee3ad04b06d0c6493be7d68a83addb13dfc210b1c0c7595f971cb646f1301a62"
EXPECTED_OBJECTS=64
EXPECTED_OBJECT_BYTES=146432131
EXPECTED_DESCRIPTION_SHA256="077aaf2ad49e2c2681ed30bc21b743294885d135d7ced167526dec1abed43a95"
UA="openzl-public-datasets/1.0 (aomic-dti-tensor)"

mkdir -p "$DOWNLOAD_DIR/dwipreproc" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

actual_selection_sha="$(sha256sum "$SELECTION" | awk '{print $1}')"
if [[ "$actual_selection_sha" != "$EXPECTED_SELECTION_SHA256" ]]; then
  echo "FATAL: selection.tsv sha256 $actual_selection_sha != pinned $EXPECTED_SELECTION_SHA256" >&2
  exit 1
fi

# Liveness: one-byte range GET on the first pinned tensor object.
first_key="$(awk -F'\t' 'NR>1 && $1=="diffmodel"{print $3; exit}' "$SELECTION")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$BASE_URL/$first_key"
echo "liveness_ok key=$first_key"

# 1. Dataset description: explicit CC0 license for the whole ds003097 dataset
#    (raw data and derivatives; derivatives/dwipreproc has no own license file).
DESCRIPTION="$DOWNLOAD_DIR/dataset_description.json"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 120 --max-filesize 100000 --user-agent "$UA" \
  --output "$DESCRIPTION.part" "$BASE_URL/ds003097/dataset_description.json"
mv "$DESCRIPTION.part" "$DESCRIPTION"
python3 - "$DESCRIPTION" "$EXPECTED_DESCRIPTION_SHA256" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
raw = path.read_bytes()
obj = json.loads(raw)
if obj.get("License") != "CC0":
    raise SystemExit(f"FATAL: expected License=CC0, found {obj.get('License')!r}")
if obj.get("Name") != "AOMIC-ID1000":
    raise SystemExit(f"FATAL: unexpected dataset name {obj.get('Name')!r}")
digest = hashlib.sha256(raw).hexdigest()
if digest != sys.argv[2]:
    print(f"WARNING: dataset_description.json sha256 {digest} differs from pinned {sys.argv[2]} "
          "(license still CC0; payload objects remain pinned by MD5)")
print(f"license={obj['License']} name={obj['Name']} doi={obj.get('DatasetDOI')} sha256={digest}")
PY

# 2. Pinned objects: 32 diffmodel tensor volumes + 32 FA maps.
fetched=0
reused=0
objects=0
object_bytes=0
while IFS=$'\t' read -r kind subject key expected_size expected_md5; do
  [[ "$kind" == "kind" ]] && continue
  [[ -n "$kind" ]] || continue
  [[ "$key" == "$KEY_PREFIX$subject/dwi/"* ]] || { echo "FATAL: unexpected key $key" >&2; exit 1; }
  target="$DOWNLOAD_DIR/dwipreproc/${key#"$KEY_PREFIX"}"
  mkdir -p "$(dirname "$target")"
  if [[ -f "$target" ]] \
    && [[ "$(stat -c %s "$target")" == "$expected_size" ]] \
    && [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]]; then
    reused=$((reused + 1))
  else
    rm -f "$target"
    curl --fail --silent --show-error --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 10000000 \
      --user-agent "$UA" --output "$target.part" "$BASE_URL/$key"
    actual_size="$(stat -c %s "$target.part")"
    actual_md5="$(md5sum "$target.part" | awk '{print $1}')"
    if [[ "$actual_size" != "$expected_size" || "$actual_md5" != "$expected_md5" ]]; then
      rm -f "$target.part"
      echo "FATAL: $key size=$actual_size md5=$actual_md5 expected size=$expected_size md5=$expected_md5" >&2
      exit 1
    fi
    mv "$target.part" "$target"
    fetched=$((fetched + 1))
  fi
  objects=$((objects + 1))
  object_bytes=$((object_bytes + expected_size))
  if (( objects % 16 == 0 )); then
    echo "progress objects=$objects fetched=$fetched reused=$reused bytes=$object_bytes"
  fi
done < "$SELECTION"

if [[ "$objects" -ne "$EXPECTED_OBJECTS" || "$object_bytes" -ne "$EXPECTED_OBJECT_BYTES" ]]; then
  echo "FATAL: selection realization mismatch objects=$objects bytes=$object_bytes" \
    "expected objects=$EXPECTED_OBJECTS bytes=$EXPECTED_OBJECT_BYTES" >&2
  exit 1
fi

# 3. Semantic validation of every pinned object.
python3 "$RECIPE_DIR/scripts/aomic_dti.py" check-downloads \
  --selection "$SELECTION" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done objects=$objects fetched=$fetched reused=$reused bytes=$object_bytes"
