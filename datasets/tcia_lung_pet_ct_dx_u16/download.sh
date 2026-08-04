#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="tcia_lung_pet_ct_dx_u16"
# Exact live TCIA collection selected by metadata discovery.
COLLECTION="Lung-PET-CT-Dx"
BASE_URL="https://services.cancerimagingarchive.net/nbia-api/services/v1"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LEGACY_DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/tcia_lung_pet_ct_dx_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MAX_ARCHIVE_BYTES="${MAX_ARCHIVE_BYTES:-100000000}"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download_probe.$RUN_TS.log" "$LOG_DIR/download_probe.latest.log") 2>&1
echo "[$(date -Is)] PET download start dataset=$CANDIDATE_ID"

METADATA="$DOWNLOAD_DIR/series_metadata.json"
if [[ ! -f "$METADATA" && -f "$LEGACY_DOWNLOAD_DIR/series_metadata.json" ]]; then
  cp --reflink=auto "$LEGACY_DOWNLOAD_DIR/series_metadata.json" "$METADATA"
  echo "reused validated predecessor metadata cache"
fi
if [[ -f "$METADATA" ]]; then
  cp --reflink=auto "$METADATA" "$METADATA.part"
else
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --max-time 180 --max-filesize 25000000 \
  --output "$METADATA.part" \
  "$BASE_URL/getSeries?Collection=$COLLECTION&Modality=PT"
fi

python3 - "$METADATA.part" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


EXPECTED = {
    "1.3.6.1.4.1.14519.5.2.1.6655.2359.139687047425239659671031900378": (136, 11_457_758),
    "1.3.6.1.4.1.14519.5.2.1.6655.2359.172915770919067984477698394110": (145, 12_215_784),
    "1.3.6.1.4.1.14519.5.2.1.6655.2359.226901752069119903728752256048": (171, 14_394_514),
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
found: dict[str, dict[str, object]] = {}
for row in rows:
    if not isinstance(row, dict):
        continue
    uid = field(row, "SeriesInstanceUID")
    if uid not in EXPECTED:
        continue
    expected_images, expected_bytes = EXPECTED[uid]
    if field(row, "Collection") != "Lung-PET-CT-Dx" or field(row, "Modality") != "PT":
        raise SystemExit(f"collection or modality changed for {uid}")
    if field(row, "SeriesDescription") != "PET WB Corrected":
        raise SystemExit(f"series description changed for {uid}")
    license_text = f"{field(row, 'LicenseName', 'License')} {field(row, 'LicenseURI', 'LicenseURL')}".lower()
    if not (
        "cc by 4.0" in license_text
        or "creativecommons.org/licenses/by/4.0" in license_text
    ):
        raise SystemExit(f"series no longer declares CC BY 4.0: {uid}")
    images = int(float(field(row, "ImageCount", "ImageCountInSeries") or 0))
    size = int(float(field(row, "FileSize", "SeriesSize", "TotalSize") or 0))
    if (images, size) != (expected_images, expected_bytes):
        raise SystemExit(
            f"series metadata changed for {uid}: {(images, size)} != {(expected_images, expected_bytes)}"
        )
    found[uid] = row
missing = sorted(set(EXPECTED) - set(found))
if missing:
    raise SystemExit(f"pinned PET series missing: {missing}")
print("metadata_validation=ok series=3 license=CC-BY-4.0 images=452 bytes=38068056")
PY
mv "$METADATA.part" "$METADATA"

while IFS=$'\t' read -r ordinal uid; do
  target="$DOWNLOAD_DIR/${ordinal}_${uid}.zip"
  legacy_target="$LEGACY_DOWNLOAD_DIR/${ordinal}_${uid}.zip"
  if [[ ! -f "$target" && -f "$legacy_target" ]] && (( $(stat -c %s "$legacy_target") > 0 )) && (( $(stat -c %s "$legacy_target") <= MAX_ARCHIVE_BYTES )); then
    cp --reflink=auto "$legacy_target" "$target"
    echo "reused validated predecessor archive $(basename "$target") bytes=$(stat -c %s "$target")"
  fi
  if [[ -f "$target" ]] && (( $(stat -c %s "$target") > 0 )) && (( $(stat -c %s "$target") <= MAX_ARCHIVE_BYTES )); then
    echo "reuse $(basename "$target") bytes=$(stat -c %s "$target")"
    continue
  fi
  rm -f "$target.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 900 --max-filesize "$MAX_ARCHIVE_BYTES" \
    --output "$target.part" "$BASE_URL/getImage?SeriesInstanceUID=$uid"
  actual_bytes="$(stat -c %s "$target.part")"
  if (( actual_bytes <= 0 || actual_bytes > MAX_ARCHIVE_BYTES )); then
    echo "download outside bounds: $target.part ($actual_bytes bytes)" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
  echo "downloaded $(basename "$target") bytes=$actual_bytes"
done <<'EOF'
01	1.3.6.1.4.1.14519.5.2.1.6655.2359.139687047425239659671031900378
02	1.3.6.1.4.1.14519.5.2.1.6655.2359.172915770919067984477698394110
03	1.3.6.1.4.1.14519.5.2.1.6655.2359.226901752069119903728752256048
EOF

export DOWNLOAD_DIR MAX_ARCHIVE_BYTES
python3 - <<'PY'
from pathlib import Path
import os
import zipfile


EXPECTED_IMAGES = {"01": 136, "02": 145, "03": 171}
root = Path(os.environ["DOWNLOAD_DIR"])
archives = sorted(root.glob("*.zip"))
if len(archives) != 3:
    raise SystemExit(f"expected exactly three ZIP archives, found {len(archives)}")
for archive in archives:
    ordinal = archive.name.split("_", 1)[0]
    if archive.stat().st_size > int(os.environ["MAX_ARCHIVE_BYTES"]):
        raise SystemExit(f"archive exceeds bound: {archive}")
    if not zipfile.is_zipfile(archive):
        raise SystemExit(f"not a ZIP archive: {archive}")
    with zipfile.ZipFile(archive) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        dicom_count = 0
        licenses = []
        for member in members:
            if member.flag_bits & 0x1:
                raise SystemExit(f"encrypted ZIP member: {archive}: {member.filename}")
            with zf.open(member) as source:
                head = source.read(132)
            if head[128:132] == b"DICM":
                dicom_count += 1
            if Path(member.filename).name.upper() == "LICENSE":
                licenses.append(zf.read(member).decode("utf-8", "replace"))
        if dicom_count != EXPECTED_IMAGES[ordinal]:
            raise SystemExit(
                f"DICOM count changed for {archive.name}: {dicom_count}/{EXPECTED_IMAGES[ordinal]}"
            )
        if len(licenses) != 1 or "CC BY 4.0" not in licenses[0]:
            raise SystemExit(f"embedded CC BY 4.0 license missing from {archive}")
print("archive_validation=ok archives=3 dicom_objects=452")
PY

echo "[$(date -Is)] PET download done dataset=$CANDIDATE_ID"
