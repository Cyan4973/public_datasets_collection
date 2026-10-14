#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="hf_vbvr_wan22_vae_latents_bf16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_REPO="Central-Cat/vbvr-latent-cache-832x832x33f-t2v-only"
CACHE_REVISION="951c2880a946f0a947bc32c9f48df30767102175"
UPSTREAM_REPO="Video-Reason/VBVR-Dataset"
UPSTREAM_REVISION="7ef37ad3706c1a146143f9ab7611730487bd8c70"
ENCODER_REPO="Wan-AI/Wan2.2-TI2V-5B"
ENCODER_REVISION="921dbaf3f1674a56f47e83fb80a34bac8a8f203e"
DIFFUSERS_REPO="Wan-AI/Wan2.2-TI2V-5B-Diffusers"
DIFFUSERS_REVISION="b8fff7315c768468a5333511427288870b2e9635"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
UA="openzl-public-datasets-vbvr-wan22-latents-download/1.0"

mkdir -p "$DOWNLOAD_DIR/cache" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start candidate=$CANDIDATE_ID cache_revision=$CACHE_REVISION"

# fetch <url> <dest> <bytes> <sha256>: download once, reuse when size and hash already match.
fetch() {
  local url="$1" dest="$2" bytes="$3" sha="$4"
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]] \
    && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  rm -f "$dest.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --speed-limit 1024 --speed-time 120 --max-filesize "$((bytes + 1))" \
    --user-agent "$UA" --output "$dest.part" "$url"
  if [[ "$(stat -c %s "$dest.part")" != "$bytes" ]] \
    || [[ "$(sha256sum "$dest.part" | awk '{print $1}')" != "$sha" ]]; then
    rm -f "$dest.part"
    echo "pinned resource changed: $url" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
  echo "downloaded $(basename "$dest") bytes=$bytes"
}

fetch "https://huggingface.co/datasets/$CACHE_REPO/raw/$CACHE_REVISION/README.md" \
  "$DOWNLOAD_DIR/cache_card.md" 9841 \
  "0faf46312369baefe326a66988b1ca786629dae2814e49ded433364dc7aa264c"
fetch "https://huggingface.co/datasets/$UPSTREAM_REPO/raw/$UPSTREAM_REVISION/README.md" \
  "$DOWNLOAD_DIR/upstream_card.md" 9344 \
  "36d9c18a64b47b80389e520cb4b14f09840995c8fb29dab729716f97438baec2"
fetch "https://huggingface.co/$ENCODER_REPO/raw/$ENCODER_REVISION/README.md" \
  "$DOWNLOAD_DIR/encoder_card.md" 15935 \
  "e357cb3ac077f8739755b0fb38fe8424c76534b19b4a84f6138856abb00abf69"
fetch "https://huggingface.co/$DIFFUSERS_REPO/raw/$DIFFUSERS_REVISION/README.md" \
  "$DOWNLOAD_DIR/encoder_diffusers_card.md" 17633 \
  "b7120bb210ab14defe6cabd7ac4bf568d0f5fde42f88ea4ac3cfec9516dc2c0c"

count=0
while read -r bytes sha path; do
  fetch "https://huggingface.co/datasets/$CACHE_REPO/resolve/$CACHE_REVISION/$path" \
    "$DOWNLOAD_DIR/cache/$path" "$bytes" "$sha"
  count=$((count + 1))
done < <(python3 "$RECIPE_DIR/scripts/vbvr_latents.py" selection)
echo "cache files present=$count"

python3 "$RECIPE_DIR/scripts/vbvr_latents.py" validate --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] pinned download done candidate=$CANDIDATE_ID"
