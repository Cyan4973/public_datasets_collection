#!/usr/bin/env bash
# Documentation of how the pinned resources were resolved (not part of the
# acceptance path). Small metadata probes only: the version-pinned dataset
# JSON, the last 64 KiB of the archive (ZIP central directory) and the first
# 1 MiB (header of the first Stata member), via byte ranges.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="wiod2016_world_input_output_tables_f64"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
URL="https://dataverse.nl/api/access/datafile/199103"
TOTAL=638963496
mkdir -p "$OUT"

curl --globoff -fsSL --max-time 120 -o "$OUT/dataset_v2.1.json" \
  "https://dataverse.nl/api/datasets/:persistentId/versions/2.1?persistentId=doi:10.34894/PJ2M1C"
python3 "$RECIPE_DIR/scripts/wiod_wiot.py" validate-metadata --metadata "$OUT/dataset_v2.1.json"
curl -fsSL --max-time 120 -r "$((TOTAL - 65536))-$((TOTAL - 1))" -o "$OUT/tail.bin" "$URL"
curl -fsSL --max-time 120 -r 0-1048575 -o "$OUT/head.bin" "$URL"

python3 - "$OUT/tail.bin" "$OUT/head.bin" "$TOTAL" "$RECIPE_DIR/scripts" <<'PY'
import io
import struct
import sys
import zlib

tail = open(sys.argv[1], "rb").read()
head = open(sys.argv[2], "rb").read()
total = int(sys.argv[3])
sys.path.insert(0, sys.argv[4])
import wiod_wiot  # noqa: E402

base = total - len(tail)
eocd = tail.rfind(b"PK\x05\x06")
_, _, _, _, entries, _, cd_offset, _ = struct.unpack_from("<IHHHHIIH", tail, eocd)
pos = cd_offset - base
for _ in range(entries):
    fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
    name = tail[pos + 46 : pos + 46 + fields[10]].decode()
    print(f"member {name} method={fields[4]} crc32={fields[7]:08x} compressed={fields[8]} size={fields[9]} offset={fields[16]}")
    pos += 46 + fields[10] + fields[11] + fields[12]
name_len, extra_len = struct.unpack_from("<HH", head, 26)
prefix = zlib.decompressobj(-15).decompress(head[30 + name_len + extra_len :])
header = wiod_wiot.parse_header_map(io.BytesIO(prefix), wiod_wiot.MEMBER_BYTES)
wiod_wiot.check_variables(header, wiod_wiot.Spec(), "first member")
print(f"first member: K={header.k} N={header.n} row_width={header.row_width} map={header.offsets}")
PY
