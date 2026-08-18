#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_aegis_obd_pid_u8"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] preflight start candidate=$CANDIDATE_ID"

export OUT_DIR
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zlib


OUT_DIR = Path(os.environ["OUT_DIR"])
RECORD_ID = "820576"
API_URL = f"https://zenodo.org/api/records/{RECORD_ID}"
ARCHIVE_KEY = "Automotive-ResearchDataSet-VIF-AEGIS.zip"
EXPECTED_ARCHIVE_SIZE = 37_204_969
EXPECTED_ARCHIVE_MD5 = "8c840ca85a0af6cb5784040cb27d465a"
MEMBER_BASENAME = "obdData.csv"
USER_AGENT = "openzl-public-datasets-aegis-obd-u8-preflight/1.0"
MAX_COMPRESSED_PREFIX = 8 * 1024 * 1024
MAX_DECOMPRESSED_PREFIX = 32 * 1024 * 1024
MAX_CENTRAL_DIRECTORY = 4 * 1024 * 1024
MIN_SEQUENCE_VALUES = 1_024


def curl_bytes(url: str, byte_range: tuple[int, int] | None = None) -> bytes:
    command = [
        "curl", "--fail-with-body", "--silent", "--show-error", "--location",
        "--retry", "3", "--retry-delay", "2", "--max-time", "180",
        "--user-agent", USER_AGENT,
    ]
    expected = None
    if byte_range is not None:
        start, end = byte_range
        expected = end - start + 1
        command.extend(("--range", f"{start}-{end}", "--max-filesize", str(expected * 2)))
    command.append(url)
    result = subprocess.run(
        command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        response = result.stdout.decode("utf-8", errors="replace").strip()[:2000]
        suffix = f" response={response}" if response else ""
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}{suffix}")
    if expected is not None and len(result.stdout) > expected * 2:
        raise RuntimeError("server ignored bounded range request")
    return result.stdout


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def license_id(metadata: dict[str, object]) -> str:
    item = metadata.get("license", {})
    if isinstance(item, dict):
        value = str(item.get("id") or item.get("title") or "")
    else:
        value = str(item or "")
    return re.sub(r"-+", "-", value.lower().replace("_", "-").replace(" ", "-")).strip("-")


def file_url(file_obj: dict[str, object]) -> str:
    links = file_obj.get("links", {})
    if not isinstance(links, dict):
        return ""
    return str(links.get("content") or links.get("self") or "")


metadata_raw = curl_bytes(API_URL)
record = json.loads(metadata_raw)
if not isinstance(record, dict) or str(record.get("id")) != RECORD_ID:
    raise SystemExit("Zenodo returned the wrong record")
metadata = record.get("metadata", {})
if not isinstance(metadata, dict):
    raise SystemExit("Zenodo record has no metadata object")
license_value = license_id(metadata)
if license_value not in {"cc-by-4.0", "creative-commons-attribution-4.0-international"}:
    raise SystemExit(f"expected CC BY 4.0, got {license_value!r}")
files = record.get("files", [])
if not isinstance(files, list):
    raise SystemExit("Zenodo record has no file list")
matches = [item for item in files if isinstance(item, dict) and item.get("key") == ARCHIVE_KEY]
if len(matches) != 1:
    raise SystemExit(f"expected exactly one {ARCHIVE_KEY!r}, found {len(matches)}")
archive = matches[0]
archive_size = int(archive.get("size", 0) or 0)
archive_checksum = str(archive.get("checksum", ""))
if archive_size != EXPECTED_ARCHIVE_SIZE:
    raise SystemExit(f"archive size drift: {archive_size} != {EXPECTED_ARCHIVE_SIZE}")
if archive_checksum.lower() != f"md5:{EXPECTED_ARCHIVE_MD5}":
    raise SystemExit(f"archive checksum drift: {archive_checksum!r}")
archive_url = file_url(archive)
if not archive_url:
    raise SystemExit("archive has no content URL")
(OUT_DIR / "record.json").write_bytes(metadata_raw + (b"\n" if not metadata_raw.endswith(b"\n") else b""))

# Read the EOCD and central directory without acquiring the archive payload.
tail_size = min(archive_size, 65_557)
tail_start = archive_size - tail_size
tail = curl_bytes(archive_url, (tail_start, archive_size - 1))
eocd_at = tail.rfind(b"PK\x05\x06")
if eocd_at < 0 or eocd_at + 22 > len(tail):
    raise SystemExit("ZIP EOCD not found")
_, _, _, _, entry_count, directory_size, directory_offset, _ = struct.unpack_from(
    "<4s4H2LH", tail, eocd_at
)
if not (0 < directory_size <= MAX_CENTRAL_DIRECTORY):
    raise SystemExit(f"unexpected ZIP central-directory size: {directory_size}")
directory = curl_bytes(
    archive_url, (directory_offset, directory_offset + directory_size - 1)
)
members: list[dict[str, object]] = []
offset = 0
while offset + 46 <= len(directory) and len(members) < entry_count:
    if directory[offset:offset + 4] != b"PK\x01\x02":
        raise SystemExit(f"invalid ZIP central-directory entry at {offset}")
    flags = struct.unpack_from("<H", directory, offset + 8)[0]
    compression = struct.unpack_from("<H", directory, offset + 10)[0]
    crc32 = struct.unpack_from("<L", directory, offset + 16)[0]
    compressed_size = struct.unpack_from("<L", directory, offset + 20)[0]
    uncompressed_size = struct.unpack_from("<L", directory, offset + 24)[0]
    name_length, extra_length, comment_length = struct.unpack_from("<3H", directory, offset + 28)
    local_offset = struct.unpack_from("<L", directory, offset + 42)[0]
    start = offset + 46
    end = start + name_length
    name = directory[start:end].decode("utf-8", errors="strict")
    members.append({
        "name": name, "flags": flags, "compression": compression,
        "crc32": f"{crc32:08x}", "compressed_size": compressed_size,
        "uncompressed_size": uncompressed_size, "local_offset": local_offset,
    })
    offset = end + extra_length + comment_length

(OUT_DIR / "zip_members.tsv").write_text(
    "name\tcompression\tcompressed_size\tuncompressed_size\tcrc32\n" +
    "".join(
        f"{member['name']}\t{member['compression']}\t{member['compressed_size']}\t"
        f"{member['uncompressed_size']}\t{member['crc32']}\n"
        for member in members
    ),
    encoding="utf-8",
)
member_matches = [member for member in members if Path(str(member["name"])).name == MEMBER_BASENAME]
if len(member_matches) != 1:
    raise SystemExit(f"expected one {MEMBER_BASENAME!r}, found {len(member_matches)}")
member = member_matches[0]
if int(member["flags"]) & 1:
    raise SystemExit("obdData.csv is encrypted")
if int(member["compression"]) not in (0, 8):
    raise SystemExit(f"unsupported ZIP compression method {member['compression']}")

local_offset = int(member["local_offset"])
local_header = curl_bytes(archive_url, (local_offset, local_offset + 29))
if len(local_header) < 30 or local_header[:4] != b"PK\x03\x04":
    raise SystemExit("invalid ZIP local header")
name_length, extra_length = struct.unpack_from("<2H", local_header, 26)
data_offset = local_offset + 30 + name_length + extra_length
compressed_size = int(member["compressed_size"])
compressed_read = min(compressed_size, MAX_COMPRESSED_PREFIX)
compressed = curl_bytes(
    archive_url, (data_offset, data_offset + compressed_read - 1)
)
if int(member["compression"]) == 0:
    decoded = compressed[:MAX_DECOMPRESSED_PREFIX]
else:
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    decoded = decoder.decompress(compressed, MAX_DECOMPRESSED_PREFIX)
complete_member = compressed_read == compressed_size and (
    int(member["compression"]) == 0 or decoder.eof
)

# Retain only complete CSV records when the range stopped within the member.
if not complete_member:
    newline = decoded.rfind(b"\n")
    if newline < 0:
        raise SystemExit("bounded member prefix contains no complete CSV row")
    decoded = decoded[:newline + 1]
text = decoded.decode("utf-8-sig", errors="strict")
reader = csv.reader(text.splitlines())
rows: list[list[str]] = []
bad_width_rows = 0
for row in reader:
    if not row:
        continue
    if len(row) != 5:
        bad_width_rows += 1
        continue
    rows.append(row)
if not rows:
    raise SystemExit("no five-field OBD rows found")

# Schema inference: ID and trip are decimal integers, PID is one byte of hex,
# value is numeric, and timestamp is an ISO-like date-time.
def is_decimal_integer(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", value.strip()))


def is_pid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Fa-f]{2}", value.strip()))


def is_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.strip())
        return True
    except ValueError:
        return False


schema_checks = {
    "field0_decimal_row_id_fraction": sum(is_decimal_integer(row[0]) for row in rows) / len(rows),
    "field1_decimal_trip_id_fraction": sum(is_decimal_integer(row[1]) for row in rows) / len(rows),
    "field2_hex_pid_fraction": sum(is_pid(row[2]) for row in rows) / len(rows),
    "field4_iso_timestamp_fraction": sum(is_timestamp(row[4]) for row in rows) / len(rows),
}
schema_credible = all(fraction >= 0.999 for fraction in schema_checks.values())

groups: dict[tuple[str, str], dict[str, object]] = defaultdict(
    lambda: {
        "count": 0, "numeric_count": 0, "integer_count": 0,
        "minimum": None, "maximum": None, "distinct": set(),
        "timestamps_monotonic": True, "previous_timestamp": None,
    }
)
for row in rows:
    trip_id, pid, value_text, timestamp = row[1].strip(), row[2].strip().upper(), row[3].strip(), row[4].strip()
    group = groups[(trip_id, pid)]
    group["count"] = int(group["count"]) + 1
    previous = group["previous_timestamp"]
    if previous is not None and timestamp < str(previous):
        group["timestamps_monotonic"] = False
    group["previous_timestamp"] = timestamp
    try:
        value = Decimal(value_text)
    except InvalidOperation:
        continue
    if not value.is_finite():
        continue
    group["numeric_count"] = int(group["numeric_count"]) + 1
    if value == value.to_integral_value():
        group["integer_count"] = int(group["integer_count"]) + 1
    if group["minimum"] is None or value < group["minimum"]:
        group["minimum"] = value
    if group["maximum"] is None or value > group["maximum"]:
        group["maximum"] = value
    distinct = group["distinct"]
    if isinstance(distinct, set) and len(distinct) <= 10_000:
        distinct.add(value)

columns = (
    "trip_id", "pid", "observations", "numeric_values", "integer_values",
    "minimum", "maximum", "distinct_values", "timestamps_monotonic",
    "complete_u8", "nonconstant", "provisional_candidate",
)
group_rows: list[dict[str, object]] = []
for (trip_id, pid), group in groups.items():
    count = int(group["count"])
    numeric_count = int(group["numeric_count"])
    integer_count = int(group["integer_count"])
    minimum = group["minimum"]
    maximum = group["maximum"]
    distinct_count = len(group["distinct"]) if isinstance(group["distinct"], set) else 0
    complete_u8 = (
        numeric_count == count and integer_count == count and
        minimum is not None and maximum is not None and
        Decimal(0) <= minimum <= maximum <= Decimal(255)
    )
    nonconstant = distinct_count > 1
    provisional = schema_credible and count >= MIN_SEQUENCE_VALUES and complete_u8 and nonconstant
    group_rows.append({
        "trip_id": trip_id, "pid": pid, "observations": count,
        "numeric_values": numeric_count, "integer_values": integer_count,
        "minimum": str(minimum) if minimum is not None else "",
        "maximum": str(maximum) if maximum is not None else "",
        "distinct_values": distinct_count,
        "timestamps_monotonic": int(bool(group["timestamps_monotonic"])),
        "complete_u8": int(complete_u8), "nonconstant": int(nonconstant),
        "provisional_candidate": int(provisional),
    })
group_rows.sort(
    key=lambda item: (-int(item["provisional_candidate"]), -int(item["observations"]), str(item["trip_id"]), str(item["pid"]))
)
with (OUT_DIR / "pid_groups.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(group_rows)

examples = rows[:20]
with (OUT_DIR / "row_examples.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(("field0", "field1", "field2", "field3", "field4"))
    writer.writerows(examples)

provisional_rows = [row for row in group_rows if int(row["provisional_candidate"])]
summary = {
    "candidate_id": "zenodo_aegis_obd_pid_u8",
    "record_id": RECORD_ID,
    "doi": clean_text(metadata.get("doi", "")),
    "license": license_value,
    "archive_size": archive_size,
    "member_name": str(member["name"]),
    "member_compressed_size": compressed_size,
    "member_uncompressed_size": int(member["uncompressed_size"]),
    "compressed_prefix_bytes": len(compressed),
    "decoded_complete_row_bytes": len(decoded),
    "complete_member_profiled": complete_member,
    "rows_profiled": len(rows),
    "bad_width_rows": bad_width_rows,
    "schema_checks": schema_checks,
    "schema_credible": schema_credible,
    "trip_ids_profiled": len({row["trip_id"] for row in group_rows}),
    "pids_profiled": len({row["pid"] for row in group_rows}),
    "trip_pid_groups": len(group_rows),
    "provisional_u8_groups": len(provisional_rows),
    "provisional_u8_values": sum(int(row["observations"]) for row in provisional_rows),
}
summary["outcome"] = (
    "promising_bounded_profile" if len(provisional_rows) >= 3 and summary["provisional_u8_values"] >= 100_000
    else "insufficient_u8_evidence"
)
(OUT_DIR / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
print("top trip/PID groups:")
for row in group_rows[:30]:
    print(
        f"trip={row['trip_id']} pid={row['pid']} n={row['observations']} "
        f"range={row['minimum']}..{row['maximum']} distinct={row['distinct_values']} "
        f"u8={row['complete_u8']} candidate={row['provisional_candidate']}"
    )
PY

echo "[$(date -Is)] preflight done candidate=$CANDIDATE_ID"
