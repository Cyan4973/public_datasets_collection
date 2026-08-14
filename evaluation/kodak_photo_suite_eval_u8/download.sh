#!/usr/bin/env bash
# Acquire the canonical Kodak PNG suite into the evaluation-only data tree.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/evaluation/kodak_photo_suite_eval_u8"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="kodak_photo_suite_eval_u8"
EVAL_DIR="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
DOWNLOAD_DIR="$EVAL_DIR/downloads"
LOG_DIR="$EVAL_DIR/logs"
SOURCE_PAGE_URL="http://r0k.us/graphics/kodak/"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] evaluation download start dataset=$DATASET_ID"

page="$DOWNLOAD_DIR/source_page.html"
if [[ ! -s "$page" ]]; then
  curl --fail --silent --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
    --max-time 240 --max-filesize 2000000 --user-agent "openzl-evaluation/1.0" \
    --output "$page.part" "$SOURCE_PAGE_URL"
  mv "$page.part" "$page"
fi
python3 - "$page" <<'PY'
import re,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text(encoding="utf-8",errors="replace").lower()
if "kodak" not in text or not re.search(r"true.?color|kodim0?1",text):
    raise SystemExit("unexpected canonical Kodak source page")
PY

inventory="$DOWNLOAD_DIR/acquisition.tsv"
printf 'image_id\timage_name\twidth\theight\tsource_size_bytes\tsource_sha256\tdecoded_rgb_sha256\turl\n' > "$inventory.part"
valid_image() {
  local path="$1" expected_width="$2" expected_height="$3" expected_size="$4" expected_sha="$5" expected_decoded_sha="$6"
  local parsed width height size sha decoded_sha
  parsed="$(python3 "$RECIPE_DIR/scripts/kodak.py" source-info "$path" 2>/dev/null)" || return 1
  IFS=$'\t' read -r width height size sha decoded_sha <<< "$parsed"
  [[ "$width" == "$expected_width" && "$height" == "$expected_height" \
     && "$size" == "$expected_size" && "$sha" == "$expected_sha" \
     && "$decoded_sha" == "$expected_decoded_sha" ]]
}

while IFS=$'\t' read -r image_id image_name expected_width expected_height expected_size expected_sha expected_decoded_sha url; do
  [[ "$image_id" == "image_id" ]] && continue
  target="$DOWNLOAD_DIR/$image_name"
  if valid_image "$target" "$expected_width" "$expected_height" "$expected_size" "$expected_sha" "$expected_decoded_sha"; then
    echo "validated existing image=$image_name"
  else
    rm -f "$target" "$target.part"
    echo "fetch image=$image_name"
    curl --fail --silent --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
      --max-time 600 --max-filesize 10000000 --user-agent "openzl-evaluation/1.0" \
      --output "$target.part" "$url"
    valid_image "$target.part" "$expected_width" "$expected_height" "$expected_size" "$expected_sha" "$expected_decoded_sha" || {
      echo "pinned Kodak source identity mismatch image=$image_name" >&2; exit 1; }
    mv "$target.part" "$target"
    sleep 1
  fi
  info="$(python3 "$RECIPE_DIR/scripts/kodak.py" source-info "$target")"
  IFS=$'\t' read -r width height source_size source_sha decoded_sha <<< "$info"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$image_id" "$image_name" "$width" "$height" "$source_size" "$source_sha" "$decoded_sha" "$url" \
    >> "$inventory.part"
done < "$RECIPE_DIR/selection.tsv"
mv "$inventory.part" "$inventory"

python3 - "$inventory" <<'PY'
import csv,sys
from pathlib import Path
rows=list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8"),delimiter="\t"))
if len(rows)!=24 or len({r["image_id"] for r in rows})!=24:
    raise SystemExit("expected 24 unique Kodak images")
if any((int(r["width"]),int(r["height"])) not in {(768,512),(512,768)} for r in rows):
    raise SystemExit("unexpected Kodak image dimensions")
print(f"validated_images={len(rows)} projected_planes=72 projected_bytes={24*768*512*3}")
PY
echo "[$(date -Is)] evaluation download done dataset=$DATASET_ID"
