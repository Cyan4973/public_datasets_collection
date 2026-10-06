#!/usr/bin/env bash
# Documents how sources.tsv was resolved: fetch the Dataverse version-1.1
# listing (one small JSON request), regenerate the 19-row source table from it,
# and diff it against the committed sources.tsv. Downloads no data files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icraf_afsis1_soil_mir_spectra_f32"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
URL="https://data.worldagroforestry.org/api/datasets/:persistentId/versions/1.1?persistentId=doi:10.34725/DVN/QXCWP1"
mkdir -p "$OUT_DIR"

curl --fail --location --silent --show-error --retry 10 --retry-all-errors \
  --retry-delay 15 --connect-timeout 30 --max-time 300 \
  --output "$OUT_DIR/dataset_version_1.1.json" "$URL"

python3 - "$OUT_DIR/dataset_version_1.1.json" > "$OUT_DIR/sources.regenerated.tsv" <<'PY'
import json
import re
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
print("datafile_id\tlocal_filename\tupstream_ingested_name\tcountry_column_value\toriginal_size_bytes\toriginal_md5")
rows = []
for entry in data["files"]:
    f = entry["dataFile"]
    if f.get("originalFileFormat") != "text/csv":
        continue  # skips datafile 10842, "0. Disclaimer.pdf"
    label = f["filename"].removesuffix(".tab")
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    slug = {"safrica": "south_africa", "zimbambwe": "zimbabwe"}.get(slug, slug)
    rows.append((f["id"], f"{f['id']}_{slug}.csv", f["filename"], label, f["originalFileSize"], f["md5"]))
for row in sorted(rows):
    print("\t".join(map(str, row)))
PY

# country_column_value equals the upstream label for all 19 files; this was
# confirmed on 2026-10-05 by reading the first row of each original CSV.
diff "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.regenerated.tsv" && echo "sources.tsv matches the live version-1.1 listing"
