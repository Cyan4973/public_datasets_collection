#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="deepmind_gencast_checkpoint_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PROBE_DIR="$REPO_ROOT/$DATA_DIR/probes/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
REVISION="9c034db1ff412d5db6cbe6bb0c5c9afc5a267719"
MODEL_URL="https://storage.googleapis.com/dm_graphcast/gencast/params/GenCast%201p0deg%20Mini%20%3C2019.npz"
LICENSE_URL="https://storage.googleapis.com/dm_graphcast/LICENSE"
README_URL="https://raw.githubusercontent.com/google-deepmind/graphcast/$REVISION/docs/weathernext1_gen/README.md"
MODEL_BYTES=230105815
MODEL_MD5="390a43c43cb6f49ea46d7ffc7104cc99"
MODEL_SHA256="a8dc94b616af89cfc01a5c6afbcc8411b594d919f23f3cd962f6f7755735195e"
LICENSE_BYTES=18649
LICENSE_SHA256="95df2e9564862e51d69683a899b6dcc8218d577057bdf67322880769ff85f29e"
README_BYTES=9170
README_SHA256="d7c7e7d75ae7c1c53e28ea495be9b79e681a855e35876d8124635c801cf3c5e6"
MODEL_FILE="$DOWNLOAD_DIR/gencast_1p0deg_mini_2019.npz"
LICENSE_FILE="$DOWNLOAD_DIR/LICENSE"
README_FILE="$DOWNLOAD_DIR/gencast_README.md"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start dataset=$DATASET_ID revision=$REVISION"

reuse_or_fetch() {
  local target="$1"
  local cache="$2"
  local url="$3"
  local expected_bytes="$4"
  local expected_sha256="$5"
  if [[ ! -f "$target" && -f "$cache" ]] \
    && [[ "$(stat -c %s "$cache")" == "$expected_bytes" ]] \
    && [[ "$(sha256sum "$cache" | awk '{print $1}')" == "$expected_sha256" ]]; then
    cp "$cache" "$target"
    echo "reused cached metadata target=$(basename "$target")"
  fi
  if [[ ! -f "$target" ]] \
    || [[ "$(stat -c %s "$target")" != "$expected_bytes" ]] \
    || [[ "$(sha256sum "$target" | awk '{print $1}')" != "$expected_sha256" ]]; then
    rm -f "$target.part"
    curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
      --retry-all-errors --max-time 180 --max-filesize "$expected_bytes" \
      --user-agent "openzl-public-datasets-gencast-checkpoint-download/1.1" \
      --output "$target.part" "$url"
    if [[ "$(stat -c %s "$target.part")" != "$expected_bytes" ]] \
      || [[ "$(sha256sum "$target.part" | awk '{print $1}')" != "$expected_sha256" ]]; then
      rm -f "$target.part"
      echo "pinned metadata changed: $url" >&2
      exit 1
    fi
    mv "$target.part" "$target"
    echo "downloaded metadata target=$(basename "$target") bytes=$expected_bytes"
  else
    echo "reuse metadata target=$(basename "$target") bytes=$expected_bytes"
  fi
}

reuse_or_fetch "$LICENSE_FILE" "$PROBE_DIR/bucket_LICENSE" "$LICENSE_URL" "$LICENSE_BYTES" "$LICENSE_SHA256"
reuse_or_fetch "$README_FILE" "$PROBE_DIR/gencast_README.md" "$README_URL" "$README_BYTES" "$README_SHA256"

if [[ ! -f "$MODEL_FILE" ]] \
  || [[ "$(stat -c %s "$MODEL_FILE")" != "$MODEL_BYTES" ]] \
  || [[ "$(md5sum "$MODEL_FILE" | awk '{print $1}')" != "$MODEL_MD5" ]] \
  || [[ "$(sha256sum "$MODEL_FILE" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
  rm -f "$MODEL_FILE.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 1800 --max-filesize "$((MODEL_BYTES + 1))" \
    --user-agent "openzl-public-datasets-gencast-checkpoint-download/1.1" \
    --output "$MODEL_FILE.part" "$MODEL_URL"
  if [[ "$(stat -c %s "$MODEL_FILE.part")" != "$MODEL_BYTES" ]] \
    || [[ "$(md5sum "$MODEL_FILE.part" | awk '{print $1}')" != "$MODEL_MD5" ]] \
    || [[ "$(sha256sum "$MODEL_FILE.part" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
    rm -f "$MODEL_FILE.part"
    echo "pinned GenCast checkpoint changed" >&2
    exit 1
  fi
  mv "$MODEL_FILE.part" "$MODEL_FILE"
  echo "downloaded checkpoint bytes=$MODEL_BYTES md5=$MODEL_MD5 sha256=$MODEL_SHA256"
else
  echo "reuse checkpoint bytes=$MODEL_BYTES md5=$MODEL_MD5 sha256=$MODEL_SHA256"
fi

export LICENSE_FILE MODEL_FILE README_FILE
python3 - <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import hashlib
import re
import zipfile


license_text = Path(os.environ["LICENSE_FILE"]).read_text(encoding="utf-8", errors="strict")
if "Creative Commons Attribution 4.0 International Public License" not in license_text:
    raise SystemExit("dm_graphcast bucket license changed")
readme = re.sub(
    r"\s+",
    " ",
    Path(os.environ["README_FILE"]).read_text(encoding="utf-8", errors="strict"),
)
for phrase in (
    "The license for the model weights in this repository",
    "updated to permit commercial use",
    "Creative Commons Attribution 4.0 International",
):
    if phrase not in readme:
        raise SystemExit(f"GenCast model-weight license evidence changed: {phrase!r}")

with zipfile.ZipFile(os.environ["MODEL_FILE"]) as archive:
    infos = archive.infolist()
    if len(infos) != 363 or len({info.filename for info in infos}) != 363:
        raise SystemExit(f"checkpoint member inventory changed: {len(infos)}")
    if any(info.compress_type != zipfile.ZIP_STORED for info in infos):
        raise SystemExit("checkpoint unexpectedly contains compressed members")
    if any(not info.filename.endswith(".npy") for info in infos):
        raise SystemExit("checkpoint unexpectedly contains non-NPY members")
    if sum(info.file_size for info in infos) != 230_022_753:
        raise SystemExit("checkpoint aggregate member size changed")
    bad = archive.testzip()
    if bad is not None:
        raise SystemExit(f"checkpoint CRC validation failed: {bad}")
digest = hashlib.sha256()
with Path(os.environ["MODEL_FILE"]).open("rb") as handle:
    for block in iter(lambda: handle.read(1 << 20), b""):
        digest.update(block)
print(
    f"validated checkpoint members={len(infos)} member_bytes={sum(info.file_size for info in infos)} "
    f"sha256={digest.hexdigest()}"
)
PY

echo "[$(date -Is)] pinned download done dataset=$DATASET_ID"
