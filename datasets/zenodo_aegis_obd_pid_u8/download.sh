#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_aegis_obd_pid_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/Automotive-ResearchDataSet-VIF-AEGIS.zip"
METADATA="$DOWNLOAD_DIR/zenodo_record_820576.json"
ARCHIVE_URL="https://zenodo.org/api/records/820576/files/Automotive-ResearchDataSet-VIF-AEGIS.zip/content"
METADATA_URL="https://zenodo.org/api/records/820576"
ARCHIVE_SIZE=37204969
ARCHIVE_MD5="8c840ca85a0af6cb5784040cb27d465a"

mkdir -p "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_archive() {
  [[ -f "$ARCHIVE" ]] || return 1
  [[ "$(stat -c %s "$ARCHIVE")" == "$ARCHIVE_SIZE" ]] || return 1
  [[ "$(md5sum "$ARCHIVE" | awk '{print $1}')" == "$ARCHIVE_MD5" ]]
}

if valid_archive && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "reuse existing archive bytes=$ARCHIVE_SIZE md5=$ARCHIVE_MD5"
else
  rm -f "$ARCHIVE.part"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 5 --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-time 1800 \
    --max-filesize 100000000 --user-agent "openzl-public-datasets/1.0" \
    --output "$ARCHIVE.part" "$ARCHIVE_URL"
  if [[ "$(stat -c %s "$ARCHIVE.part")" != "$ARCHIVE_SIZE" ]] || \
     [[ "$(md5sum "$ARCHIVE.part" | awk '{print $1}')" != "$ARCHIVE_MD5" ]]; then
    echo "FATAL: downloaded archive identity mismatch" >&2
    exit 1
  fi
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

rm -f "$METADATA.part"
curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-all-errors --retry-delay 5 --connect-timeout 30 \
  --max-time 240 --max-filesize 1000000 --user-agent "openzl-public-datasets/1.0" \
  --output "$METADATA.part" "$METADATA_URL"
mv "$METADATA.part" "$METADATA"

export ARCHIVE METADATA EXTRACT_DIR DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import zipfile


archive = Path(os.environ["ARCHIVE"])
metadata_path = Path(os.environ["METADATA"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected_members = {
    "accelerations.csv": (77_500_354, 0x3BEF5795),
    "beaglebones.csv": (205, 0x24688C3C),
    "gyroscopes.csv": (78_268_526, 0xE109E5CF),
    "obdData.csv": (63_583_909, 0xBE67319C),
    "positions.csv": (10_281_753, 0x8171BF01),
    "trips.csv": (1_109, 0x89842629),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
if str(metadata.get("id")) != "820576":
    raise SystemExit("wrong Zenodo record ID")
record_metadata = metadata.get("metadata", {})
if not isinstance(record_metadata, dict) or record_metadata.get("doi") != "10.5281/zenodo.820576":
    raise SystemExit("wrong Zenodo DOI")
license_obj = record_metadata.get("license", {})
if not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0":
    raise SystemExit(f"record no longer declares CC BY 4.0: {license_obj}")
files = metadata.get("files", [])
matches = [item for item in files if isinstance(item, dict) and item.get("key") == archive.name]
if len(matches) != 1 or int(matches[0].get("size", 0)) != 37_204_969:
    raise SystemExit("Zenodo file metadata mismatch")
if str(matches[0].get("checksum", "")).lower() != "md5:8c840ca85a0af6cb5784040cb27d465a":
    raise SystemExit("Zenodo checksum metadata mismatch")

if not zipfile.is_zipfile(archive):
    raise SystemExit("source is not a valid ZIP archive")
if extract_dir.exists():
    shutil.rmtree(extract_dir)
extract_dir.mkdir(parents=True)
with zipfile.ZipFile(archive) as zf:
    actual: dict[str, tuple[int, int]] = {}
    infos: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        member_path = PurePosixPath(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        if info.is_dir():
            continue
        actual[info.filename] = (info.file_size, info.CRC)
        infos[info.filename] = info
    if actual != expected_members:
        raise SystemExit(f"ZIP inventory drift: {actual}")
    source_info = infos["obdData.csv"]
    output = extract_dir / "obdData.csv"
    with zf.open(source_info) as source, output.open("wb") as destination:
        shutil.copyfileobj(source, destination, 1 << 20)

if output.stat().st_size != expected_members["obdData.csv"][0]:
    raise SystemExit("extracted OBD table size mismatch")
with output.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.reader(handle)
    header = next(reader, None)
if header != ["obdData_id", "trip_id", "obdPid", "data", "timestamp"]:
    raise SystemExit(f"unexpected OBD table header: {header}")
inventory = {
    "dataset_id": "zenodo_aegis_obd_pid_u8",
    "record_id": 820576,
    "doi": "10.5281/zenodo.820576",
    "license": "CC-BY-4.0",
    "archive_size_bytes": archive.stat().st_size,
    "archive_md5": hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest(),
    "archive_sha256": sha256(archive),
    "metadata_size_bytes": metadata_path.stat().st_size,
    "metadata_sha256": sha256(metadata_path),
    "obd_csv_size_bytes": output.stat().st_size,
    "obd_csv_sha256": sha256(output),
    "obd_csv_header": header,
}
(download_dir / "inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(inventory, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
