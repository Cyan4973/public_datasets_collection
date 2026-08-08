#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="tcia_cmmd_mammography_u16"
COLLECTION="CMMD"
SERIES_UID="1.3.6.1.4.1.14519.5.2.1.1239.1759.338921544064671779799433793481"
STUDY_UID="1.3.6.1.4.1.14519.5.2.1.1239.1759.195542464785425982618478565588"
BASE_URL="https://services.cancerimagingarchive.net/nbia-api/services/v1"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MAX_ARCHIVE_BYTES="${MAX_ARCHIVE_BYTES:-100000000}"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

METADATA="$DOWNLOAD_DIR/series_metadata.json"
if [[ -s "$METADATA" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "metadata_cache_hit bytes=$(stat -c %s "$METADATA")"
elif [[ -s "$DISCOVERY_DIR/series_metadata.json" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  cp --reflink=auto "$DISCOVERY_DIR/series_metadata.json" "$METADATA"
  echo "metadata_reused_from_discovery bytes=$(stat -c %s "$METADATA")"
else
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 180 --max-filesize 25000000 \
    --output "$METADATA.part" \
    "$BASE_URL/getSeries?Collection=$COLLECTION&Modality=MG"
  mv "$METADATA.part" "$METADATA"
fi

export METADATA SERIES_UID STUDY_UID
python3 - <<'PY'
import json
import os
from pathlib import Path


def field(row, *names):
    lower = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lower:
            return str(lower[name.lower()]).strip()
    return ""


rows = json.loads(Path(os.environ["METADATA"]).read_text(encoding="utf-8"))
matches = [row for row in rows if field(row, "SeriesInstanceUID") == os.environ["SERIES_UID"]]
if len(matches) != 1:
    raise SystemExit("pinned CMMD series missing or duplicated")
row = matches[0]
license_text = f"{field(row, 'LicenseName', 'License')} {field(row, 'LicenseURI', 'LicenseURL')}".lower()
expected = {
    "Collection": "CMMD",
    "Modality": "MG",
    "StudyInstanceUID": os.environ["STUDY_UID"],
    "ImageCount": "2",
    "FileSize": "17567732",
}
for name, value in expected.items():
    if field(row, name) != value:
        raise SystemExit(f"pinned CMMD metadata changed: {name}")
if not ("cc by 4.0" in license_text or "creativecommons.org/licenses/by/4.0" in license_text):
    raise SystemExit("pinned CMMD series no longer declares CC BY 4.0")
print("metadata_validation=ok images=2 dicom_source_bytes=17567732 license=CC-BY-4.0")
PY

ARCHIVE="$DOWNLOAD_DIR/cmmd_mammography_u16.zip"
DISCOVERY_ARCHIVE="$DISCOVERY_DIR/probe_${SERIES_UID}.zip"
if [[ -s "$ARCHIVE" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "archive_cache_hit bytes=$(stat -c %s "$ARCHIVE")"
elif [[ -s "$DISCOVERY_ARCHIVE" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  cp --reflink=auto "$DISCOVERY_ARCHIVE" "$ARCHIVE"
  echo "archive_reused_from_discovery bytes=$(stat -c %s "$ARCHIVE")"
else
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 900 --max-filesize "$MAX_ARCHIVE_BYTES" \
    --output "$ARCHIVE.part" "$BASE_URL/getImage?SeriesInstanceUID=$SERIES_UID"
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

export ARCHIVE DOWNLOAD_DIR MAX_ARCHIVE_BYTES
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import zipfile


archive = Path(os.environ["ARCHIVE"])
expected = {
    "LICENSE": (2784, "e586c7380104cd254f08d7758705ba9494db2d8d0db33b27ab4d88418f965865"),
    "00000001.dcm": (8783862, "ab9c82e3fc5c0c1149943b0d08126021364370148631f03e429dcf5bdda5f602"),
    "00000002.dcm": (8783870, "6c6ca46caf550654755e5fb20f88683d1363ecb87e26e89e8079e295ef6e07b2"),
}
if not zipfile.is_zipfile(archive) or not 0 < archive.stat().st_size <= int(os.environ["MAX_ARCHIVE_BYTES"]):
    raise SystemExit("CMMD response is not a bounded ZIP archive")
records = []
with zipfile.ZipFile(archive) as zf:
    members = [member for member in zf.infolist() if not member.is_dir()]
    if {member.filename for member in members} != set(expected):
        raise SystemExit("CMMD archive member inventory changed")
    for member in sorted(members, key=lambda item: item.filename):
        if member.flag_bits & 0x1:
            raise SystemExit("encrypted CMMD archive member")
        data = zf.read(member)
        digest = hashlib.sha256(data).hexdigest()
        if (len(data), digest) != expected[member.filename]:
            raise SystemExit(f"pinned CMMD member identity changed: {member.filename}")
        if member.filename.endswith(".dcm") and data[128:132] != b"DICM":
            raise SystemExit("CMMD DICOM preamble missing")
        if member.filename == "LICENSE" and not (
            b"CC BY 4.0" in data or b"creativecommons.org/licenses/by/4.0" in data
        ):
            raise SystemExit("embedded CMMD CC BY 4.0 license missing")
        records.append({
            "bytes": len(data),
            "filename": member.filename,
            "sha256": digest,
        })
payload = {
    "archive_bytes": archive.stat().st_size,
    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "candidate_id": "tcia_cmmd_mammography_u16",
    "dicom_source_bytes": sum(record["bytes"] for record in records if record["filename"].endswith(".dcm")),
    "records": records,
    "series_uid": os.environ["SERIES_UID"],
}
(Path(os.environ["DOWNLOAD_DIR"]) / "download_inventory.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"archive_validation=ok archive_bytes={payload['archive_bytes']} "
    f"dicom_source_bytes={payload['dicom_source_bytes']}"
)
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
