#!/usr/bin/env bash
# Range-only inventory of members in the oversized LoDoPaB validation ZIP.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lodopab_ct_sinograms_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
CANDIDATES="$OUT_DIR/candidates.tsv"
TAIL_BYTES="${LODOPAB_ZIP_TAIL_BYTES:-4194304}"
UA="openzl-public-datasets-lodopab-zip-discovery/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover_zip.$RUN_TS.log" "$LOG_DIR/discover_zip.latest.log") 2>&1
echo "[$(date -Is)] range discovery start candidate=$CANDIDATE_ID"

if [ ! -s "$CANDIDATES" ]; then
  echo "FATAL: missing $CANDIDATES; run discover.sh first" >&2
  exit 1
fi

python3 - "$CANDIDATES" "$OUT_DIR/selected_archive.json" <<'PY'
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


source, destination = map(Path, sys.argv[1:])
with source.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
matches = [row for row in rows if row.get("split") == "validation"]
if len(matches) != 1:
    raise SystemExit(f"expected one validation observation archive, found {len(matches)}")
row = matches[0]
size = int(row["size_bytes"])
if size <= 0 or not row.get("url") or not row.get("checksum"):
    raise SystemExit(f"incomplete validation archive metadata: {row}")
destination.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"selected key={row['key']} bytes={size} checksum={row['checksum']}")
PY

archive_url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$OUT_DIR/selected_archive.json")"
archive_size="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["size_bytes"])' "$OUT_DIR/selected_archive.json")"
if ! [[ "$TAIL_BYTES" =~ ^[0-9]+$ ]] || [ "$TAIL_BYTES" -lt 65557 ]; then
  echo "FATAL: LODOPAB_ZIP_TAIL_BYTES must be an integer of at least 65557" >&2
  exit 1
fi
if [ "$TAIL_BYTES" -gt "$archive_size" ]; then
  TAIL_BYTES="$archive_size"
fi
range_start=$((archive_size - TAIL_BYTES))
range_end=$((archive_size - 1))

rm -f "$OUT_DIR/validation_zip_tail.bin.part" "$OUT_DIR/validation_zip_tail.headers.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 180 --max-filesize "$((TAIL_BYTES + 1024))" \
  --range "$range_start-$range_end" --user-agent "$UA" \
  --dump-header "$OUT_DIR/validation_zip_tail.headers.part" \
  --output "$OUT_DIR/validation_zip_tail.bin.part" "$archive_url"
mv "$OUT_DIR/validation_zip_tail.headers.part" "$OUT_DIR/validation_zip_tail.headers"
mv "$OUT_DIR/validation_zip_tail.bin.part" "$OUT_DIR/validation_zip_tail.bin"

python3 - "$OUT_DIR/selected_archive.json" "$OUT_DIR/validation_zip_tail.headers" \
  "$OUT_DIR/validation_zip_tail.bin" "$range_start" "$OUT_DIR/zip_members.tsv" \
  "$OUT_DIR/zip_summary.json" <<'PY'
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import struct
import sys


selection_path = Path(sys.argv[1])
headers_path = Path(sys.argv[2])
tail_path = Path(sys.argv[3])
tail_start = int(sys.argv[4])
members_path = Path(sys.argv[5])
summary_path = Path(sys.argv[6])
selection = json.loads(selection_path.read_text(encoding="utf-8"))
archive_size = int(selection["size_bytes"])
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
    raise SystemExit(
        f"Zenodo object did not honor the bounded byte range: status={status} content_range={range_match}"
    )
response_start, response_end, response_total = map(int, range_match.groups())
if response_start != tail_start or response_end != archive_size - 1 or response_total != archive_size:
    raise SystemExit(
        "unexpected Content-Range: "
        f"got={response_start}-{response_end}/{response_total} "
        f"expected={tail_start}-{archive_size - 1}/{archive_size}"
    )
tail = tail_path.read_bytes()
if len(tail) != archive_size - tail_start:
    raise SystemExit(f"range byte count mismatch: expected={archive_size-tail_start} got={len(tail)}")

eocd_offset = tail.rfind(b"PK\x05\x06")
if eocd_offset < 0 or eocd_offset + 22 > len(tail):
    raise SystemExit("ZIP end-of-central-directory record not found in requested tail")
(
    signature,
    disk_number,
    central_disk,
    disk_entries,
    total_entries,
    central_size,
    central_offset,
    comment_length,
) = struct.unpack_from("<4s4H2IH", tail, eocd_offset)
if signature != b"PK\x05\x06":
    raise SystemExit("invalid ZIP EOCD signature")
if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
    raise SystemExit("split/multidisk ZIP archives are unsupported")
if 0xFFFF in (disk_entries, total_entries) or 0xFFFFFFFF in (central_size, central_offset):
    raise SystemExit("validation archive unexpectedly requires ZIP64 central-directory parsing")
if eocd_offset + 22 + comment_length != len(tail):
    raise SystemExit("ZIP EOCD/comment does not end at the archive boundary")
if central_offset + central_size != tail_start + eocd_offset:
    raise SystemExit("ZIP central directory is not contiguous with the EOCD")
central_relative = central_offset - tail_start
if central_relative < 0 or central_relative + central_size > len(tail):
    required_tail = archive_size - central_offset
    raise SystemExit(
        f"central directory is not fully present; rerun with LODOPAB_ZIP_TAIL_BYTES={required_tail}"
    )

members: list[dict[str, object]] = []
cursor = central_relative
central_end = central_relative + central_size
while cursor < central_end:
    if cursor + 46 > len(tail) or tail[cursor : cursor + 4] != b"PK\x01\x02":
        raise SystemExit(f"invalid central-directory member at archive offset {tail_start + cursor}")
    fields = struct.unpack_from("<4s6H3I5H2I", tail, cursor)
    flags = fields[3]
    method = fields[4]
    crc32 = fields[7]
    compressed_size = fields[8]
    uncompressed_size = fields[9]
    name_length = fields[10]
    extra_length = fields[11]
    comment_length = fields[12]
    disk_start = fields[13]
    local_header_offset = fields[16]
    variable_start = cursor + 46
    variable_end = variable_start + name_length + extra_length + comment_length
    if variable_end > central_end:
        raise SystemExit("central-directory variable fields exceed declared directory size")
    name_bytes = tail[variable_start : variable_start + name_length]
    encoding = "utf-8" if flags & 0x800 else "cp437"
    name = name_bytes.decode(encoding, errors="strict")
    if disk_start != 0:
        raise SystemExit(f"member {name!r} starts on an unsupported split disk")
    if 0xFFFFFFFF in (compressed_size, uncompressed_size, local_header_offset):
        raise SystemExit(f"member {name!r} unexpectedly requires ZIP64 fields")
    members.append(
        {
            "name": name,
            "compression_method": method,
            "flags": flags,
            "crc32_hex": f"{crc32:08x}",
            "compressed_size": compressed_size,
            "uncompressed_size": uncompressed_size,
            "local_header_offset": local_header_offset,
        }
    )
    cursor = variable_end
if cursor != central_end or len(members) != total_entries:
    raise SystemExit(
        f"central-directory count mismatch: parsed={len(members)} declared={total_entries}"
    )

with members_path.open("w", encoding="utf-8", newline="") as destination:
    writer = csv.DictWriter(
        destination,
        fieldnames=(
            "name",
            "compression_method",
            "flags",
            "crc32_hex",
            "compressed_size",
            "uncompressed_size",
            "local_header_offset",
        ),
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(members)

hdf5_members = [row for row in members if str(row["name"]).lower().endswith((".h5", ".hdf5"))]
bounded_hdf5 = [
    row
    for row in hdf5_members
    if 10_000_000 <= int(row["compressed_size"]) <= 750_000_000
    and 10_000_000 <= int(row["uncompressed_size"]) <= 1_000_000_000
    and int(row["compression_method"]) in {0, 8}
]
summary = {
    "candidate_id": "zenodo_lodopab_ct_sinograms_f32",
    "range_request": {
        "status": status,
        "start": response_start,
        "end": response_end,
        "total": response_total,
        "bytes_downloaded": len(tail),
    },
    "archive": selection,
    "zip_entries": len(members),
    "zip_central_directory_bytes": central_size,
    "hdf5_members": len(hdf5_members),
    "bounded_hdf5_members": len(bounded_hdf5),
    "preferred_members": bounded_hdf5[:12],
    "next_step": (
        "range-download one exact HDF5 member and validate native dtype/shape"
        if bounded_hdf5
        else "no independently fetchable bounded HDF5 member found"
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
if not hdf5_members:
    raise SystemExit("validation ZIP contains no HDF5 members")
if not bounded_hdf5:
    raise SystemExit("validation ZIP contains no bounded HDF5 member suitable for a probe")
PY

echo "[$(date -Is)] range discovery done candidate=$CANDIDATE_ID"
