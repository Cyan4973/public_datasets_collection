#!/usr/bin/env bash
# Documents how the pins were resolved (run 2026-10-09). Not part of the acquisition path:
# fetches the 35 JunoCam volume INDEX.TAB files, derives the candidate list, fetches
# candidate labels, HEADs the selected images, fetches the selected volumes' md5 lists,
# and rewrites volumes.tsv, candidates.tsv and sources.tsv in the recipe directory.
# Usage: bash discover.sh [work_dir]   (default /tmp/autocollect/<id>/discover)
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="nasa_pds_juno_junocam_perijove_rgb_framelets_u8"
WORK="${1:-/tmp/autocollect/$DATASET_ID/discover}"
BASE="https://planetarydata.jpl.nasa.gov/img/data/juno"
mkdir -p "$WORK/index" "$WORK/labels" "$WORK/md5"
get() { [[ -s "$2" ]] || curl -fsSL --retry 5 --retry-delay 5 --speed-limit 1024 --speed-time 120 -o "$2" "$1"; }
for n in $(seq 1 35); do
  vol="$(printf 'JNOJNC_%04d' "$n")"
  get "$BASE/$vol/INDEX/INDEX.TAB" "$WORK/index/${vol}_INDEX.TAB"
done
python3 "$RECIPE_DIR/scripts/pins.py" candidates --work "$WORK" --recipe-dir "$RECIPE_DIR"
awk -F'\t' 'NR > 1 {print $6 "\t" $1}' "$RECIPE_DIR/candidates.tsv" | while IFS=$'\t' read -r url pid; do
  get "$url" "$WORK/labels/$pid.LBL"
done
# Provisional selection to learn which images to HEAD and which md5 lists to read.
: > "$WORK/heads.tsv"
python3 - "$WORK" "$RECIPE_DIR" <<'PY' > "$WORK/selected.tsv"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[2]) / "scripts"))
import junocam as jc
for item in jc.select(jc.candidates(Path(sys.argv[1]) / "index"), Path(sys.argv[1]) / "labels"):
    print(f"{item['product_id']}\t{item['volume']}\t{jc.BASE_URL}/{item['volume']}/{item['label_path'][:-4]}.IMG")
PY
while IFS=$'\t' read -r pid vol url; do
  size="$(curl -fsSIL --max-time 60 "$url" | tr -d '\r' | awk 'tolower($1)=="content-length:" {v=$2} END {print v}')"
  printf '%s\t%s\n' "$pid" "$size" >> "$WORK/heads.tsv"
  get "$BASE/${vol}_md5.txt" "$WORK/md5/${vol}_md5.txt"
done < "$WORK/selected.tsv"
python3 "$RECIPE_DIR/scripts/pins.py" sources --work "$WORK" --recipe-dir "$RECIPE_DIR"
