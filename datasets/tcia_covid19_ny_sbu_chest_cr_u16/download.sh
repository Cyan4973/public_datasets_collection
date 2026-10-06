#!/usr/bin/env bash
# Fetch the 48 pinned COVID-19-NY-SBU Carestream DRX-Revolution AP chest CR
# DICOM objects (one per patient) from the public TCIA NBIA API.
#
# Per pinned series: a small getSeries?StudyInstanceUID= call re-validates the
# live CC BY 4.0 license and series metadata, then getSingleImage fetches the
# complete DICOM object. The server ignores Range requests (chunked transfer,
# no Content-Length), so each ~15.5 MB object is fetched whole into a .part
# file, checked against its pinned size and header SHA-256, fully parsed, and
# only then renamed into place. Re-runs skip objects that already validate.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_covid19_ny_sbu_chest_cr_u16"
BASE_URL="https://services.cancerimagingarchive.net/nbia-api/services/v1"
PINS="$RECIPE_DIR/pinned_series.tsv"
PINS_SHA256="68c20df34c05b2e16e98aa4e554c511625d3240db2f31ad2316d49aba6b6ba9d"
EXPECTED_IMAGES=48
EXPECTED_DICOM_BYTES=746512192
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
IMAGE_DIR="$DOWNLOAD_DIR/images"
META_DIR="$DOWNLOAD_DIR/metadata"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PARSER="$RECIPE_DIR/scripts/cr_dicom.py"
UA="openzl-public-datasets-tcia-sbu-cr/1.0"

mkdir -p "$IMAGE_DIR" "$META_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

printf '%s  %s\n' "$PINS_SHA256" "$PINS" | sha256sum --check --status || {
  echo "FATAL: pinned_series.tsv checksum changed" >&2
  exit 1
}
python3 "$PARSER" selftest

validate_metadata() {
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json
import sys
from pathlib import Path

path, series, patient, study, file_size = sys.argv[1:6]
rows = json.loads(Path(path).read_text(encoding="utf-8"))
if not isinstance(rows, list):
    raise SystemExit(f"FATAL: getSeries response is not a JSON list: {path}")
matches = [row for row in rows if row.get("SeriesInstanceUID") == series]
if len(matches) != 1:
    raise SystemExit(f"FATAL: pinned series missing from study metadata: {series}")
row = matches[0]
expected = {
    "Collection": "COVID-19-NY-SBU",
    "Modality": "CR",
    "Manufacturer": "CARESTREAM HEALTH",
    "ManufacturerModelName": "DRX-REVOLUTION",
    "BodyPartExamined": "CHEST",
    "SeriesDescription": "AP",
    "PatientID": patient,
    "StudyInstanceUID": study,
    "ImageCount": 1,
    "FileSize": int(file_size),
    "LicenseURI": "https://creativecommons.org/licenses/by/4.0/",
    "CollectionURI": "https://doi.org/10.7937/TCIA.BBAG-2923",
}
for key, value in expected.items():
    if row.get(key) != value:
        raise SystemExit(f"FATAL: {series}: metadata {key}={row.get(key)!r}, expected {value!r}")
if "Attribution 4.0" not in str(row.get("LicenseName", "")):
    raise SystemExit(f"FATAL: {series}: license name changed: {row.get('LicenseName')!r}")
PY
}

count=0
total_bytes=0
while IFS=$'\t' read -r -u 3 ordinal patient study series sop file_size header_bytes header_sha256 software study_desc; do
  [ "$ordinal" = "ordinal" ] && continue
  count=$((count + 1))
  label="$(printf '%02d' "$ordinal")"
  meta="$META_DIR/$study.json"
  if [ ! -s "$meta" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$meta.part"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 3 --retry-all-errors \
      --max-time 120 --max-filesize 2000000 --user-agent "$UA" \
      --output "$meta.part" "$BASE_URL/getSeries?StudyInstanceUID=$study"
    mv "$meta.part" "$meta"
  fi
  validate_metadata "$meta" "$series" "$patient" "$study" "$file_size"

  final="$IMAGE_DIR/${label}_${series}.dcm"
  if [ -s "$final" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if python3 "$PARSER" validate --pins "$PINS" --series "$series" --file "$final"; then
      echo "cache_hit ordinal=$label"
      total_bytes=$((total_bytes + file_size))
      continue
    fi
    echo "cached object failed validation; refetching ordinal=$label"
    rm -f "$final"
  fi

  part="$final.part"
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$part"
    if curl --fail --silent --show-error --location \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((file_size + 65536))" --user-agent "$UA" \
      --output "$part" \
      "$BASE_URL/getSingleImage?SeriesInstanceUID=$series&SOPInstanceUID=$sop"; then
      actual="$(stat -c %s "$part")"
      if [ "$actual" = "$file_size" ]; then
        ok=1
        break
      fi
      echo "size mismatch ordinal=$label attempt=$attempt actual=$actual expected=$file_size"
    else
      echo "curl failed ordinal=$label attempt=$attempt"
    fi
    sleep $((attempt * 5))
  done
  if [ "$ok" != "1" ]; then
    echo "FATAL: could not fetch a complete object for ordinal=$label series=$series" >&2
    exit 1
  fi
  python3 "$PARSER" validate --pins "$PINS" --series "$series" --file "$part"
  mv "$part" "$final"
  total_bytes=$((total_bytes + file_size))
  echo "fetched ordinal=$label bytes=$file_size"
done 3< "$PINS"

if [ "$count" != "$EXPECTED_IMAGES" ] || [ "$total_bytes" != "$EXPECTED_DICOM_BYTES" ]; then
  echo "FATAL: realized count=$count bytes=$total_bytes, expected $EXPECTED_IMAGES / $EXPECTED_DICOM_BYTES" >&2
  exit 1
fi

python3 - "$PINS" "$IMAGE_DIR" "$DOWNLOAD_DIR/download_inventory.json" "$DATASET_ID" <<'PY'
import csv
import hashlib
import json
import sys
from pathlib import Path

pins_path, image_dir, out_path, dataset_id = sys.argv[1:5]
with open(pins_path, encoding="utf-8", newline="") as handle:
    pins = list(csv.DictReader(handle, delimiter="\t"))
records = []
for pin in pins:
    name = f"{int(pin['ordinal']):02d}_{pin['series_instance_uid']}.dcm"
    path = Path(image_dir) / name
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    if path.stat().st_size != int(pin["file_size"]):
        raise SystemExit(f"FATAL: {name} size changed")
    records.append({"bytes": path.stat().st_size, "file": name, "sha256": digest.hexdigest()})
extra = sorted(p.name for p in Path(image_dir).iterdir() if p.name not in {r["file"] for r in records})
if extra:
    raise SystemExit(f"FATAL: unexpected files in image directory: {extra}")
payload = {
    "dataset_id": dataset_id,
    "images": len(records),
    "license": "CC-BY-4.0",
    "records": records,
    "total_bytes": sum(r["bytes"] for r in records),
}
Path(out_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"inventory images={payload['images']} total_bytes={payload['total_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID images=$count bytes=$total_bytes"
