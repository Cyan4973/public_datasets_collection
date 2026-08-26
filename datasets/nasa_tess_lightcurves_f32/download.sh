#!/usr/bin/env bash
# Download the exact public TESS products selected by metadata discovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_tess_lightcurves_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FITS_DIR="$DOWNLOAD_DIR/fits"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INVENTORY="$DOWNLOAD_DIR/download_inventory.tsv"
DOWNLOAD_API="https://mast.stsci.edu/api/v0.1/Download/file"

mkdir -p "$FITS_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

SELECTION="$RECIPE_DIR/selection.tsv"
[[ -s "$SELECTION" ]] || {
  echo "missing pinned selection: $SELECTION" >&2
  exit 1
}

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

fetch_if_needed "$DOWNLOAD_DIR/mast_tess_page.html" \
  "https://archive.stsci.edu/missions-and-data/tess" 5000000
fetch_if_needed "$DOWNLOAD_DIR/nasa_media_usage_guidelines.html" \
  "https://www.nasa.gov/nasa-brand-center/images-and-media/" 5000000

python3 - "$DOWNLOAD_DIR/nasa_media_usage_guidelines.html" <<'PY'
import html
from pathlib import Path
import re
import sys

text = html.unescape(Path(sys.argv[1]).read_text(errors="replace"))
text = re.sub(r"\s+", " ", text).lower()
if "generally are not subject to copyright in the united states" not in text:
    raise SystemExit("NASA usage page no longer contains expected copyright statement")
print("NASA rights evidence validated")
PY

python3 - "$SELECTION" <<'PY'
import csv
import hashlib
from pathlib import Path
import sys

source = Path(sys.argv[1])
with source.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 64:
    raise SystemExit(f"expected 64 selected products, found {len(rows)}")
required = {"obsid", "target_name", "sector", "data_uri", "filename", "size_bytes", "sha256", "source_row_count"}
if not rows or not required.issubset(rows[0]):
    raise SystemExit("selection schema mismatch")
if sum(int(row["size_bytes"]) for row in rows) != 126_650_880:
    raise SystemExit("selection source-byte total changed")
if sum(int(row["source_row_count"]) for row in rows) != 1_247_392:
    raise SystemExit("selection source-row total changed")
if len({row["target_name"] for row in rows}) != 8 or {int(row["sector"]) for row in rows} != set(range(61, 69)):
    raise SystemExit("selection target or sector coverage changed")
if len({row["data_uri"] for row in rows}) != 64 or len({row["filename"] for row in rows}) != 64:
    raise SystemExit("selection contains duplicate identities")
for row in rows:
    if not row["data_uri"].startswith("mast:TESS/product/"):
        raise SystemExit(f"invalid MAST URI: {row['data_uri']}")
    if len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"]):
        raise SystemExit(f"invalid SHA-256: {row['filename']}")
print(f"selected_products={len(rows)} selected_bytes={sum(int(row['size_bytes']) for row in rows)}")
PY

printf 'obsid\ttarget_name\tsector\tdata_uri\tfilename\tsize_bytes\tsha256\tsource_row_count\n' > "$INVENTORY"
total=0
while IFS=$'\t' read -r obsid target_name sector data_uri filename expected_size expected_sha source_rows; do
  encoded_uri="$(python3 - "$data_uri" <<'PY'
import sys
import urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
PY
)"
  url="$DOWNLOAD_API?uri=$encoded_uri"
  target="$FITS_DIR/$filename"
  fetch_if_needed "$target" "$url" 50000000
  size="$(stat -c %s "$target")"
  [[ "$size" == "$expected_size" ]] || {
    echo "MAST product size mismatch file=$filename size=$size expected=$expected_size" >&2
    exit 1
  }
  [[ "$(head -c 9 "$target")" == "SIMPLE  =" ]] || {
    echo "downloaded object is not FITS: $filename" >&2
    exit 1
  }
  sha256="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$sha256" == "$expected_sha" ]] || {
    echo "MAST product SHA-256 mismatch file=$filename sha256=$sha256 expected=$expected_sha" >&2
    exit 1
  }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$obsid" "$target_name" "$sector" "$data_uri" "$filename" "$size" "$sha256" "$source_rows" >> "$INVENTORY"
  total=$((total + size))
  [[ "$total" -le 300000000 ]] || {
    echo "TESS download total exceeds 300 MB cap: $total" >&2
    exit 1
  }
done < <(tail -n +2 "$SELECTION")

rows="$(($(wc -l < "$INVENTORY") - 1))"
[[ "$rows" == "64" ]] || { echo "download inventory has $rows products; expected 64" >&2; exit 1; }
echo "downloaded_products=$rows downloaded_bytes=$total"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
