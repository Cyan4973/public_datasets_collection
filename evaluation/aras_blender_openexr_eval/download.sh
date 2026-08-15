#!/usr/bin/env bash
# Acquire pinned EXRs and TinyEXR into evaluation-only storage.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/evaluation/aras_blender_openexr_eval"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aras_blender_openexr_eval"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
DOWNLOAD_DIR="$EVAL_ROOT/downloads"
TOOL_DIR="$EVAL_ROOT/tools/tinyexr_v1.0.12"
LOG_DIR="$EVAL_ROOT/logs"
USER_AGENT="openzl-evaluation-exr/1.0"

mkdir -p "$DOWNLOAD_DIR" "$TOOL_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] evaluation download start dataset=$DATASET_ID"

valid_file() {
  local path="$1" size="$2" md5="$3" sha256="$4"
  [[ -f "$path" ]] \
    && [[ "$(wc -c < "$path" | tr -d ' ')" == "$size" ]] \
    && [[ "$(md5sum "$path" | awk '{print $1}')" == "$md5" ]] \
    && [[ "$(sha256sum "$path" | awk '{print $1}')" == "$sha256" ]]
}

printf 'source_name\twidth\theight\tdeclared_channel_layout\tsize_bytes\tmd5\tsha256\turl\n' \
  > "$DOWNLOAD_DIR/acquisition.tsv.part"
files=0
total_bytes=0
while IFS=$'\t' read -r kind name size md5 sha256 width height half_channels float_channels url; do
  [[ "$kind" == "kind" ]] && continue
  [[ -n "$kind" ]] || continue
  target_dir="$DOWNLOAD_DIR"
  [[ "$kind" == "tool" ]] && target_dir="$TOOL_DIR"
  target="$target_dir/$name"

  if valid_file "$target" "$size" "$md5" "$sha256"; then
    echo "validated existing kind=$kind name=$name bytes=$size"
  else
    reused=false
    for reuse_dir in \
      "$REPO_ROOT/$DATA_DIR/tools/tinyexr_v1.0.12" \
      "$REPO_ROOT/$DATA_DIR/downloads/polyhaven_hdri_exr_f32"; do
      candidate="$reuse_dir/$name"
      if valid_file "$candidate" "$size" "$md5" "$sha256"; then
        cp --reflink=auto "$candidate" "$target"
        echo "reused pinned local file name=$name from=$candidate"
        reused=true
        break
      fi
    done
    if [[ "$reused" != true ]]; then
      partial="$target.part"
      if [[ -f "$partial" && "$(wc -c < "$partial" | tr -d ' ')" -gt "$size" ]]; then
        rm -f "$partial"
      fi
      current_bytes=0
      [[ -f "$partial" ]] && current_bytes="$(wc -c < "$partial" | tr -d ' ')"
      echo "fetch kind=$kind name=$name bytes=$size resume_from=$current_bytes"
      curl --fail --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
        --connect-timeout 30 --max-time 7200 --max-filesize "$size" \
        --continue-at - --user-agent "$USER_AGENT" --output "$partial" "$url"
      if ! valid_file "$partial" "$size" "$md5" "$sha256"; then
        echo "pinned file identity mismatch: $name" >&2
        exit 1
      fi
      mv "$partial" "$target"
    fi
  fi

  if [[ "$kind" == "exr" ]]; then
    layout="half=$half_channels,float=$float_channels"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$name" "$width" "$height" "$layout" "$size" "$md5" "$sha256" "$url" \
      >> "$DOWNLOAD_DIR/acquisition.tsv.part"
    files=$((files + 1))
    total_bytes=$((total_bytes + size))
  fi
done < "$RECIPE_DIR/selection.tsv"

if [[ "$files" -ne 8 || "$total_bytes" -ne 1554393182 ]]; then
  echo "acquisition realization mismatch files=$files bytes=$total_bytes" >&2
  exit 1
fi
mv "$DOWNLOAD_DIR/acquisition.tsv.part" "$DOWNLOAD_DIR/acquisition.tsv"
echo "[$(date -Is)] evaluation download done files=$files bytes=$total_bytes"
