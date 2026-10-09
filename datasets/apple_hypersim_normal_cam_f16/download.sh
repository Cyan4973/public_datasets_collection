#!/usr/bin/env bash
# Download one normal_cam G-buffer HDF5 member per selected Hypersim scene by
# HTTP range requests against the official scene zips, never the whole zips.
#
# Resources (all anonymous):
#   * apple/ml-hypersim README.md and evermotion_dataset/analysis/
#     metadata_images_split_scene_v1.csv at commit
#     3463c5c4a75f3cbfc65ed31cfd6e87204b3a2254 (sha256-pinned).  The README is
#     the CC BY-SA 3.0 license evidence; the CSV drives the frame selection,
#     which must reproduce sources.tsv exactly.
#   * for each of the 200 scenes in sources.tsv, byte ranges of
#     https://docs-assets.developer.apple.com/ml-research/datasets/hypersim/v1/scenes/<scene>.zip
#     (1.0-15.8 GB each, every member stored uncompressed):
#       1. the last 128 KiB  -> EOCD (+ zip64 EOCD locator/record) -> CD extent
#       2. the central directory (0.4-3 MB) -> local header offset, size and
#          CRC-32 of images/scene_<cam>_geometry_hdf5/frame.NNNN.normal_cam.hdf5
#       3. local header + member bytes (+1 KiB slack for a local extra field)
#     The local header name must equal the requested member, the member bytes
#     must match the central-directory CRC-32, and the member must decode as an
#     HDF5 file holding `dataset` = float16[768, 1024, 3] (full chunk decode).
#     Only the validated member (~0.5-2 MB) and a small JSON sidecar are kept;
#     tail/CD/slab scratch is deleted per scene.  Re-runs skip scenes whose
#     member + sidecar are already valid.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="apple_hypersim_normal_cam_f16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/members"
SCRATCH="$DOWNLOAD_DIR/scratch"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
COMMIT="3463c5c4a75f3cbfc65ed31cfd6e87204b3a2254"
RAW_BASE="https://raw.githubusercontent.com/apple/ml-hypersim/$COMMIT"
CSV_SHA256="47b7cce12f4659ffa31cf05e8fbf2aee3d69e1929d07b5ea25506603b69d5ce6"
README_SHA256="1141b4943d26a33e0c3b5efc0660db5088b0a972d51e2e52c7ef60044e7b851d"
EXPECTED_SCENES=200
TAIL_BYTES=131072
LOCAL_SLACK=1024
UA="openzl-public-datasets/1.0 ($DATASET_ID)"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR/upstream" "$MEMBER_DIR" "$SCRATCH" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID commit=$COMMIT data_root=$DATA_ROOT"

CURL=(curl --globoff --fail --silent --show-error --location --retry 10 --retry-delay 5
      --retry-all-errors --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

fetch_pinned() {
  local url="$1" target="$2" sha="$3"
  if [[ -f "$target" ]] && echo "$sha  $target" | sha256sum -c --status -; then
    return 0
  fi
  rm -f "$target.part"
  "${CURL[@]}" --max-filesize 20000000 --output "$target.part" "$url"
  if ! echo "$sha  $target.part" | sha256sum -c --status -; then
    echo "FATAL: sha256 mismatch for $url (got $(sha256sum "$target.part" | cut -c1-64))" >&2
    exit 1
  fi
  mv "$target.part" "$target"
}

# range_get URL START END OUT: fetch bytes [START, END] and insist on exact length.
range_get() {
  local url="$1" start="$2" end="$3" out="$4" attempt
  local want=$((end - start + 1))
  for attempt in 1 2 3 4 5; do
    rm -f "$out"
    if "${CURL[@]}" --range "$start-$end" --output "$out" "$url"; then
      if [[ "$(stat -c %s "$out")" == "$want" ]]; then
        return 0
      fi
      echo "range length mismatch attempt=$attempt url=$url range=$start-$end got=$(stat -c %s "$out") want=$want" >&2
    else
      echo "range curl failed attempt=$attempt url=$url range=$start-$end" >&2
    fi
    sleep $((attempt * 5))
  done
  echo "FATAL: could not fetch range $start-$end of $url" >&2
  return 1
}

# ---------------------------------------------------------- upstream metadata
fetch_pinned "$RAW_BASE/README.md" "$DOWNLOAD_DIR/upstream/README.md" "$README_SHA256"
grep -qF 'The Hypersim Dataset is licensed under the [Creative Commons Attribution-ShareAlike 3.0 Unported License](http://creativecommons.org/licenses/by-sa/3.0/).' \
  "$DOWNLOAD_DIR/upstream/README.md" || { echo "FATAL: README lacks the CC BY-SA 3.0 statement" >&2; exit 1; }
grep -qF 'frame.IIII.normal_cam.hdf5           # surface normals in camera-space (ignores bump mapping)' \
  "$DOWNLOAD_DIR/upstream/README.md" || { echo "FATAL: README lacks the normal_cam description" >&2; exit 1; }
echo "license evidence ok: README.md sha256=$README_SHA256 states CC BY-SA 3.0"

CSV="$DOWNLOAD_DIR/upstream/metadata_images_split_scene_v1.csv"
fetch_pinned "$RAW_BASE/evermotion_dataset/analysis/metadata_images_split_scene_v1.csv" "$CSV" "$CSV_SHA256"
python3 -I "$RECIPE_DIR/scripts/selection.py" "$CSV" > "$SCRATCH/selection.tsv"
if ! diff -q <(cut -f1-6 "$RECIPE_DIR/sources.tsv") "$SCRATCH/selection.tsv" >/dev/null; then
  echo "FATAL: selection re-derived from the pinned split CSV differs from sources.tsv" >&2
  exit 1
fi
echo "selection ok: sources.tsv matches the rule applied to the pinned split CSV"

# ------------------------------------------------------------ member extraction
header="scene_name	camera_name	frame_id	kept_frames_in_camera	member_name	zip_url	zip_size_bytes	zip_last_modified"
[[ "$(head -n 1 "$RECIPE_DIR/sources.tsv")" == "$header" ]] || { echo "FATAL: sources.tsv header changed" >&2; exit 1; }

count=0; fetched=0; reused=0; kept_bytes=0
while IFS=$'\t' read -r -u 3 scene cam frame _nframes member url zsize _lm; do
  [[ "$scene" == "scene_name" ]] && continue
  [[ "$scene" =~ ^ai_[0-9]{3}_[0-9]{3}$ && "$cam" =~ ^cam_[0-9]{2}$ && "$frame" =~ ^[0-9]+$ ]] || {
    echo "FATAL: malformed sources.tsv row: $scene $cam $frame" >&2; exit 1; }
  base="$scene.$cam.frame.$(printf '%04d' "$frame").normal_cam"
  out="$MEMBER_DIR/$base.hdf5"
  side="$MEMBER_DIR/$base.json"
  count=$((count + 1))
  if [[ -f "$out" && -f "$side" ]] && python3 -I "$RECIPE_DIR/scripts/validate_member.py" check "$out" "$side" "$member" "$zsize"; then
    reused=$((reused + 1))
    kept_bytes=$((kept_bytes + $(stat -c %s "$out")))
    continue
  fi
  rm -f "$out" "$side"
  work="$SCRATCH/$scene"
  rm -rf "$work"; mkdir -p "$work"
  tail_start=$((zsize - TAIL_BYTES))
  range_get "$url" "$tail_start" "$((zsize - 1))" "$work/tail.bin"
  res="$(python3 -I "$RECIPE_DIR/scripts/hypersim_zip.py" eocd "$work/tail.bin" "$tail_start" "$zsize")"
  read -r cd_off cd_size n_entries <<< "$res"
  if (( cd_off >= tail_start )); then
    python3 -I "$RECIPE_DIR/scripts/hypersim_zip.py" slice "$work/tail.bin" "$((cd_off - tail_start))" "$cd_size" "$work/cd.bin"
  else
    range_get "$url" "$cd_off" "$((cd_off + cd_size - 1))" "$work/cd.bin"
  fi
  res="$(python3 -I "$RECIPE_DIR/scripts/hypersim_zip.py" find "$work/cd.bin" "$member")"
  read -r loc_off msize crc nlen <<< "$res"
  slab_end=$((loc_off + 30 + nlen + LOCAL_SLACK + msize - 1))
  (( slab_end > zsize - 1 )) && slab_end=$((zsize - 1))
  range_get "$url" "$loc_off" "$slab_end" "$work/slab.bin"
  python3 -I "$RECIPE_DIR/scripts/hypersim_zip.py" extract "$work/slab.bin" "$member" "$msize" "$crc" "$work/member.hdf5"
  python3 -I "$RECIPE_DIR/scripts/validate_member.py" write "$work/member.hdf5" "$work/member.json" "$member" "$zsize" \
    "$url" "$cd_off" "$cd_size" "$n_entries" "$loc_off" "$msize" "$crc"
  mv "$work/member.json" "$side"
  mv "$work/member.hdf5" "$out"
  rm -rf "$work"
  fetched=$((fetched + 1))
  kept_bytes=$((kept_bytes + msize))
  echo "[$(date -Is)] $count/$EXPECTED_SCENES $scene $cam frame=$frame member_bytes=$msize zip_bytes=$zsize cd_bytes=$cd_size"
done 3< "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_SCENES" ]] || { echo "FATAL: scene count $count != $EXPECTED_SCENES" >&2; exit 1; }
n_members="$(find "$MEMBER_DIR" -maxdepth 1 -name '*.normal_cam.hdf5' | wc -l)"
[[ "$n_members" == "$EXPECTED_SCENES" ]] || { echo "FATAL: $n_members member files, expected $EXPECTED_SCENES (stray files?)" >&2; exit 1; }
rm -rf "$SCRATCH"
echo "[$(date -Is)] download done dataset=$DATASET_ID scenes=$count fetched=$fetched reused=$reused member_bytes=$kept_bytes"
