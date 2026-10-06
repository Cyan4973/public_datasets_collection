#!/usr/bin/env bash
# Documentation probe: how members.tsv was resolved. Fetches only the ZIP tail
# (end-of-central-directory + central directory, < 70 KB) of each pinned
# steady-state archive with an HTTP range request and prints the CSV members
# (name, local-header offset, compressed/uncompressed size, CRC32).
# Not needed by download.sh/build.sh/verify.sh.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_gridgnosis_pmu_voltage_magnitude_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
UA="openzl-public-datasets-pmu-voltage-discover/1.0"
mkdir -p "$OUT_DIR"

# record_id|archive size|tail start offset
for spec in "20308780|894457235|894440000" "17648863|201941844|201876000"; do
  IFS='|' read -r record_id size start <<< "$spec"
  url="https://zenodo.org/api/records/$record_id/files/Steady%20state%20data.zip/content"
  tail_file="$OUT_DIR/record_${record_id}_zip_tail.bin"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 120 --user-agent "$UA" --range "$start-$((size - 1))" \
    --output "$tail_file" "$url"
  python3 - "$tail_file" "$start" "$record_id" <<'PY'
import struct
import sys

path, base, record_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data = open(path, "rb").read()
eocd = data.rfind(b"PK\x05\x06")
if eocd < 0:
    raise SystemExit("no end-of-central-directory record in the fetched tail")
_, _, _, _, entries, cd_size, cd_offset, _ = struct.unpack_from("<IHHHHIIH", data, eocd)
print(f"record={record_id} entries={entries} central_directory_offset={cd_offset} size={cd_size}")
pos = cd_offset - base
for _ in range(entries):
    fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", data, pos)
    flags, crc, csize, usize, nlen, elen, clen, offset = (
        fields[3], fields[7], fields[8], fields[9], fields[10], fields[11], fields[12], fields[16]
    )
    name = data[pos + 46 : pos + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    pos += 46 + nlen + elen + clen
    if name.endswith(".csv") and not name.startswith("__MACOSX/"):
        print(f"{offset}\t{csize}\t{usize}\t{crc:08x}\t{name}")
PY
done
