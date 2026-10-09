#!/usr/bin/env bash
# Regenerate sources.tsv (documentation of how resources were resolved; not
# part of the download/build path).  Fetches the pinned split CSV (~3 MB),
# applies scripts/selection.py, and HEADs each selected scene zip to pin its
# Content-Length and Last-Modified.  No scene payload bytes are fetched.
set -euo pipefail

DATASET_ID="apple_hypersim_normal_cam_f16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMIT="3463c5c4a75f3cbfc65ed31cfd6e87204b3a2254"
CSV_URL="https://raw.githubusercontent.com/apple/ml-hypersim/${COMMIT}/evermotion_dataset/analysis/metadata_images_split_scene_v1.csv"
CSV_SHA256="47b7cce12f4659ffa31cf05e8fbf2aee3d69e1929d07b5ea25506603b69d5ce6"

work="$(mktemp -d "${TMPDIR:-/tmp}/${DATASET_ID}.discover.XXXXXX")"
trap 'rm -rf "$work"' EXIT

curl -fsSL --retry 5 --max-time 300 -o "$work/split.csv" "$CSV_URL"
echo "$CSV_SHA256  $work/split.csv" | sha256sum -c - >/dev/null
python3 -I "$RECIPE_DIR/scripts/selection.py" "$work/split.csv" > "$work/selection.tsv"

out="$work/sources.tsv"
{
  head -n 1 "$work/selection.tsv" | tr -d '\n'
  printf '\tzip_size_bytes\tzip_last_modified\n'
} > "$out"
tail -n +2 "$work/selection.tsv" | while IFS=$'\t' read -r scene cam frame nframes member url; do
  hdr="$(curl -fsSIL --retry 5 --max-time 60 "$url" | tr -d '\r')"
  size="$(printf '%s\n' "$hdr" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  lm="$(printf '%s\n' "$hdr" | awk 'tolower($1)=="last-modified:"{sub(/^[^:]*: /,""); v=$0} END{print v}')"
  if [[ -z "$size" || "$size" -lt 1000000 ]]; then
    echo "bad Content-Length for $url: '$size'" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$scene" "$cam" "$frame" "$nframes" "$member" "$url" "$size" "$lm" >> "$out"
done
cp "$out" "$RECIPE_DIR/sources.tsv"
echo "wrote $RECIPE_DIR/sources.tsv ($(($(wc -l < "$out") - 1)) rows)"
