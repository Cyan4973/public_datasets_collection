#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_eclipse_rtdose_u32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-25000000}"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start dataset=$DATASET_ID"

BASE_URL="https://services.cancerimagingarchive.net/nbia-api/services/v1"
METADATA="$DOWNLOAD_DIR/series_metadata.json"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --max-time 180 --output "$METADATA.part" \
  "$BASE_URL/getSeries?Collection=Pancreatic-CT-CBCT-SEG&Modality=RTDOSE"

python3 - "$METADATA.part" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


expected = {
    "1.3.6.1.4.1.14519.5.2.1.337132488476568438964794321553967230469": 8383680,
    "1.3.6.1.4.1.14519.5.2.1.132957944596075614237465645641313092885": 8771960,
    "1.3.6.1.4.1.14519.5.2.1.277895508499534253640451142336498460409": 9839814,
}


def field(row: dict[str, object], *names: str) -> str:
    lower = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lower.get(name.lower())
        if value is not None:
            return str(value).strip()
    return ""


rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(rows, list):
    raise SystemExit("TCIA metadata response is not an array")
found = {}
for row in rows:
    if not isinstance(row, dict):
        continue
    uid = field(row, "SeriesInstanceUID")
    if uid not in expected:
        continue
    required = {
        "Collection": "Pancreatic-CT-CBCT-SEG",
        "Modality": "RTDOSE",
        "BodyPartExamined": "ABDOMEN",
        "Manufacturer": "Varian Medical Systems",
        "ManufacturerModelName": "ARIA RadOnc",
        "SeriesDescription": "Eclipse Doses",
    }
    for key, value in required.items():
        if field(row, key) != value:
            raise SystemExit(f"metadata changed for {uid}: {key}={field(row, key)!r}")
    license_text = f"{field(row, 'LicenseName', 'License')} {field(row, 'LicenseURI', 'LicenseURL')}".lower()
    if not (
        "cc by 4.0" in license_text
        or "creativecommons.org/licenses/by/4.0" in license_text
    ):
        raise SystemExit(f"series no longer declares CC BY 4.0: {uid}: {license_text!r}")
    if int(field(row, "ImageCount", "ImageCountInSeries") or 0) != 1:
        raise SystemExit(f"expected one DICOM object for {uid}")
    if int(field(row, "FileSize", "SeriesSize", "TotalSize") or 0) != expected[uid]:
        raise SystemExit(f"source DICOM size changed for {uid}")
    if uid in found:
        raise SystemExit(f"duplicate metadata row for {uid}")
    found[uid] = row
missing = sorted(set(expected) - set(found))
if missing:
    raise SystemExit(f"pinned series missing from TCIA metadata: {missing}")
studies = {field(row, "StudyInstanceUID") for row in found.values()}
if "" in studies or len(studies) != 3:
    raise SystemExit("pinned series no longer represent three distinct studies")
print("metadata_validation=ok series=3 studies=3 license=CC-BY-4.0")
PY
mv "$METADATA.part" "$METADATA"

while IFS=$'\t' read -r ordinal uid; do
  target="$DOWNLOAD_DIR/${ordinal}_${uid}.zip"
  if [[ -f "$target" ]] && (( $(stat -c %s "$target") > 0 )) && (( $(stat -c %s "$target") <= MAX_FILE_BYTES )); then
    echo "reuse $(basename "$target") bytes=$(stat -c %s "$target")"
    continue
  fi
  rm -f "$target.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 600 --max-filesize "$MAX_FILE_BYTES" \
    --output "$target.part" "$BASE_URL/getImage?SeriesInstanceUID=$uid"
  actual_bytes="$(stat -c %s "$target.part")"
  if (( actual_bytes <= 0 || actual_bytes > MAX_FILE_BYTES )); then
    echo "download outside bounds: $target.part ($actual_bytes bytes)" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
  echo "downloaded $(basename "$target") bytes=$actual_bytes"
done <<'EOF'
01	1.3.6.1.4.1.14519.5.2.1.337132488476568438964794321553967230469
02	1.3.6.1.4.1.14519.5.2.1.132957944596075614237465645641313092885
03	1.3.6.1.4.1.14519.5.2.1.277895508499534253640451142336498460409
EOF

export DOWNLOAD_DIR MAX_FILE_BYTES
python3 - <<'PY'
from pathlib import Path
import os
import zipfile


root = Path(os.environ["DOWNLOAD_DIR"])
archives = sorted(root.glob("*.zip"))
if len(archives) != 3:
    raise SystemExit(f"expected exactly three ZIP archives, found {len(archives)}")
for archive in archives:
    if archive.stat().st_size > int(os.environ["MAX_FILE_BYTES"]):
        raise SystemExit(f"archive exceeds bound: {archive}")
    with zipfile.ZipFile(archive) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        dicom_members = []
        licenses = []
        for member in members:
            with zf.open(member) as source:
                head = source.read(132)
            if head[128:132] == b"DICM":
                dicom_members.append(member)
            if Path(member.filename).name.upper() == "LICENSE":
                licenses.append(zf.read(member).decode("utf-8", "replace"))
        if len(dicom_members) != 1:
            raise SystemExit(f"expected one DICOM object in {archive}, found {len(dicom_members)}")
        if len(licenses) != 1 or "CC BY 4.0" not in licenses[0]:
            raise SystemExit(f"missing embedded CC BY 4.0 license in {archive}")
print("archive_validation=ok archives=3 dicom_objects=3")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
