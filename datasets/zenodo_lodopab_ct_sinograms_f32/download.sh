#!/usr/bin/env bash
# Download one pinned LoDoPaB validation HDF5 member by exact ZIP byte range.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_lodopab_ct_sinograms_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
RECORD_ID=3384092
API_URL="https://zenodo.org/api/records/$RECORD_ID"
ARCHIVE_URL="https://zenodo.org/api/records/3384092/files/observation_validation.zip/content"
ARCHIVE_NAME="observation_validation.zip"
ARCHIVE_BYTES=2944573582
ARCHIVE_MD5="3cff406e09c59774912655eb7a72cfcf"
MEMBER_NAME="observation_validation_000.hdf5"
MEMBER_RANGE_START=0
MEMBER_RANGE_END=106629167
MEMBER_RANGE_BYTES=106629168
MEMBER_COMPRESSED_BYTES=106629107
MEMBER_UNCOMPRESSED_BYTES=272735288
MEMBER_CRC32="206b14c4"
MEMBER_RANGE_SHA256="fe5d44a630728d768552e1be3624fbaf1cfc27c6a73ccbfd860e89398f2a3ae4"
MEMBER_SHA256="04f0399b1d1d4ff8d012d54312b1b67f84a412d94bf935865963172e996fb977"
UA="openzl-public-datasets-lodopab-sinograms/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

metadata="$DOWNLOAD_DIR/record.json"
if [ ! -s "$metadata" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$metadata.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 180 --max-filesize 20000000 \
    --user-agent "$UA" --header "Accept: application/json" \
    --output "$metadata.part" "$API_URL"
  mv "$metadata.part" "$metadata"
fi

python3 - "$metadata" "$RECORD_ID" "$ARCHIVE_NAME" "$ARCHIVE_BYTES" "$ARCHIVE_MD5" <<'PY'
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys


path = Path(sys.argv[1])
record_id = int(sys.argv[2])
archive_name = sys.argv[3]
archive_bytes = int(sys.argv[4])
archive_md5 = sys.argv[5]
record = json.loads(path.read_text(encoding="utf-8"))
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"unexpected Zenodo record id: {record.get('id')!r}")
metadata = record.get("metadata")
if not isinstance(metadata, dict):
    raise SystemExit("Zenodo response has no metadata object")
identity = html.unescape(
    re.sub(r"<[^>]+>", " ", f"{metadata.get('title', '')} {metadata.get('description', '')}")
)
if "lodopabct" not in re.sub(r"[^a-z0-9]+", "", identity.lower()):
    raise SystemExit(f"record does not identify LoDoPaB-CT: {metadata.get('title')!r}")
license_value = metadata.get("license")
license_id = (
    str(license_value.get("id") or license_value.get("title") or "")
    if isinstance(license_value, dict)
    else str(license_value or "")
)
if license_id.lower().replace("_", "-") != "cc-by-4.0":
    raise SystemExit(f"record license changed: {license_id!r}")
files = record.get("files")
if not isinstance(files, list):
    raise SystemExit("record has no files list")
matches = [item for item in files if isinstance(item, dict) and item.get("key") == archive_name]
if len(matches) != 1:
    raise SystemExit(f"expected one {archive_name!r} file, found {len(matches)}")
item = matches[0]
if int(item.get("size") or 0) != archive_bytes:
    raise SystemExit(f"outer archive size changed: {item.get('size')!r}")
if str(item.get("checksum") or "").lower() != f"md5:{archive_md5}":
    raise SystemExit(f"outer archive checksum changed: {item.get('checksum')!r}")
print(
    f"metadata_validation=ok record={record_id} license=CC-BY-4.0 "
    f"archive_bytes={archive_bytes} archive_md5={archive_md5}"
)
PY

range_file="$DOWNLOAD_DIR/$MEMBER_NAME.zip-range"
headers_file="$DOWNLOAD_DIR/$MEMBER_NAME.range.headers"
output_file="$DOWNLOAD_DIR/$MEMBER_NAME"

validate_hdf5() {
  python3 - "$1" "$MEMBER_UNCOMPRESSED_BYTES" "$MEMBER_SHA256" <<'PY'
from pathlib import Path
import hashlib
import sys


path = Path(sys.argv[1])
expected_bytes = int(sys.argv[2])
expected_sha256 = sys.argv[3]
if not path.is_file() or path.stat().st_size != expected_bytes:
    raise SystemExit(f"missing or wrong-sized HDF5 member: {path}")
digest = hashlib.sha256()
with path.open("rb") as handle:
    signature = handle.read(8)
    if signature != b"\x89HDF\r\n\x1a\n":
        raise SystemExit("extracted member lacks the HDF5 signature")
    digest.update(signature)
    while block := handle.read(8 * 1024 * 1024):
        digest.update(block)
actual_sha256 = digest.hexdigest()
if actual_sha256 != expected_sha256:
    raise SystemExit(f"HDF5 SHA-256 mismatch: expected={expected_sha256} actual={actual_sha256}")
print(f"hdf5_validation=ok bytes={expected_bytes} sha256={actual_sha256}")
PY
}

if [ -s "$output_file" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  validate_hdf5 "$output_file"
  echo "cache_hit member=$MEMBER_NAME path=$output_file"
else
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$range_file" "$range_file.part" "$headers_file" "$headers_file.part" \
      "$output_file" "$output_file.part"
  fi
  if [ -s "$range_file" ]; then
    actual_range_bytes="$(wc -c < "$range_file" | tr -d ' ')"
    if [ "$actual_range_bytes" != "$MEMBER_RANGE_BYTES" ] || [ ! -s "$headers_file" ]; then
      rm -f "$range_file" "$headers_file"
    fi
  fi
  if [ ! -s "$range_file" ]; then
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 2 --retry-all-errors \
      --max-time 600 --max-filesize "$((MEMBER_RANGE_BYTES + 1024))" \
      --range "$MEMBER_RANGE_START-$MEMBER_RANGE_END" --user-agent "$UA" \
      --dump-header "$headers_file.part" --output "$range_file.part" "$ARCHIVE_URL"
    mv "$headers_file.part" "$headers_file"
    mv "$range_file.part" "$range_file"
  fi
  printf '%s  %s\n' "$MEMBER_RANGE_SHA256" "$range_file" | sha256sum --check --status || {
    echo "FATAL: member ZIP range SHA-256 mismatch" >&2
    exit 1
  }

  python3 - "$headers_file" "$range_file" "$output_file.part" \
    "$ARCHIVE_BYTES" "$MEMBER_RANGE_START" "$MEMBER_RANGE_END" "$MEMBER_NAME" \
    "$MEMBER_COMPRESSED_BYTES" "$MEMBER_UNCOMPRESSED_BYTES" "$MEMBER_CRC32" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import struct
import sys
import zlib


headers_path = Path(sys.argv[1])
range_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
archive_bytes = int(sys.argv[4])
range_start = int(sys.argv[5])
range_end = int(sys.argv[6])
member_name = sys.argv[7]
expected_compressed = int(sys.argv[8])
expected_uncompressed = int(sys.argv[9])
expected_crc32 = int(sys.argv[10], 16)
headers = headers_path.read_text(encoding="iso-8859-1")
responses = re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE)
final = next((part for part in reversed(responses) if part.strip()), "")
status_match = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
content_range = re.search(
    r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$",
    final,
    flags=re.IGNORECASE | re.MULTILINE,
)
status = int(status_match.group(1)) if status_match else 0
if status != 206 or not content_range:
    raise SystemExit(f"server did not honor exact member range: status={status}")
if tuple(map(int, content_range.groups())) != (range_start, range_end, archive_bytes):
    raise SystemExit(f"unexpected Content-Range: {content_range.groups()}")
payload = range_path.read_bytes()
if len(payload) != range_end - range_start + 1 or payload[:4] != b"PK\x03\x04":
    raise SystemExit("invalid ZIP member range payload")
fields = struct.unpack_from("<4s5H3I2H", payload, 0)
flags = fields[3]
method = fields[4]
crc32 = fields[7]
compressed_size = fields[8]
uncompressed_size = fields[9]
name_length = fields[10]
extra_length = fields[11]
name = payload[30 : 30 + name_length].decode("utf-8" if flags & 0x800 else "cp437")
data_offset = 30 + name_length + extra_length
if (
    name != member_name
    or flags != 0
    or method != 8
    or crc32 != expected_crc32
    or compressed_size != expected_compressed
    or uncompressed_size != expected_uncompressed
    or data_offset + compressed_size != len(payload)
):
    raise SystemExit("ZIP local-header/member metadata mismatch")
decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
actual_crc32 = 0
written = 0
with output_path.open("wb") as destination:
    view = memoryview(payload)[data_offset:]
    for offset in range(0, len(view), 1024 * 1024):
        decoded = decompressor.decompress(view[offset : offset + 1024 * 1024])
        destination.write(decoded)
        actual_crc32 = zlib.crc32(decoded, actual_crc32)
        written += len(decoded)
    decoded = decompressor.flush()
    destination.write(decoded)
    actual_crc32 = zlib.crc32(decoded, actual_crc32)
    written += len(decoded)
if not decompressor.eof or decompressor.unused_data:
    raise SystemExit("DEFLATE stream did not end at the exact member boundary")
if written != expected_uncompressed or actual_crc32 & 0xFFFFFFFF != expected_crc32:
    raise SystemExit(
        f"extracted member mismatch: bytes={written} crc32={actual_crc32 & 0xFFFFFFFF:08x}"
    )
print(f"zip_member_validation=ok bytes={written} crc32={actual_crc32 & 0xFFFFFFFF:08x}")
PY
  mv "$output_file.part" "$output_file"
  validate_hdf5 "$output_file"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
