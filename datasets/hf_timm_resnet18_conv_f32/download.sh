#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="hf_timm_resnet18_conv_f32"
REVISION="491b427b45c94c7fb0e78b5474cc919aff584bbf"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MODEL_CARD="$DOWNLOAD_DIR/model_card.md"
MODEL_FILE="$DOWNLOAD_DIR/model.safetensors"
MODEL_CARD_URL="https://huggingface.co/timm/resnet18.a1_in1k/raw/$REVISION/README.md"
MODEL_URL="https://huggingface.co/timm/resnet18.a1_in1k/resolve/$REVISION/model.safetensors"
MODEL_CARD_BYTES=38416
MODEL_CARD_SHA256="e96d7547dfaff6f0a0d74209819c461ec2d66556a9d6b059f1c2a50d413da5bb"
MODEL_BYTES=46807446
MODEL_SHA256="80c49dee3da4822c009c5a7fe591e9223c5a2cfcf95a4067ca4dfb5a7b89c612"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start candidate=$CANDIDATE_ID revision=$REVISION"

card_cache="$DISCOVERY_DIR/model_card.md"
if [[ ! -f "$MODEL_CARD" ]] \
  && [[ -f "$card_cache" ]] \
  && [[ "$(stat -c %s "$card_cache")" == "$MODEL_CARD_BYTES" ]] \
  && [[ "$(sha256sum "$card_cache" | awk '{print $1}')" == "$MODEL_CARD_SHA256" ]]; then
  cp "$card_cache" "$MODEL_CARD"
  echo "reused cached model card"
fi
if [[ ! -f "$MODEL_CARD" ]] \
  || [[ "$(stat -c %s "$MODEL_CARD")" != "$MODEL_CARD_BYTES" ]] \
  || [[ "$(sha256sum "$MODEL_CARD" | awk '{print $1}')" != "$MODEL_CARD_SHA256" ]]; then
  rm -f "$MODEL_CARD.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize "$MODEL_CARD_BYTES" \
    --user-agent "openzl-public-datasets-resnet18-f32-download/1.0" \
    --output "$MODEL_CARD.part" "$MODEL_CARD_URL"
  if [[ "$(stat -c %s "$MODEL_CARD.part")" != "$MODEL_CARD_BYTES" ]] \
    || [[ "$(sha256sum "$MODEL_CARD.part" | awk '{print $1}')" != "$MODEL_CARD_SHA256" ]]; then
    rm -f "$MODEL_CARD.part"
    echo "pinned model card changed" >&2
    exit 1
  fi
  mv "$MODEL_CARD.part" "$MODEL_CARD"
  echo "downloaded model_card.md bytes=$MODEL_CARD_BYTES"
else
  echo "reuse model_card.md bytes=$MODEL_CARD_BYTES"
fi

if [[ ! -f "$MODEL_FILE" ]] \
  || [[ "$(stat -c %s "$MODEL_FILE")" != "$MODEL_BYTES" ]] \
  || [[ "$(sha256sum "$MODEL_FILE" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
  rm -f "$MODEL_FILE.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 1800 --max-filesize "$((MODEL_BYTES + 1))" \
    --user-agent "openzl-public-datasets-resnet18-f32-download/1.0" \
    --output "$MODEL_FILE.part" "$MODEL_URL"
  if [[ "$(stat -c %s "$MODEL_FILE.part")" != "$MODEL_BYTES" ]] \
    || [[ "$(sha256sum "$MODEL_FILE.part" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
    rm -f "$MODEL_FILE.part"
    echo "pinned SafeTensors checkpoint changed" >&2
    exit 1
  fi
  mv "$MODEL_FILE.part" "$MODEL_FILE"
  echo "downloaded model.safetensors bytes=$MODEL_BYTES"
else
  echo "reuse model.safetensors bytes=$MODEL_BYTES"
fi

python3 "$RECIPE_DIR/scripts/resnet_conv.py" validate --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] pinned download done candidate=$CANDIDATE_ID"
