#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/dc_lidar_2015_intensity_u16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_intensity_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/las"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
BASE_URL="https://dc-lidar-2015.s3.amazonaws.com/Classified_LAS"
REUSE_DIRS=(
  "$REPO_ROOT/$DATA_DIR/downloads/dc_lidar_2015_classification_u8/las"
  "$REPO_ROOT/$DATA_DIR/downloads/dc_lidar_2015_gps_time_f64/las"
)

NAMES=(1812.las 2016.las 2315.las)
SIZES=(223634623 331834948 95485012)
HASHES=(
  757e683b350eb02678b1ca2d5406e4b31c3e0f8e726c5453b645058637b89660
  27fdb047a5aa4d329fdfc660c2420c99c4406e6284c329616545eab1cdb98488
  59fef9e2cca40bf696a9adff8a3cfb90de2857e6e8f002f2cfcec1c796d42bbe
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

check_file() {
  local path="$1" expected_size="$2" expected_hash="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(wc -c < "$path" | tr -d ' ')" == "$expected_size" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_hash" ]]
}

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  size="${SIZES[$i]}"
  hash="${HASHES[$i]}"
  target="$DOWNLOAD_DIR/$name"
  url="$BASE_URL/$name"

  if check_file "$target" "$size" "$hash"; then
    echo "validated existing $name"
    continue
  fi
  rm -f "$target" "$target.part"
  reused=false
  for reuse_dir in "${REUSE_DIRS[@]}"; do
    reuse="$reuse_dir/$name"
    if check_file "$reuse" "$size" "$hash"; then
      echo "reuse validated accepted-cache source $reuse"
      ln "$reuse" "$target" 2>/dev/null || cp --reflink=auto "$reuse" "$target"
      reused=true
      break
    fi
  done
  if [[ "$reused" != true ]]; then
    echo "fetch $url"
    curl --fail --location --retry 3 --retry-delay 2 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize 400000000 --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  if ! check_file "$target" "$size" "$hash"; then
    echo "size or SHA-256 validation failed for $name" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/las_intensity.py" inspect \
  "$DOWNLOAD_DIR/1812.las" "$DOWNLOAD_DIR/2016.las" "$DOWNLOAD_DIR/2315.las"

inventory="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/download_inventory.tsv"
printf 'source_url\tlocal_name\tbytes\tsha256\n' > "$inventory"
for i in "${!NAMES[@]}"; do
  printf '%s/%s\t%s\t%s\t%s\n' "$BASE_URL" "${NAMES[$i]}" \
    "${NAMES[$i]}" "${SIZES[$i]}" "${HASHES[$i]}" >> "$inventory"
done
echo "[$(date -Is)] download done dataset=$DATASET_ID"
