#!/usr/bin/env bash
# Metadata-only discovery for the Cartographer 2D-backpack bags.
#
# Documents how sources.tsv was resolved. The GCS bucket listing is denied, so
# the bag inventory comes from cartographer_ros docs/source/data.rst. For every
# listed backpack_2d bag this fetches only: response headers (size, MD5,
# CRC32C, generation), the first 8,192 bytes (magic + bag-header record
# giving index_pos) and the index section from index_pos to EOF
# (connection and chunk-info records, i.e. exact per-topic message counts).
# No message payloads are fetched. Output: discovery/<id>/bags.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cartographer_backpack2d_hokuyo_ranges_f32"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DATA_RST_URL="https://raw.githubusercontent.com/cartographer-project/cartographer_ros/master/docs/source/data.rst"
BAG_BASE="https://storage.googleapis.com/cartographer-public-data/bags/backpack_2d"
UA="openzl-public-datasets-cartographer-discovery/1.0"

mkdir -p "$OUT_DIR/heads" "$OUT_DIR/tails" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

small_get() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 300 --user-agent "$UA" "$@"
}

small_get --max-filesize 2000000 --output "$OUT_DIR/data.rst" "$DATA_RST_URL"

# bag, duration_s, floor, known issues from the backpack_2d table
python3 - "$OUT_DIR/data.rst" "$OUT_DIR/inventory.tsv" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
section = text.split("2D Cartographer Backpack", 1)[1].split("3D Cartographer Backpack", 1)[0]
if "Licensed under the Apache License, Version 2.0" not in section:
    raise SystemExit("backpack_2d section no longer carries the Apache-2.0 license text")
pattern = re.compile(
    r"^`(?P<bag>b[0-9]-[0-9-]+)\.bag <https://storage\.googleapis\.com/cartographer-public-data/bags/backpack_2d/(?P=bag)\.bag>`_"
    r"[ \t]+(?P<dur>\d+) s[ \t]+(?P<size>[0-9.]+ [MG]B)[ \t]+(?P<floor>1\. OG|EG|UG)[ \t]*(?P<issue>[^\n]*)$",
    re.MULTILINE,
)
rows = [m.groupdict() for m in pattern.finditer(section)]
if len(rows) != 56:
    raise SystemExit(f"expected 56 backpack_2d bags in data.rst, found {len(rows)}")
with open(sys.argv[2], "w", encoding="utf-8") as out:
    out.write("bag\tunit\tfloor\tduration_s\tlisted_size\tknown_issues\n")
    for row in rows:
        floor = "OG1" if row["floor"].startswith("1.") else row["floor"]
        out.write(f"{row['bag']}\t{row['bag'][:2]}\t{floor}\t{row['dur']}\t{row['size']}\t{row['issue'].strip()}\n")
print(f"inventory bags={len(rows)}")
PY

printf 'bag\tunit\tfloor\tduration_s\tknown_issues\tsize_bytes\tmd5_base64\tcrc32c_base64\tgcs_generation\tindex_pos\tchunk_count\tscan_count\tspan_seconds\tmessages_per_topic\n' > "$OUT_DIR/bags.tsv.part"
tail -n +2 "$OUT_DIR/inventory.tsv" | while IFS=$'\t' read -r bag unit floor duration listed issues; do
  url="$BAG_BASE/$bag.bag"
  headers="$OUT_DIR/heads/$bag.headers"
  small_get --head --output "$headers" "$url"
  size="$(tr -d '\r' < "$headers" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  md5="$(tr -d '\r' < "$headers" | sed -n 's/^[Xx]-[Gg]oog-[Hh]ash: md5=//p' | tail -1)"
  crc="$(tr -d '\r' < "$headers" | sed -n 's/^[Xx]-[Gg]oog-[Hh]ash: crc32c=//p' | tail -1)"
  gen="$(tr -d '\r' < "$headers" | awk 'tolower($1)=="x-goog-generation:"{v=$2} END{print v}')"
  if [ -z "$size" ] || [ -z "$md5" ] || [ -z "$gen" ]; then
    echo "FATAL: incomplete object metadata for $bag" >&2
    exit 1
  fi
  head_file="$OUT_DIR/heads/$bag.head"
  small_get --range 0-8191 --output "$head_file" "$url"
  index_pos="$(python3 -c '
import struct, sys
b = open(sys.argv[1], "rb").read()
assert b[:13] == b"#ROSBAG V2.0\n", "bad magic"
i = 13 + 4
end = i + struct.unpack_from("<I", b, 13)[0]
while i < end:
    n = struct.unpack_from("<I", b, i)[0]; f = b[i + 4:i + 4 + n]; i += 4 + n
    if f.startswith(b"index_pos="):
        print(struct.unpack("<Q", f[10:18])[0])
' "$head_file")"
  tail_file="$OUT_DIR/tails/$bag.tail"
  small_get --range "$index_pos-$((size - 1))" --max-filesize 5000000 --output "$tail_file" "$url"
  summary="$(python3 "$RECIPE_DIR/scripts/cartographer_hokuyo.py" index-summary \
    --head "$head_file" --tail "$tail_file" --size "$size")"
  python3 - "$summary" "$bag" "$unit" "$floor" "$duration" "$issues" "$size" "$md5" "$crc" "$gen" >> "$OUT_DIR/bags.tsv.part" <<'PY'
import json
import sys

s = json.loads(sys.argv[1])
bag, unit, floor, duration, issues, size, md5, crc, gen = sys.argv[2:]
print("\t".join([bag, unit, floor, duration, issues or "-", size, md5, crc, gen, str(s["index_pos"]),
                 str(s["chunk_count"]), str(s["scan_count"]), str(s["span_seconds"]),
                 json.dumps(s["messages_per_topic"], sort_keys=True, separators=(",", ":"))]))
PY
  echo "bag=$bag size=$size md5=$md5 index_pos=$index_pos $(tail -1 "$OUT_DIR/bags.tsv.part" | cut -f12,13)"
done
mv "$OUT_DIR/bags.tsv.part" "$OUT_DIR/bags.tsv"
echo "discovery bags=$(($(wc -l < "$OUT_DIR/bags.tsv") - 1)) table=$OUT_DIR/bags.tsv"

python3 "$RECIPE_DIR/scripts/select_sources.py" "$OUT_DIR/bags.tsv" "$OUT_DIR/sources.selected.tsv"
if cmp -s "$OUT_DIR/sources.selected.tsv" "$RECIPE_DIR/sources.tsv"; then
  echo "selection matches pinned sources.tsv"
else
  echo "WARNING: selection differs from pinned sources.tsv; review $OUT_DIR/sources.selected.tsv" >&2
fi
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
