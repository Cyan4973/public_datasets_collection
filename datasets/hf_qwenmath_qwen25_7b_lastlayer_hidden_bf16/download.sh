#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="lzhang472/qwen-math-hidden-states"
REVISION="1b8d08c6c6bca2c3ebad597f3ea0802c9d420910"
MODEL_REPO="Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION="a09a35458c702b33eeacc393d103063234e8bc28"
GSM8K_REPO="openai/gsm8k"
GSM8K_REVISION="740312add88f781978c0658806c59bc2815b9866"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-qwenmath-hidden-download/1.0"

mkdir -p "$DOWNLOAD_DIR/traces" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start dataset=$DATASET_ID revision=$REVISION"

# fetch <url> <dest> <bytes> <sha256>: resumable; reuse when size and hash already match.
fetch() {
  local url="$1" dest="$2" bytes="$3" sha="$4" attempt
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]] \
    && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha" ]]; then
    return 0
  fi
  rm -f "$dest"
  mkdir -p "$(dirname "$dest")"
  for attempt in 1 2; do
    if [[ -f "$dest.part" ]] && (( $(stat -c %s "$dest.part") > bytes )); then
      rm -f "$dest.part"
    fi
    if [[ ! -f "$dest.part" ]] || (( $(stat -c %s "$dest.part") < bytes )); then
      curl --fail --silent --show-error --location -C - --retry 10 --retry-delay 5 \
        --retry-all-errors --speed-limit 1024 --speed-time 120 --max-filesize "$((bytes + 1))" \
        --user-agent "$UA" --output "$dest.part" "$url"
    fi
    if [[ "$(stat -c %s "$dest.part")" == "$bytes" ]] \
      && [[ "$(sha256sum "$dest.part" | awk '{print $1}')" == "$sha" ]]; then
      mv "$dest.part" "$dest"
      return 0
    fi
    echo "size/hash mismatch for $url (attempt $attempt); refetching from scratch" >&2
    rm -f "$dest.part"
  done
  echo "pinned resource changed: $url" >&2
  exit 1
}

fetch "https://huggingface.co/datasets/$REPO/raw/$REVISION/README.md" \
  "$DOWNLOAD_DIR/dataset_card.md" 1377 \
  "dffacb6b78de90f74ff097eb6e21453c462cdd3549f1eb8fd55d073a73446061"
fetch "https://huggingface.co/datasets/$REPO/resolve/$REVISION/manifest.jsonl" \
  "$DOWNLOAD_DIR/manifest.jsonl" 10649660 \
  "17b44c8f5c8915fe2612e404b3c82241923cad9b351b6a97387cbf9eab308631"
fetch "https://huggingface.co/$MODEL_REPO/raw/$MODEL_REVISION/README.md" \
  "$DOWNLOAD_DIR/model_card.md" 6240 \
  "f366f33bbf6bcadbb7d87f0a21a7b65584a56b8d58b0743c77c88bee625b93a6"
fetch "https://huggingface.co/datasets/$GSM8K_REPO/raw/$GSM8K_REVISION/README.md" \
  "$DOWNLOAD_DIR/gsm8k_card.md" 7935 \
  "a17e882503578c9e324560630e31017617714ee025c87cf4fea6fd916895f3c1"

count=0
total=0
while read -r bytes sha path; do
  fetch "https://huggingface.co/datasets/$REPO/resolve/$REVISION/$path" \
    "$DOWNLOAD_DIR/traces/$path" "$bytes" "$sha"
  count=$((count + 1))
  total=$((total + bytes))
  if (( count % 25 == 0 )); then echo "traces present=$count bytes=$total"; fi
done < <(python3 "$RECIPE_DIR/scripts/qwenmath_hidden.py" selection)
echo "trace files present=$count bytes=$total"

# Semantic validation: card licenses, manifest rows, safetensors layout, BF16 dtype/shape,
# finiteness, distribution sanity and final-layer consistency of every selected trace.
python3 "$RECIPE_DIR/scripts/qwenmath_hidden.py" validate --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] pinned download done dataset=$DATASET_ID"
