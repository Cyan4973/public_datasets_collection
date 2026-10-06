#!/usr/bin/env bash
# Download the pinned HC18 fetal-head ultrasound deposit (Zenodo record 1327317):
# the two image ZIP archives (whole, resumable) and the two pixel-size CSVs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_hc18_fetal_head_ultrasound_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=1327317
CONCEPT_RECORD_ID=1322000
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_URL_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
UA="openzl-public-datasets-hc18/1.0"

# name|bytes|md5|kind|sha256 (MD5 from Zenodo; SHA-256 recorded from the
# verified 2026-10-06 download)
FILES=(
  "training_set.zip|132926838|00eb8198b9a505b2b3a6dfc740382497|zip|fd20d7909df892cfbdc0850de18072dbdad4dc3bc0a57202d4cc818d4715de36"
  "test_set.zip|43518463|8402af5d137ef40a2888c1011ef3fe7e|zip|6356d1171e5805dabb83af72c13eb2b32fc3d6c0c2015c58eb9ee083521e9bdd"
  "training_set_pixel_size_and_HC.csv|33688|c0761518fece2bd2d2ad4218f2cd9777|csv|1c08fa81c374c5f9509f3aa6a6568e4dc6cc5434ff82d0df731db7e4f25816b3"
  "test_set_pixel_size.csv|9096|8476dc198cc6542f26c57e87faeee033|csv|215970c7334fcb3794c88d39cbe33fe334f4323cbce8cddeeda04aa5c0faf227"
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID record=$RECORD_ID"

# 1. Record metadata: identity, licence, version and the pinned file list.
metadata="$DOWNLOAD_DIR/record_$RECORD_ID.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 - "$metadata" "$RECORD_ID" "$CONCEPT_RECORD_ID" "${FILES[@]}" <<'PY'
import json
import sys

path, record_id, concept_id = sys.argv[1], int(sys.argv[2]), str(sys.argv[3])
pinned = {}
for spec in sys.argv[4:]:
    name, size, md5, _kind, _sha256 = spec.split("|")
    pinned[name] = (int(size), md5)
record = json.load(open(path, encoding="utf-8"))
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"FATAL: unexpected Zenodo record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = str(meta.get("title", ""))
if title != "Automated measurement of fetal head circumference using 2D ultrasound images":
    raise SystemExit(f"FATAL: record title changed: {title!r}")
creators = [c.get("name", "") for c in meta.get("creators", [])]
if not creators or "van den Heuvel" not in creators[0]:
    raise SystemExit(f"FATAL: unexpected creators {creators!r}")
license_value = meta.get("license")
license_id = str(license_value.get("id", "") if isinstance(license_value, dict) else license_value or "")
if license_id.lower() != "cc-by-4.0":
    raise SystemExit(f"FATAL: record licence is {license_id!r}, expected cc-by-4.0")
if meta.get("access_right") != "open":
    raise SystemExit(f"FATAL: access_right is {meta.get('access_right')!r}")
if str(record.get("conceptrecid", "")) != concept_id:
    raise SystemExit(f"FATAL: concept record is {record.get('conceptrecid')!r}")
files = {f.get("key"): f for f in record.get("files", []) if isinstance(f, dict)}
if set(files) != set(pinned):
    raise SystemExit(f"FATAL: record file list changed: {sorted(files)}")
for name, (size, md5) in pinned.items():
    entry = files[name]
    if int(entry.get("size") or -1) != size or str(entry.get("checksum", "")).lower() != f"md5:{md5}":
        raise SystemExit(f"FATAL: {name} changed: size={entry.get('size')} checksum={entry.get('checksum')}")
print(f"metadata_validation=ok record={record_id} concept={concept_id} license=cc-by-4.0 files={len(pinned)}")
PY

md5_of() { md5sum "$1" | awk '{print $1}'; }
sha256_of() { sha256sum "$1" | awk '{print $1}'; }
size_of() { stat -L -c %s "$1"; }

validate_payload() {
  # Semantic checks beyond size/MD5: ZIP end-of-central-directory geometry and
  # CSV header/row count.
  python3 - "$1" "$2" <<'PY'
import struct
import sys

path, name = sys.argv[1], sys.argv[2]
zips = {
    "training_set.zip": (1999, 221260, 132705556),
    "test_set.zip": (336, 33926, 43484515),
}
csvs = {
    "training_set_pixel_size_and_HC.csv": ("filename,pixel size(mm),head circumference (mm)", 999),
    "test_set_pixel_size.csv": ("filename,pixel size(mm)", 335),
}
data = open(path, "rb")
if name in zips:
    head = data.read(4)
    data.seek(-22, 2)
    eocd = data.read(22)
    if head != b"PK\x03\x04" or eocd[:4] != b"PK\x05\x06":
        raise SystemExit(f"FATAL: {name} is not a single-segment ZIP without comment")
    entries, cd_size, cd_offset = struct.unpack("<10xHII2x", eocd)
    if (entries, cd_size, cd_offset) != zips[name]:
        raise SystemExit(f"FATAL: {name} central directory {entries}/{cd_size}/{cd_offset}")
    print(f"zip_validation=ok file={name} entries={entries}")
else:
    lines = data.read().decode("ascii").splitlines()
    header, rows = csvs[name]
    columns = header.count(",") + 1
    well_formed = all(
        len(line.split(",")) == columns and line.split(",")[0].endswith("HC.png") for line in lines[1:]
    )
    if lines[0] != header or len(lines) - 1 != rows or not well_formed:
        raise SystemExit(f"FATAL: {name} header/rows unexpected ({len(lines) - 1} rows)")
    print(f"csv_validation=ok file={name} rows={rows}")
PY
}

for spec in "${FILES[@]}"; do
  IFS='|' read -r name bytes md5 kind sha256 <<<"$spec"
  dest="$DOWNLOAD_DIR/$name"
  part="$dest.part"
  url="$FILE_URL_BASE/$name/content"
  if [ -f "$dest" ] && [ "$(size_of "$dest")" = "$bytes" ] && [ "$(md5_of "$dest")" = "$md5" ] \
    && [ "$(sha256_of "$dest")" = "$sha256" ]; then
    echo "cache_hit file=$name bytes=$bytes md5=$md5 sha256=$sha256"
    validate_payload "$dest" "$name"
    continue
  fi
  rm -f "$dest"
  if [ -f "$part" ] && [ "$(size_of "$part")" -gt "$bytes" ]; then
    echo "discarding oversized partial $part"
    rm -f "$part"
  fi
  if [ -f "$part" ] && [ "$(size_of "$part")" = "$bytes" ]; then
    echo "partial file=$name already complete; checking it"
  else
    echo "fetch file=$name bytes=$bytes resume_from=$( [ -f "$part" ] && size_of "$part" || echo 0)"
    curl --fail --location --silent --show-error \
      --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$url"
  fi
  actual_bytes="$(size_of "$part")"
  actual_md5="$(md5_of "$part")"
  actual_sha256="$(sha256_of "$part")"
  if [ "$actual_bytes" != "$bytes" ] || [ "$actual_md5" != "$md5" ] || [ "$actual_sha256" != "$sha256" ]; then
    echo "FATAL: $name bytes=$actual_bytes md5=$actual_md5 sha256=$actual_sha256 expected bytes=$bytes md5=$md5 sha256=$sha256; partial removed, re-run to fetch again" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$dest"
  echo "downloaded file=$name bytes=$bytes md5=$md5 sha256=$sha256"
  validate_payload "$dest" "$name"
done

echo "[$(date -Is)] download done dataset=$DATASET_ID"
