#!/usr/bin/env bash
# Download the selected SDO/AIA FITS files and official CFITSIO source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_sdo_aia_synoptic_i32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FITS_DIR="$DOWNLOAD_DIR/fits"
TOOL_DIR="$DOWNLOAD_DIR/tool"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INVENTORY="$DOWNLOAD_DIR/download_inventory.tsv"

mkdir -p "$FITS_DIR" "$TOOL_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_if_needed() {
  local target="$1" url="$2" max_bytes="$3"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse existing $(basename "$target") bytes=$(stat -c %s "$target")"
    return
  fi
  local part="$target.part"
  rm -f "$part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 1800 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets/1.0" --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$DOWNLOAD_DIR/sdo_data_access.html" \
  "https://sdo.gsfc.nasa.gov/data/dataaccess.php" 5000000
fetch_if_needed "$DOWNLOAD_DIR/sdo_copyright.html" \
  "https://sdo.gsfc.nasa.gov/gallery/copyright/" 5000000
fetch_if_needed "$DOWNLOAD_DIR/nasa_media_usage_guidelines.html" \
  "https://www.nasa.gov/nasa-brand-center/images-and-media/" 5000000

python3 - "$DOWNLOAD_DIR/sdo_copyright.html" "$DOWNLOAD_DIR/nasa_media_usage_guidelines.html" <<'PY'
import html
from pathlib import Path
import re
import sys

sdo = re.sub(r"\s+", " ", html.unescape(Path(sys.argv[1]).read_text(errors="replace"))).lower()
nasa = re.sub(r"\s+", " ", html.unescape(Path(sys.argv[2]).read_text(errors="replace"))).lower()
if "sdo images and movies are not copyrighted unless explicitly noted" not in sdo:
    raise SystemExit("SDO copyright page no longer contains expected reuse statement")
if "generally are not subject to copyright in the united states" not in nasa:
    raise SystemExit("NASA usage page no longer contains expected copyright statement")
print("rights evidence validated")
PY

printf 'wavelength\turl\tlocal_path\tsize_bytes\tsha256\n' > "$INVENTORY"
tail -n +2 "$RECIPE_DIR/selection.tsv" |
while IFS=$'\t' read -r wavelength url expected_size expected_sha256 bitpix width height bscale bzero compression; do
  [[ "$bitpix" == "32" && "$width" == "1024" && "$height" == "1024" ]] || {
    echo "invalid selection row for wavelength=$wavelength" >&2
    exit 1
  }
  name="${url##*/}"
  target="$FITS_DIR/$name"
  fetch_if_needed "$target" "$url" 100000000
  size="$(stat -c %s "$target")"
  sha256="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$size" == "$expected_size" && "$sha256" == "$expected_sha256" ]] || {
    echo "FITS identity mismatch wavelength=$wavelength size=$size sha256=$sha256" >&2
    exit 1
  }
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$wavelength" "$url" "fits/$name" "$size" "$sha256" >> "$INVENTORY"
done

IFS=$'\t' read -r CFITSIO_VERSION CFITSIO_URL CFITSIO_NAME CFITSIO_SIZE CFITSIO_SHA256 < <(
  tail -n +2 "$RECIPE_DIR/tool_selection.tsv"
)
fetch_if_needed "$TOOL_DIR/$CFITSIO_NAME" "$CFITSIO_URL" 50000000
actual_tool_size="$(stat -c %s "$TOOL_DIR/$CFITSIO_NAME")"
actual_tool_sha256="$(sha256sum "$TOOL_DIR/$CFITSIO_NAME" | awk '{print $1}')"
[[ "$actual_tool_size" == "$CFITSIO_SIZE" && "$actual_tool_sha256" == "$CFITSIO_SHA256" ]] || {
  echo "CFITSIO source identity mismatch size=$actual_tool_size sha256=$actual_tool_sha256" >&2
  exit 1
}
printf 'url\tlocal_path\tsize_bytes\tsha256\n' > "$TOOL_DIR/source_inventory.tsv"
printf '%s\t%s\t%s\t%s\n' \
  "$CFITSIO_URL" "tool/$CFITSIO_NAME" "$actual_tool_size" \
  "$actual_tool_sha256" >> "$TOOL_DIR/source_inventory.tsv"

python3 - "$INVENTORY" <<'PY'
import csv
from pathlib import Path
import sys

with Path(sys.argv[1]).open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 10:
    raise SystemExit(f"download inventory has {len(rows)} FITS files; expected 10")
if len({row["wavelength"] for row in rows}) != 10:
    raise SystemExit("download inventory has duplicate wavelengths")
total = sum(int(row["size_bytes"]) for row in rows)
if total <= 0 or total > 1_000_000_000:
    raise SystemExit(f"FITS download total outside bounds: {total}")
print(f"fits_files={len(rows)} fits_bytes={total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
