#!/usr/bin/env bash
# Fetch the ten MIT-licensed MACE-MP foundation checkpoints (GitHub release
# assets of ACEsuit/mace-foundations) plus the pinned README/LICENSE that carry
# the license evidence. Resumable; rejects size, sha256, central-directory,
# data.pkl or member-CRC drift. About 692 MB in total.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="mace_mp_foundation_model_weights_f64"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/mace_weights.py"
USER_AGENT="openzl-public-datasets-mace-mp-weights/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

fetch() {
  local url="$1" bytes="$2" dest="$3" part="$3.part" have
  have="$(file_size "$part")"
  if [[ "$have" -gt "$bytes" ]]; then
    echo "discarding oversized partial $part ($have > $bytes)"
    rm -f "$part"
    have=0
  fi
  if [[ "$have" -lt "$bytes" ]]; then
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$USER_AGENT" \
      --output "$part" "$url" </dev/null
  fi
  have="$(file_size "$part")"
  if [[ "$have" != "$bytes" ]]; then
    echo "size mismatch for $url: got $have expected $bytes" >&2
    [[ "$have" -gt "$bytes" ]] && rm -f "$part"
    return 1
  fi
  mv "$part" "$dest"
}

total=0
count=0
while read -r kind tag url bytes sha rel; do
  dest="$DATA_ROOT/$rel"
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" && "$(file_size "$dest")" == "$bytes" ]]; then
    echo "reuse $tag bytes=$bytes"
  else
    rm -f "$dest"
    echo "fetch $tag bytes=$bytes url=$url"
    fetch "$url" "$bytes" "$dest"
  fi
  if [[ "$kind" == "doc" ]]; then
    got="$(sha256sum "$dest" | awk '{print $1}')"
    if [[ "$got" != "$sha" ]]; then
      echo "pinned document changed: $tag sha256=$got expected=$sha" >&2
      rm -f "$dest"
      exit 1
    fi
    echo "validated $tag sha256=$got"
  else
    if ! python3 "$TOOL" validate-file --tag "$tag" --file "$dest" </dev/null; then
      echo "rejecting invalid checkpoint payload $tag; removed so a re-run refetches" >&2
      rm -f "$dest"
      exit 1
    fi
  fi
  total=$((total + bytes))
  count=$((count + 1))
done < <(python3 "$TOOL" resources)

if [[ "$count" != 12 ]]; then
  echo "expected 12 pinned resources, processed $count" >&2
  exit 1
fi
python3 "$TOOL" validate-docs --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID total_bytes=$total"
