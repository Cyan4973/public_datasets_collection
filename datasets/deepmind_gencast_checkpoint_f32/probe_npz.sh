#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="deepmind_gencast_checkpoint_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/probes/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
HEADER_DIR="$OUT_DIR/entry_headers"
REPOSITORY="google-deepmind/graphcast"
REVISION="9c034db1ff412d5db6cbe6bb0c5c9afc5a267719"
OBJECT_NAME="gencast/params/GenCast 1p0deg Mini <2019.npz"
OBJECT_URL="https://storage.googleapis.com/dm_graphcast/gencast/params/GenCast%201p0deg%20Mini%20%3C2019.npz"
SOURCE_BYTES=230105815
SOURCE_GENERATION="1733326322411726"
SOURCE_MD5_BASE64="OQpDxDy29J6kbX/8cQTMmQ=="
TAIL_BYTES=8388608
TAIL_START=$((SOURCE_BYTES - TAIL_BYTES))
TAIL_END=$((SOURCE_BYTES - 1))

mkdir -p "$OUT_DIR" "$LOG_DIR" "$HEADER_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/probe_npz.$RUN_TS.log" "$LOG_DIR/probe_npz.latest.log") 2>&1
echo "[$(date -Is)] bounded NPZ probe start candidate=$CANDIDATE_ID"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 100000 \
  --user-agent "openzl-public-datasets-gencast-checkpoint-probe/1.1" \
  --output "$OUT_DIR/bucket_LICENSE.part" \
  "https://storage.googleapis.com/dm_graphcast/LICENSE"
mv "$OUT_DIR/bucket_LICENSE.part" "$OUT_DIR/bucket_LICENSE"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 1000000 \
  --user-agent "openzl-public-datasets-gencast-checkpoint-probe/1.0" \
  --output "$OUT_DIR/gencast_README.md.part" \
  "https://raw.githubusercontent.com/$REPOSITORY/$REVISION/docs/weathernext1_gen/README.md"
mv "$OUT_DIR/gencast_README.md.part" "$OUT_DIR/gencast_README.md"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 2000000 \
  --user-agent "openzl-public-datasets-gencast-checkpoint-probe/1.0" \
  --get --data-urlencode "maxResults=10" --data-urlencode "prefix=$OBJECT_NAME" \
  --output "$OUT_DIR/object_listing.json.part" \
  "https://storage.googleapis.com/storage/v1/b/dm_graphcast/o"
mv "$OUT_DIR/object_listing.json.part" "$OUT_DIR/object_listing.json"

export OBJECT_NAME OUT_DIR REVISION SOURCE_BYTES SOURCE_GENERATION SOURCE_MD5_BASE64
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import re


out_dir = Path(os.environ["OUT_DIR"])
license_text = (out_dir / "bucket_LICENSE").read_text(encoding="utf-8", errors="strict")
if "Creative Commons Attribution 4.0 International Public License" not in license_text:
    raise SystemExit("dm_graphcast bucket license is missing or changed")
readme = (out_dir / "gencast_README.md").read_text(encoding="utf-8", errors="strict")
normalized_readme = re.sub(r"\s+", " ", readme)
required_readme_phrases = (
    "The license for the model weights in this repository",
    "updated to permit commercial use",
    "Creative Commons Attribution 4.0 International",
)
missing = [phrase for phrase in required_readme_phrases if phrase not in normalized_readme]
if missing:
    raise SystemExit(f"GenCast model-weight licensing text changed; missing={missing}")

listing = json.loads((out_dir / "object_listing.json").read_text(encoding="utf-8"))
items = [
    item
    for item in listing.get("items", [])
    if isinstance(item, dict) and item.get("name") == os.environ["OBJECT_NAME"]
]
if len(items) != 1:
    raise SystemExit(f"expected one exact checkpoint object, found {len(items)}")
item = items[0]
expected = {
    "size": os.environ["SOURCE_BYTES"],
    "generation": os.environ["SOURCE_GENERATION"],
    "md5Hash": os.environ["SOURCE_MD5_BASE64"],
}
changed = {key: (expected_value, str(item.get(key) or "")) for key, expected_value in expected.items() if str(item.get(key) or "") != expected_value}
if changed:
    raise SystemExit(f"checkpoint object identity changed: {changed}")
print(
    "license_and_identity=ok "
    f"revision={os.environ['REVISION']} bytes={item['size']} generation={item['generation']}"
)
PY

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 300 --max-filesize "$TAIL_BYTES" \
  --user-agent "openzl-public-datasets-gencast-checkpoint-probe/1.0" \
  --header "Range: bytes=$TAIL_START-$TAIL_END" \
  --dump-header "$OUT_DIR/tail.headers.part" \
  --output "$OUT_DIR/tail.bin.part" "$OBJECT_URL"
if [[ "$(stat -c %s "$OUT_DIR/tail.bin.part")" != "$TAIL_BYTES" ]]; then
  echo "checkpoint tail size changed: $(stat -c %s "$OUT_DIR/tail.bin.part")" >&2
  exit 1
fi
mv "$OUT_DIR/tail.bin.part" "$OUT_DIR/tail.bin"
mv "$OUT_DIR/tail.headers.part" "$OUT_DIR/tail.headers"

export TAIL_START
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import struct


out_dir = Path(os.environ["OUT_DIR"])
tail_start = int(os.environ["TAIL_START"])
tail = (out_dir / "tail.bin").read_bytes()
eocd_at = tail.rfind(b"PK\x05\x06")
if eocd_at < 0 or eocd_at + 22 > len(tail):
    raise SystemExit("ZIP end-of-central-directory record not found in bounded tail")
(
    _signature,
    disk_number,
    central_disk,
    entries_on_disk,
    entries_total,
    central_size,
    central_offset,
    comment_length,
) = struct.unpack_from("<4s4H2LH", tail, eocd_at)
if any(value == 0xFFFF for value in (entries_on_disk, entries_total)) or any(
    value == 0xFFFFFFFF for value in (central_size, central_offset)
):
    raise SystemExit("ZIP64 central directory is not yet supported by this bounded probe")
if disk_number != 0 or central_disk != 0 or entries_on_disk != entries_total:
    raise SystemExit("multi-disk ZIP archives are not supported")
if eocd_at + 22 + comment_length > len(tail):
    raise SystemExit("truncated ZIP end record or comment")
central_relative = central_offset - tail_start
if central_relative < 0 or central_relative + central_size > len(tail):
    raise SystemExit(
        f"central directory is outside the {len(tail)}-byte tail; "
        f"offset={central_offset} size={central_size}"
    )


def zip64_values(extra: bytes, needs: tuple[bool, bool, bool]) -> tuple[int | None, int | None, int | None]:
    cursor = 0
    while cursor + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        payload = extra[cursor : cursor + field_size]
        cursor += field_size
        if field_id != 0x0001:
            continue
        values: list[int | None] = []
        offset = 0
        for needed in needs:
            if needed:
                if offset + 8 > len(payload):
                    raise SystemExit("truncated ZIP64 extended information")
                values.append(struct.unpack_from("<Q", payload, offset)[0])
                offset += 8
            else:
                values.append(None)
        return tuple(values)  # type: ignore[return-value]
    return (None, None, None)


entries: list[dict[str, object]] = []
cursor = central_relative
end = central_relative + central_size
while cursor < end:
    if tail[cursor : cursor + 4] != b"PK\x01\x02" or cursor + 46 > len(tail):
        raise SystemExit(f"invalid central-directory entry at relative offset {cursor}")
    fields = struct.unpack_from("<4s6H3L5H2L", tail, cursor)
    (
        _signature,
        _made_by,
        _needed,
        flags,
        method,
        _mtime,
        _mdate,
        crc32,
        compressed_size,
        uncompressed_size,
        name_length,
        extra_length,
        comment_length,
        disk_start,
        _internal_attrs,
        _external_attrs,
        local_offset,
    ) = fields
    body = cursor + 46
    name_bytes = tail[body : body + name_length]
    extra = tail[body + name_length : body + name_length + extra_length]
    name = name_bytes.decode("utf-8" if flags & 0x800 else "cp437")
    need_uncompressed = uncompressed_size == 0xFFFFFFFF
    need_compressed = compressed_size == 0xFFFFFFFF
    need_offset = local_offset == 0xFFFFFFFF
    if need_uncompressed or need_compressed or need_offset:
        z_uncompressed, z_compressed, z_offset = zip64_values(
            extra, (need_uncompressed, need_compressed, need_offset)
        )
        if z_uncompressed is not None:
            uncompressed_size = z_uncompressed
        if z_compressed is not None:
            compressed_size = z_compressed
        if z_offset is not None:
            local_offset = z_offset
    entries.append(
        {
            "name": name,
            "compression_method": method,
            "flags": flags,
            "crc32": f"{crc32:08x}",
            "compressed_size": compressed_size,
            "uncompressed_size": uncompressed_size,
            "local_header_offset": local_offset,
            "disk_start": disk_start,
        }
    )
    cursor = body + name_length + extra_length + comment_length
if cursor != end or len(entries) != entries_total:
    raise SystemExit(
        f"central-directory count/size mismatch entries={len(entries)}/{entries_total} cursor={cursor}/{end}"
    )

columns = (
    "name",
    "compression_method",
    "flags",
    "crc32",
    "compressed_size",
    "uncompressed_size",
    "local_header_offset",
    "disk_start",
)
with (out_dir / "central_entries.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(entries)

npy_entries = [row for row in entries if str(row["name"]).endswith(".npy")]
stored = [row for row in npy_entries if int(row["compression_method"]) == 0]
selected = sorted(stored, key=lambda row: (-int(row["uncompressed_size"]), str(row["name"])))[:64]
with (out_dir / "header_requests.tsv").open("w", encoding="utf-8", newline="") as handle:
    columns = ("request_id", "name", "start", "end", "uncompressed_size")
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for index, row in enumerate(selected, start=1):
        start = int(row["local_header_offset"])
        writer.writerow(
            {
                "request_id": f"{index:03d}",
                "name": row["name"],
                "start": start,
                "end": min(int(os.environ["SOURCE_BYTES"]) - 1, start + 8191),
                "uncompressed_size": row["uncompressed_size"],
            }
        )

directory_summary = {
    "archive_entries": len(entries),
    "npy_entries": len(npy_entries),
    "stored_npy_entries": len(stored),
    "deflated_npy_entries": sum(1 for row in npy_entries if int(row["compression_method"]) == 8),
    "selected_header_ranges": len(selected),
    "central_directory_offset": central_offset,
    "central_directory_size": central_size,
}
(out_dir / "directory_summary.json").write_text(
    json.dumps(directory_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(directory_summary, indent=2, sort_keys=True))
PY

while IFS=$'\t' read -r request_id name start end uncompressed_size; do
  [[ "$request_id" != "request_id" ]] || continue
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize 8192 \
    --user-agent "openzl-public-datasets-gencast-checkpoint-probe/1.0" \
    --header "Range: bytes=$start-$end" \
    --output "$HEADER_DIR/$request_id.bin.part" "$OBJECT_URL"
  mv "$HEADER_DIR/$request_id.bin.part" "$HEADER_DIR/$request_id.bin"
  echo "entry_header id=$request_id bytes=$(stat -c %s "$HEADER_DIR/$request_id.bin") name=$name"
done < "$OUT_DIR/header_requests.tsv"

export HEADER_DIR
python3 - <<'PY'
from __future__ import annotations

import ast
import csv
import json
import os
from pathlib import Path
import struct


out_dir = Path(os.environ["OUT_DIR"])
header_dir = Path(os.environ["HEADER_DIR"])
requests: list[dict[str, str]] = []
with (out_dir / "header_requests.tsv").open(encoding="utf-8", newline="") as handle:
    requests = list(csv.DictReader(handle, delimiter="\t"))

arrays: list[dict[str, object]] = []
for request in requests:
    blob = (header_dir / f"{request['request_id']}.bin").read_bytes()
    if len(blob) < 30 or blob[:4] != b"PK\x03\x04":
        raise SystemExit(f"invalid local ZIP header for {request['name']!r}")
    fields = struct.unpack_from("<4s5H3L2H", blob, 0)
    method = fields[3]
    name_length = fields[-2]
    extra_length = fields[-1]
    payload_offset = 30 + name_length + extra_length
    payload = blob[payload_offset:]
    if method != 0:
        raise SystemExit(f"selected non-stored entry unexpectedly: {request['name']!r}")
    if not payload.startswith(b"\x93NUMPY") or len(payload) < 10:
        raise SystemExit(f"missing NPY header for {request['name']!r}")
    major, minor = payload[6], payload[7]
    if major == 1:
        header_length = struct.unpack_from("<H", payload, 8)[0]
        header_start = 10
    elif major in {2, 3}:
        header_length = struct.unpack_from("<I", payload, 8)[0]
        header_start = 12
    else:
        raise SystemExit(f"unsupported NPY version {major}.{minor} for {request['name']!r}")
    header_end = header_start + header_length
    if header_end > len(payload):
        raise SystemExit(f"NPY header exceeds bounded entry prefix for {request['name']!r}")
    header = ast.literal_eval(payload[header_start:header_end].decode("latin1").strip())
    shape = tuple(int(value) for value in header["shape"])
    value_count = 1
    for extent in shape:
        value_count *= extent
    arrays.append(
        {
            "name": request["name"],
            "dtype": str(header["descr"]),
            "fortran_order": bool(header["fortran_order"]),
            "rank": len(shape),
            "shape": ",".join(str(value) for value in shape),
            "value_count": value_count,
            "npy_entry_bytes": int(request["uncompressed_size"]),
        }
    )

with (out_dir / "array_headers.tsv").open("w", encoding="utf-8", newline="") as handle:
    columns = ("name", "dtype", "fortran_order", "rank", "shape", "value_count", "npy_entry_bytes")
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(arrays)

float32 = [row for row in arrays if row["dtype"] in {"<f4", "=f4", "f4"}]
matrix_float32 = [row for row in float32 if int(row["rank"]) == 2 and int(row["value_count"]) >= 1000]
summary = {
    "candidate_id": "deepmind_gencast_checkpoint_f32",
    "source_object": os.environ["OBJECT_NAME"],
    "source_bytes": int(os.environ["SOURCE_BYTES"]),
    "source_generation": os.environ["SOURCE_GENERATION"],
    "source_md5_base64": os.environ["SOURCE_MD5_BASE64"],
    "bounded_tail_bytes": 8_388_608,
    "array_headers_probed": len(arrays),
    "native_float32_headers": len(float32),
    "large_rank2_float32_headers": len(matrix_float32),
    "probed_float32_values": sum(int(row["value_count"]) for row in float32),
    "probed_float32_bytes": sum(int(row["value_count"]) * 4 for row in float32),
    "complete_checkpoint_downloaded": False,
    "next_step": (
        "Download the complete checkpoint only if native float32 tensor headers establish "
        "substantial matrix-shaped parameter material distinct from convolution kernels."
    ),
}
(out_dir / "probe_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
print("largest_probed_arrays:")
for row in arrays[:30]:
    print(
        f"  dtype={row['dtype']} rank={row['rank']} shape={row['shape']} "
        f"values={row['value_count']} name={row['name']!r}"
    )
PY

echo "[$(date -Is)] bounded NPZ probe done candidate=$CANDIDATE_ID"
