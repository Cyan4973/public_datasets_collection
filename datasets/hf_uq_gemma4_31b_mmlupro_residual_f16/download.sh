#!/usr/bin/env bash
# Fetch the pinned uq-hiddenstates index, license cards, NPY headers and the
# selected Gemma-4-31B-it layer-45 MMLU-Pro trace row ranges (HTTP Range GETs).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
CANDIDATE_ID="hf_uq_gemma4_31b_mmlupro_residual_f16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$DATA_DIR/logs/$CANDIDATE_ID"
REPO="loose-bits/uq-hiddenstates"
REV="853e3392729d5ecc5663e4a635898085acc92109"
BASE="https://huggingface.co/datasets/$REPO"
GEMMA_REV="842da3794eaa0b77d5f08bae87a17459d91ff475"
MMLUPRO_REV="b189ec765aa7ed75c8acfea42df31fdae71f97be"
UA="openzl-public-datasets-uq-hiddenstates-download/1.0"
HEADER_BYTES=1024

mkdir -p "$DOWNLOAD_DIR/traces" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID revision=$REV"

# fetch <url> <dest> <bytes> <sha256>: small pinned file, reused when size and hash match.
fetch() {
  local url="$1" dest="$2" bytes="$3" sha="$4"
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$bytes" ]] \
    && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha" ]]; then
    return 0
  fi
  rm -f "$dest.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
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

# fetch_range <url> <dest> <start> <end>: byte range [start, end] of a remote file.
# Resumes from a partial .part file; each attempt must answer 206 with the
# requested slice (a server ignoring Range would exceed --max-filesize and abort;
# the limit has a 1 MiB floor because the Hugging Face 302 redirect body counts too).
fetch_range() {
  local url="$1" dest="$2" start="$3" end="$4"
  local expected=$((end - start + 1)) have=0 attempt code rc
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$expected" ]]; then
    return 0
  fi
  rm -f "$dest"
  if [[ -f "$dest.part" ]]; then have="$(stat -c %s "$dest.part")"; fi
  if (( have > expected )); then rm -f "$dest.part"; have=0; fi
  for attempt in $(seq 1 30); do
    if (( have == expected )); then break; fi
    rm -f "$dest.chunk"
    rc=0
    code="$(curl --silent --show-error --location --fail \
      --range "$((start + have))-$end" --speed-limit 1024 --speed-time 120 \
      --max-filesize "$(( expected - have + 1 > 1048576 ? expected - have + 1 : 1048576 ))" --user-agent "$UA" \
      --write-out '%{http_code}' --output "$dest.chunk" "$url")" || rc=$?
    if [[ "$code" == "206" ]] && [[ -f "$dest.chunk" ]]; then
      cat "$dest.chunk" >> "$dest.part"
    else
      echo "range attempt $attempt for $(basename "$dest") returned http=$code rc=$rc" >&2
    fi
    rm -f "$dest.chunk"
    have=0
    if [[ -f "$dest.part" ]]; then have="$(stat -c %s "$dest.part")"; fi
    if (( have > expected )); then
      echo "range overshoot for $(basename "$dest"): $have > $expected" >&2
      rm -f "$dest.part"; exit 1
    fi
    if (( have < expected )); then sleep 5; fi
  done
  if (( have != expected )); then
    echo "failed to fetch $(basename "$dest") after retries ($have/$expected bytes)" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
}

# 1. Pinned license cards and index.
fetch "$BASE/raw/$REV/README.md" "$DOWNLOAD_DIR/uq_hiddenstates_card.md" 2446 \
  "950b37c3db3dfb23a2693371b3ccd77eaf7455a932b62b6019cae2685fa8e62e"
fetch "https://huggingface.co/google/gemma-4-31B-it/raw/$GEMMA_REV/README.md" \
  "$DOWNLOAD_DIR/gemma4_31b_it_card.md" 27963 \
  "e209f5c435b1e66055bd6d7c29185103ae8d2027a03a96b359335154f206b82b"
fetch "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/raw/$MMLUPRO_REV/README.md" \
  "$DOWNLOAD_DIR/mmlu_pro_card.md" 11723 \
  "4bd710f67da3fa359a33edce1b4b5816b3de416c823c2624ba5e89c2557d2a47"
fetch "$BASE/resolve/$REV/gemma_mmlupro_L45.idx.json" "$DOWNLOAD_DIR/gemma_mmlupro_L45.idx.json" 138017 \
  "76307021af08a649f0cb578f11887528e156780d2c5463a218bf5048623eba55"

head -5 "$DOWNLOAD_DIR/uq_hiddenstates_card.md" | grep -qx 'license: apache-2.0' \
  || { echo "cache card no longer declares apache-2.0" >&2; exit 1; }
head -5 "$DOWNLOAD_DIR/gemma4_31b_it_card.md" | grep -qx 'license: apache-2.0' \
  || { echo "Gemma 4 card no longer declares apache-2.0" >&2; exit 1; }
head -8 "$DOWNLOAD_DIR/mmlu_pro_card.md" | grep -qx 'license: mit' \
  || { echo "MMLU-Pro card no longer declares mit" >&2; exit 1; }

# 2. Shard identity (LFS size + sha256 oid from the resolve redirect) and NPY headers.
check_shard() {
  local name="$1" size="$2" oid="$3" headers
  headers="$(curl --silent --show-error --max-time 60 --retry 5 --retry-delay 2 --head \
    --user-agent "$UA" "$BASE/resolve/$REV/$name" | tr -d '\r')"
  grep -qi "^x-linked-size: $size\$" <<<"$headers" \
    || { echo "$name: x-linked-size changed (expected $size)" >&2; exit 1; }
  grep -qi "^x-linked-etag: \"$oid\"\$" <<<"$headers" \
    || { echo "$name: x-linked-etag changed (expected $oid)" >&2; exit 1; }
}
check_shard gemma_mmlupro_L45.part00.npy 21459572864 4c186df9151b0e00134fc032e89306f13f8abc19d36425d670f05bfd81338bda
check_shard gemma_mmlupro_L45.part01.npy 14746378880 cff24898792133a9f252e8d92d67f708f3a76fe5bd677b7524cb1390f580b560
for s in 00 01; do
  fetch_range "$BASE/resolve/$REV/gemma_mmlupro_L45.part$s.npy" "$DOWNLOAD_DIR/header_part$s.bin" 0 "$((HEADER_BYTES - 1))"
done
python3 -I "$RECIPE_DIR/scripts/uq_hidden.py" check-headers --download-dir "$DOWNLOAD_DIR"

# 3. Selected trace row ranges (every 37th index item; see scripts/selected_items.tsv).
plan="$(python3 -I "$RECIPE_DIR/scripts/uq_hidden.py" plan --download-dir "$DOWNLOAD_DIR")"
count=0
while read -r shard item start end bytes; do
  fetch_range "$BASE/resolve/$REV/$shard" "$DOWNLOAD_DIR/traces/item_$item.f16" "$start" "$end"
  count=$((count + 1))
  echo "[$(date -Is)] trace $count item=$item shard=$shard bytes=$bytes"
done <<<"$plan"

# 4. Semantic validation (sizes, finiteness) and realized checksums.
python3 -I "$RECIPE_DIR/scripts/uq_hidden.py" validate --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done candidate=$CANDIDATE_ID traces=$count"
