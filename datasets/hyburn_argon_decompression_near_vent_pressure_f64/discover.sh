#!/usr/bin/env bash
# Metadata-only discovery that produced scripts/near_vent_members.tsv.
#
# For every near_vent_NNNNNN.npz on Zenodo record 4127362 this fetches the
# last 8 KiB of the archive (ZIP central directory + the 88-byte time.npy
# member) and the 128-byte local header of pressure.npy, then pins offsets,
# compressed sizes, CRC32s and simulation times.  For early snapshots
# (index <= PROBE_MAX, where the archives are small) it also fetches the full
# pressure.npy member to measure the dominant-value fraction that motivates
# the start-of-range rule.  Total transfer is a few MB.  download.sh does not
# depend on this script; it uses the committed pinned table.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hyburn_argon_decompression_near_vent_pressure_f64"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
RANGES="$OUT_DIR/ranges"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=4127362
BASE="https://zenodo.org/api/records/$RECORD_ID/files"
PROBE_MAX="${PROBE_MAX:-80}"
UA="openzl-public-datasets-hyburn-discovery/1.0"

mkdir -p "$RANGES" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

fetch() { # url range out
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 120 --user-agent "$UA" --range "$2" --output "$3.part" "$1"
  mv "$3.part" "$3"
}

if [ ! -s "$OUT_DIR/files.json" ]; then
  curl --fail --silent --show-error --location --retry 5 --max-time 180 --user-agent "$UA" \
    --output "$OUT_DIR/files.json.part" "$BASE"
  mv "$OUT_DIR/files.json.part" "$OUT_DIR/files.json"
fi

python3 -I - "$OUT_DIR/files.json" > "$OUT_DIR/near_vent_files.tsv" <<'PY'
import json, re, sys
entries = json.load(open(sys.argv[1]))["entries"]
for e in sorted(entries, key=lambda e: e["key"]):
    if re.fullmatch(r"near_vent_\d{6}\.npz", e["key"]):
        print(f"{e['key']}\t{e['size']}")
PY

while IFS=$'\t' read -r key size; do
  stem="${key%.npz}"
  url="$BASE/$key/content"
  [ -s "$RANGES/$stem.tail" ] || fetch "$url" "$((size - 8192))-$((size - 1))" "$RANGES/$stem.tail"
  read -r off csize < <(python3 -I - "$RANGES/$stem.tail" "$size" "$RECIPE_DIR/scripts" <<'PY'
import sys
sys.path.insert(0, sys.argv[3])
from hyburn_npz import parse_central_directory
tail = open(sys.argv[1], "rb").read(); total = int(sys.argv[2])
m = {x["name"]: x for x in parse_central_directory(tail, total - len(tail), total)}["pressure.npy"]
print(m["offset"], m["csize"])
PY
)
  [ -s "$RANGES/$stem.lh" ] || fetch "$url" "$off-$((off + 127))" "$RANGES/$stem.lh"
  snap=$((10#${stem##*_}))
  if [ "$snap" -le "$PROBE_MAX" ] && [ ! -s "$RANGES/$stem.pressure" ]; then
    fetch "$url" "$off-$((off + 42 + csize - 1))" "$RANGES/$stem.pressure"
  fi
  echo "probed $key size=$size pressure_off=$off csize=$csize"
done < "$OUT_DIR/near_vent_files.tsv"

python3 -I "$RECIPE_DIR/scripts/hyburn_npz.py" discover-parse \
  --files-json "$OUT_DIR/files.json" --ranges-dir "$RANGES" --out "$OUT_DIR/near_vent_members.tsv"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID table=$OUT_DIR/near_vent_members.tsv"
