#!/usr/bin/env bash
# Fetch and extract one exact LoDoPaB validation HDF5 member by HTTP range.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lodopab_ct_sinograms_f32"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MEMBER_NAME="${LODOPAB_PROBE_MEMBER:-observation_validation_000.hdf5}"
UA="openzl-public-datasets-lodopab-member-probe/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download_probe.$RUN_TS.log" "$LOG_DIR/download_probe.latest.log") 2>&1
echo "[$(date -Is)] member download start candidate=$CANDIDATE_ID member=$MEMBER_NAME"

if [ ! -s "$DISCOVERY_DIR/zip_members.tsv" ] || [ ! -s "$DISCOVERY_DIR/zip_summary.json" ]; then
  echo "FATAL: missing ZIP discovery outputs; run discover_zip.sh first" >&2
  exit 1
fi

python3 - "$DISCOVERY_DIR/zip_members.tsv" "$DISCOVERY_DIR/zip_summary.json" \
  "$MEMBER_NAME" "$DISCOVERY_DIR/selected_member.json" <<'PY'
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


members_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
member_name = sys.argv[3]
output_path = Path(sys.argv[4])
with members_path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
matches = [row for row in rows if row.get("name") == member_name]
if len(matches) != 1:
    raise SystemExit(f"expected one member named {member_name!r}, found {len(matches)}")
row = matches[0]
index = rows.index(row)
if index + 1 >= len(rows):
    raise SystemExit("probe member is the last ZIP member; no next local-header boundary is available")
next_row = rows[index + 1]
local_offset = int(row["local_header_offset"])
next_offset = int(next_row["local_header_offset"])
compressed_size = int(row["compressed_size"])
if next_offset <= local_offset or next_offset - local_offset <= compressed_size:
    raise SystemExit("invalid member/local-header boundaries")
summary = json.loads(summary_path.read_text(encoding="utf-8"))
archive = summary.get("archive")
if not isinstance(archive, dict) or not archive.get("url"):
    raise SystemExit("ZIP summary has no archive URL")
selection = {
    **row,
    "archive_url": str(archive["url"]),
    "archive_size": int(archive["size_bytes"]),
    "range_start": local_offset,
    "range_end": next_offset - 1,
    "range_bytes": next_offset - local_offset,
}
output_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(selection, indent=2, sort_keys=True))
PY

archive_url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["archive_url"])' "$DISCOVERY_DIR/selected_member.json")"
range_start="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["range_start"])' "$DISCOVERY_DIR/selected_member.json")"
range_end="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["range_end"])' "$DISCOVERY_DIR/selected_member.json")"
range_bytes="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["range_bytes"])' "$DISCOVERY_DIR/selected_member.json")"
range_file="$DOWNLOAD_DIR/$MEMBER_NAME.zip-range"
headers_file="$DOWNLOAD_DIR/$MEMBER_NAME.range.headers"
output_file="$DOWNLOAD_DIR/$MEMBER_NAME"

if [ -s "$output_file" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "cache_hit member=$MEMBER_NAME path=$output_file"
else
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$range_file" "$range_file.part" "$headers_file" "$headers_file.part" \
      "$output_file" "$output_file.part"
  fi
  if [ -s "$range_file" ]; then
    cached_range_bytes="$(wc -c < "$range_file" | tr -d ' ')"
    if [ "$cached_range_bytes" != "$range_bytes" ] || [ ! -s "$headers_file" ]; then
      echo "discarding incomplete cached range bytes=$cached_range_bytes expected=$range_bytes"
      rm -f "$range_file" "$headers_file"
    fi
  fi
  if [ ! -s "$range_file" ]; then
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 2 --retry-all-errors \
      --max-time 600 --max-filesize "$((range_bytes + 1024))" \
      --range "$range_start-$range_end" --user-agent "$UA" \
      --dump-header "$headers_file.part" --output "$range_file.part" "$archive_url"
    mv "$headers_file.part" "$headers_file"
    mv "$range_file.part" "$range_file"
  fi

  python3 - "$DISCOVERY_DIR/selected_member.json" "$headers_file" "$range_file" "$output_file.part" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib


selection_path, headers_path, range_path, output_path = map(Path, sys.argv[1:])
selection = json.loads(selection_path.read_text(encoding="utf-8"))
headers = headers_path.read_text(encoding="iso-8859-1")
responses = re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE)
final = next((part for part in reversed(responses) if part.strip()), "")
status_match = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
range_match = re.search(
    r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$",
    final,
    flags=re.IGNORECASE | re.MULTILINE,
)
status = int(status_match.group(1)) if status_match else 0
if status != 206 or not range_match:
    raise SystemExit(f"server did not honor exact member range: status={status}")
actual_start, actual_end, actual_total = map(int, range_match.groups())
expected_range = (
    int(selection["range_start"]),
    int(selection["range_end"]),
    int(selection["archive_size"]),
)
if (actual_start, actual_end, actual_total) != expected_range:
    raise SystemExit(
        f"Content-Range mismatch: expected={expected_range} "
        f"actual={(actual_start, actual_end, actual_total)}"
    )

payload = range_path.read_bytes()
if len(payload) != int(selection["range_bytes"]):
    raise SystemExit(
        f"range size mismatch: expected={selection['range_bytes']} actual={len(payload)}"
    )
if len(payload) < 30 or payload[:4] != b"PK\x03\x04":
    raise SystemExit("invalid ZIP local-file header signature")
(
    signature,
    version_needed,
    flags,
    method,
    mod_time,
    mod_date,
    crc32_expected,
    compressed_size,
    uncompressed_size,
    name_length,
    extra_length,
) = struct.unpack_from("<4s5H3I2H", payload, 0)
del signature, version_needed, mod_time, mod_date
if flags != int(selection["flags"]) or method != int(selection["compression_method"]):
    raise SystemExit("local header flags/compression method disagree with central directory")
if crc32_expected != int(str(selection["crc32_hex"]), 16):
    raise SystemExit("local header CRC32 disagrees with central directory")
if compressed_size != int(selection["compressed_size"]):
    raise SystemExit("local header compressed size disagrees with central directory")
if uncompressed_size != int(selection["uncompressed_size"]):
    raise SystemExit("local header uncompressed size disagrees with central directory")
data_offset = 30 + name_length + extra_length
name = payload[30 : 30 + name_length].decode("utf-8" if flags & 0x800 else "cp437")
if name != selection["name"]:
    raise SystemExit(f"local header member name mismatch: {name!r}")
if data_offset + compressed_size != len(payload):
    raise SystemExit(
        f"member range boundary mismatch: header={data_offset} compressed={compressed_size} "
        f"range={len(payload)}"
    )
if method != 8:
    raise SystemExit(f"expected DEFLATE method 8, got {method}")

decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
crc32_actual = 0
written = 0
sha256 = hashlib.sha256()
with output_path.open("wb") as destination:
    view = memoryview(payload)[data_offset : data_offset + compressed_size]
    for offset in range(0, len(view), 1024 * 1024):
        decoded = decompressor.decompress(view[offset : offset + 1024 * 1024])
        if decoded:
            destination.write(decoded)
            crc32_actual = zlib.crc32(decoded, crc32_actual)
            sha256.update(decoded)
            written += len(decoded)
    decoded = decompressor.flush()
    if decoded:
        destination.write(decoded)
        crc32_actual = zlib.crc32(decoded, crc32_actual)
        sha256.update(decoded)
        written += len(decoded)
if not decompressor.eof or decompressor.unused_data:
    raise SystemExit("DEFLATE stream did not terminate exactly at the member boundary")
if written != uncompressed_size:
    raise SystemExit(f"uncompressed size mismatch: expected={uncompressed_size} actual={written}")
if crc32_actual & 0xFFFFFFFF != crc32_expected:
    raise SystemExit(
        f"member CRC32 mismatch: expected={crc32_expected:08x} actual={crc32_actual & 0xFFFFFFFF:08x}"
    )
print(
    f"member_validation=ok name={name} compressed_bytes={compressed_size} "
    f"uncompressed_bytes={written} crc32={crc32_actual & 0xFFFFFFFF:08x} "
    f"sha256={sha256.hexdigest()}"
)
PY
  mv "$output_file.part" "$output_file"
fi

python3 - "$output_file" <<'PY'
from pathlib import Path
import hashlib
import sys


path = Path(sys.argv[1])
with path.open("rb") as handle:
    signature = handle.read(8)
if signature != b"\x89HDF\r\n\x1a\n":
    raise SystemExit("extracted member does not have an HDF5 signature")
sha256 = hashlib.sha256()
with path.open("rb") as handle:
    while chunk := handle.read(8 * 1024 * 1024):
        sha256.update(chunk)
print(f"hdf5_signature=ok bytes={path.stat().st_size} sha256={sha256.hexdigest()}")
PY

echo "[$(date -Is)] member download done candidate=$CANDIDATE_ID member=$MEMBER_NAME"
