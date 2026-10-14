#!/usr/bin/env bash
# Fetch the pinned cards, the HDF5 metadata head, and the 100 raw_h_norm
# windows of chr22_tier3_raw.h5 as byte ranges (the full file is 47.7 GB).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
[[ "$DATA_DIR" = /* ]] || DATA_DIR="$REPO_ROOT/$DATA_DIR"
DATASET_ID="hf_tdig_evo2_7b_hg38_final_norm_hidden_f16"
REPO="darejinn/TDiG-evo2-hidden-states"
REVISION="9f0d2a6a31ddd08ca4e3defab714dc7665634501"
MODEL_REPO="arcinstitute/evo2_7b_base"
MODEL_REVISION="074097e9dc788e8bfe045d6495b9f6153a7c6bfc"
H5_URL="https://huggingface.co/datasets/$REPO/resolve/$REVISION/chr22_tier3_raw.h5"
H5_SIZE=47677466172
HEAD_BYTES=65536
HEAD_SHA256="2c6772344c10254fc7f6dda71dd1621e165b4769f0d3762b9ac42782ffce6599"
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-tdig-evo2-download/1.0"
TOOL="$RECIPE_DIR/scripts/tdig_evo2.py"

mkdir -p "$DOWNLOAD_DIR/chr22_raw_h_norm" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

# fetch_file <url> <dest> <bytes> <sha256>: small pinned files.
fetch_file() {
  local url="$1" dest="$2" bytes="$3" sha="$4"
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]] \
    && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha" ]]; then
    return 0
  fi
  rm -f "$dest.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize "$((bytes + 1))" \
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

# fetch_range <start> <length> <dest>: one HTTP Range GET of an exact byte span.
# Resume granularity is the range: completed files of the exact length are kept
# and re-validated by the semantic check below; failed spans are fetched again.
fetch_range() {
  local start="$1" length="$2" dest="$3" end attempt code got cap
  end=$((start + length - 1))
  # --max-filesize also applies to the Hub's 302 redirect body (~1 KiB), so
  # small spans need a floor; the exact length is enforced after the fetch.
  cap=$((length + 1)); (( cap < 65536 )) && cap=65536
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$length" ]]; then
    return 0
  fi
  for attempt in 1 2 3 4 5 6; do
    rm -f "$dest.part"
    code="$(curl --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize "$cap" \
      --user-agent "$UA" --range "$start-$end" --output "$dest.part" \
      --write-out '%{http_code}' "$H5_URL" || true)"
    got="$(stat -c %s "$dest.part" 2>/dev/null || echo 0)"
    if [[ "$code" == "206" && "$got" == "$length" ]]; then
      mv "$dest.part" "$dest"
      return 0
    fi
    echo "range $start-$end attempt $attempt failed: http=$code bytes=$got" >&2
    sleep $((attempt * 10))
  done
  rm -f "$dest.part"
  echo "giving up on range $start-$end" >&2
  exit 1
}

# License / provenance evidence (pinned revisions).
fetch_file "https://huggingface.co/datasets/$REPO/raw/$REVISION/README.md" \
  "$DOWNLOAD_DIR/dataset_card.md" 6180 \
  "4ea25df8dfbef6d823404091a9747ee31b0eecc20abebbb32239c5805900385a"
fetch_file "https://huggingface.co/$MODEL_REPO/raw/$MODEL_REVISION/README.md" \
  "$DOWNLOAD_DIR/model_card.md" 1217 \
  "b39cc7f28cca98b868aa2e9a8bcb93b11c13937e45f330f616070d8a2545e180"
grep -q '^license: mit$' "$DOWNLOAD_DIR/dataset_card.md" || { echo "dataset card no longer declares MIT" >&2; exit 1; }
grep -q '^license: apache-2.0$' "$DOWNLOAD_DIR/model_card.md" || { echo "model card no longer declares Apache-2.0" >&2; exit 1; }

# Liveness and size of the pinned HDF5 object (one-byte range GET).
probe="$(curl --silent --show-error --location --retry 5 --retry-delay 5 --max-time 120 \
  --user-agent "$UA" --range 0-0 --output /dev/null \
  --write-out '%{http_code}' --dump-header - "$H5_URL" | tr -d '\r')"
grep -qi "^content-range: bytes 0-0/$H5_SIZE$" <<<"$probe" \
  || { echo "chr22_tier3_raw.h5 is not reachable at the pinned size $H5_SIZE" >&2; exit 1; }

# HDF5 superblock, root group and object headers (all within the first 64 KiB).
head_file="$DOWNLOAD_DIR/chr22_tier3_raw.head.bin"
if [[ ! -f "$head_file" ]] || [[ "$(sha256sum "$head_file" | awk '{print $1}')" != "$HEAD_SHA256" ]]; then
  rm -f "$head_file"
  fetch_range 0 "$HEAD_BYTES" "$head_file"
fi

# The plan re-derives every address from the object headers and rejects any
# datatype/layout other than contiguous, unfiltered IEEE binary16 LE.
plan="$(python3 "$TOOL" plan --head "$head_file")"
n=0
while IFS=$'\t' read -r kind start length rel; do
  fetch_range "$start" "$length" "$DOWNLOAD_DIR/$rel"
  if [[ "$kind" == "window" ]]; then
    n=$((n + 1))
    (( n % 10 == 0 )) && echo "[$(date -Is)] windows present: $n/100"
  fi
done <<<"$plan"

# Semantic gate: done_mask/token_stride, finiteness, non-degenerate windows.
python3 "$TOOL" check --download-dir "$DOWNLOAD_DIR"
du -sb "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
