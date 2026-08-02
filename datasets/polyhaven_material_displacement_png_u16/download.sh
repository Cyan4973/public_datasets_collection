#!/usr/bin/env bash
# Download eight exact CC0 Poly Haven grayscale16 displacement maps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_material_displacement_png_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

download_one() {
  local name="$1"
  local size="$2"
  local md5="$3"
  local url="$4"
  local target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] && \
      [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "verified cached $name"
    return
  fi
  rm -f "$target.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 \
    --output "$target.part" "$url"
  local actual_size actual_md5
  actual_size="$(stat -c %s "$target.part")"
  actual_md5="$(md5sum "$target.part" | awk '{print $1}')"
  [[ "$actual_size" == "$size" ]] || { echo "size mismatch for $name: $actual_size != $size" >&2; exit 1; }
  [[ "$actual_md5" == "$md5" ]] || { echo "MD5 mismatch for $name: $actual_md5 != $md5" >&2; exit 1; }
  mv "$target.part" "$target"
  echo "downloaded and verified $name"
}

download_one "black_painted_planks_disp_1k.png" 1033118 a2f1a8983e70687538946bff5d737a08 \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/black_painted_planks/black_painted_planks_disp_1k.png"
download_one "concrete_wall_008_disp_1k.png" 1108458 98c7c2c3cccb4f5992e09c77ee3e6706 \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/concrete_wall_008/concrete_wall_008_disp_1k.png"
download_one "decrepit_wallpaper_disp_1k.png" 1473765 92590700030fda709fbecf20f2c33653 \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/decrepit_wallpaper/decrepit_wallpaper_disp_1k.png"
download_one "marble_cliff_01_disp_1k.png" 1494165 4a976db8538f16444e54e708d82666c2 \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/marble_cliff_01/marble_cliff_01_disp_1k.png"
download_one "rusty_metal_03_disp_1k.png" 1643570 6b560f4adaab0a436283c4ccf1692782 \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/rusty_metal_03/rusty_metal_03_disp_1k.png"
download_one "trident_maple_bark_disp_1k.png" 1687901 4472649d09f2b4fc2c0cb5072f2fb42f \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/trident_maple_bark/trident_maple_bark_disp_1k.png"
download_one "gravelly_sand_disp_1k.png" 1694619 592e4c98c6d4ccc821547f5fb9e1e11b \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/gravelly_sand/gravelly_sand_disp_1k.png"
download_one "denim_fabric_06_disp_1k.png" 1995611 47b98dd5e19439255e76ac66f329c02e \
  "https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/denim_fabric_06/denim_fabric_06_disp_1k.png"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
