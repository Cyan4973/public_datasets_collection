#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_mturk_fitbit_heartrate_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-fitbit-hr-download/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Zenodo record 53894 (DOI 10.5281/zenodo.53894), CC-BY-4.0. Sizes and MD5s
# are pinned from https://zenodo.org/api/records/53894.
# filename  size_bytes  md5
FILES=(
  "mturkfitbit_export_3.12.16-4.11.16.zip 20410739 88a4396c5ff706b7eaed030de4c53588"
  "mturkfitbit_export_4.12.16-5.12.16.zip 25291915 7afbecdce29814e1be2e9a7c94f8f165"
)

for entry in "${FILES[@]}"; do
  read -r name size md5 <<< "$entry"
  target="$DOWNLOAD_DIR/$name"
  url="https://zenodo.org/records/53894/files/$name?download=1"
  if [[ -s "$target" ]] && [[ "$(stat -c %s "$target")" = "$size" ]]; then
    echo "cache_hit file=$name bytes=$size"
  else
    rm -f "$target"
    echo "fetch file=$name bytes=$size url=$url"
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$target.part" "$url"
    actual="$(stat -c %s "$target.part")"
    if [[ "$actual" != "$size" ]]; then
      echo "size mismatch file=$name expected=$size actual=$actual" >&2
      exit 1
    fi
    mv "$target.part" "$target"
  fi
  if ! printf '%s  %s\n' "$md5" "$target" | md5sum --check --status; then
    echo "MD5 mismatch file=$name; removing" >&2
    rm -f "$target"
    exit 1
  fi
  echo "md5_ok file=$name sha256=$(sha256sum "$target" | awk '{print $1}')"
done

# Semantic validation: the heart-rate members must exist with the pinned
# uncompressed size and CRC32, carry the Id,Time,Value header, and every row
# must parse with a heart rate in 1..255.
python3 -I "$RECIPE_DIR/scripts/fitbit_hr.py" check-download \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
