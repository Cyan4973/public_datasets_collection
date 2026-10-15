#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
CANDIDATE_ID="hf_anycam_mcv_wan21_vae_latents_bf16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$RECIPE_DIR/scripts/anycam_latents.py"
CACHE_REPO="wlyu/AnyCam_MCV_480p_wan21_latent"
CACHE_REVISION="acb9cc2a3851b1e987a9dbf02895a311d263d5a8"
PAIRS_REPO="wlyu/AnyCam_MCV_480p"
PAIRS_REVISION="3e7bacb2f216c305abc1b80a6c7453eaec14ca7a"
MCV_REPO="KlingTeam/MultiCamVideo-Dataset"
MCV_REVISION="4e7d995480cfa915f7c3721e616ed14789d87ff7"
ENCODER_REPO="alibaba-pai/Wan2.1-Fun-1.3B-InP"
ENCODER_REVISION="9bcbbcf673c0e6a996df6f3f25bee596ffa36d47"
DOWNLOAD_DIR="$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$DATA_DIR/logs/$CANDIDATE_ID"
UA="openzl-public-datasets-anycam-wan21-latents-download/1.0"

mkdir -p "$DOWNLOAD_DIR/cards" "$DOWNLOAD_DIR/fragments" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned range download start candidate=$CANDIDATE_ID cache_revision=$CACHE_REVISION"

CURL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

# fetch_card <url> <dest> <bytes> <sha256>
fetch_card() {
  local url="$1" dest="$2" bytes="$3" sha="$4"
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]] \
    && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha" ]]; then
    return 0
  fi
  rm -f "$dest.part"
  "${CURL[@]}" --max-filesize "$((bytes + 65536))" --output "$dest.part" "$url"
  if [[ "$(stat -c %s "$dest.part")" != "$bytes" ]] \
    || [[ "$(sha256sum "$dest.part" | awk '{print $1}')" != "$sha" ]]; then
    rm -f "$dest.part"
    echo "pinned card changed: $url" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
  echo "downloaded card $(basename "$dest") bytes=$bytes"
}

# fetch_range <url> <dest> <first> <stop>: bytes [first, stop) of the archive. --max-filesize also
# applies to the ~1 KB redirect body, hence the 64 KiB slack.
# A server that ignores the Range header returns the full archive, which --max-filesize
# and the length check reject.
fetch_range() {
  local url="$1" dest="$2" first="$3" stop="$4"
  local bytes=$((stop - first))
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]]; then
    return 0
  fi
  rm -f "$dest.part"
  "${CURL[@]}" --max-filesize "$((bytes + 65536))" --range "$first-$((stop - 1))" --output "$dest.part" "$url"
  if [[ "$(stat -c %s "$dest.part")" != "$bytes" ]]; then
    rm -f "$dest.part"
    echo "range $first-$((stop - 1)) of $url returned the wrong length" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
}

fetch_card "https://huggingface.co/datasets/$CACHE_REPO/raw/$CACHE_REVISION/README.md" \
  "$DOWNLOAD_DIR/cards/latent_cache_card.md" 1259 \
  "3d8a0eb6a8ee3f4686400d03711f659d2f5cc8ab9ef30e42ca921ea30d755af1"
fetch_card "https://huggingface.co/datasets/$PAIRS_REPO/raw/$PAIRS_REVISION/README.md" \
  "$DOWNLOAD_DIR/cards/anycam_pairs_card.md" 4144 \
  "1ea2b98afab68aeccf473592b23763c132843fcc95afce6d3ff991ea59800fcf"
fetch_card "https://huggingface.co/datasets/$MCV_REPO/raw/$MCV_REVISION/README.md" \
  "$DOWNLOAD_DIR/cards/multicamvideo_card.md" 9009 \
  "97bc2df4c3fc8fe5fbb48e3350810778a3bf432ba5700497bcd5def79a54456d"
fetch_card "https://huggingface.co/$ENCODER_REPO/raw/$ENCODER_REVISION/README.md" \
  "$DOWNLOAD_DIR/cards/encoder_card.md" 13018 \
  "c3441cf796d4aa326a2887978ec81c66177a4e9d38842a38d3e472dbdc7158ed"

count=0
while read -r scene size cd_start head_stop target_start target_stop; do
  url="https://huggingface.co/datasets/$CACHE_REPO/resolve/$CACHE_REVISION/$scene.pt"
  dir="$DOWNLOAD_DIR/fragments/$scene"
  mkdir -p "$dir"
  fetch_range "$url" "$dir/tail.bin" "$cd_start" "$size"
  fetch_range "$url" "$dir/head.bin" 0 "$head_stop"
  fetch_range "$url" "$dir/target.bin" "$target_start" "$target_stop"
  # Semantic check: central directory, CRC-32s, pinned offsets, restricted unpickle, tensor
  # dtype/shape/strides, byte order, finiteness and non-degeneracy. Bad fragments are removed
  # so a re-run fetches them again.
  if ! python3 -I "$TOOL" check-scene --download-dir "$DOWNLOAD_DIR" --scene "$scene"; then
    rm -f "$dir/tail.bin" "$dir/head.bin" "$dir/target.bin"
    echo "invalid fragments for $scene" >&2
    exit 1
  fi
  count=$((count + 1))
  if (( count % 10 == 0 )); then echo "[$(date -Is)] scenes ready=$count"; fi
done < <(python3 -I "$TOOL" selection)
echo "scenes present=$count"

python3 -I "$TOOL" validate --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] pinned range download done candidate=$CANDIDATE_ID"
