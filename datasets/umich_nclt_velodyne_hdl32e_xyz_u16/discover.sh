#!/usr/bin/env bash
# Discovery record (not part of the acquisition path; download.sh does not
# call it). Shows how the archive identity, multipart layout and the presence
# and format of the velodyne_sync members were established with small
# requests before the full 2.93 GB download:
#   * HEAD of the object: size 2,926,183,916, ETag "...-349", Last-Modified
#   * HEAD ?partNumber=1 / ?partNumber=349: 8,388,608-byte parts
#   * first 256 KiB: first tar member 2013-01-10/velodyne_hits.bin
#   * last 2 MiB: raw-inflate resync (scripts/probe_tail.py) shows
#     2013-01-10/velodyne_sync/<utime>.bin members at the end of the archive
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umich_nclt_velodyne_hdl32e_xyz_u16"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
URL="https://s3.us-east-2.amazonaws.com/nclt.perl.engin.umich.edu/velodyne_data/2013-01-10_vel.tar.gz"
SIZE=2926183916
mkdir -p "$OUT"

curl -fsSI --max-time 60 "$URL" | tee "$OUT/head.headers"
for part in 1 349; do
  curl -fsSI --max-time 60 "$URL?partNumber=$part" | tee "$OUT/part$part.headers"
done
curl -fsSL --max-time 120 --range 0-262143 -o "$OUT/first_256k.bin" "$URL"
python3 - "$OUT/first_256k.bin" <<'PY'
import sys, zlib
out = zlib.decompressobj(31).decompress(open(sys.argv[1], "rb").read())
print("first member:", out[:100].rstrip(b"\0").decode(), "size", int(out[124:136].rstrip(b"\0 "), 8))
PY
curl -fsSL --max-time 300 --range "$((SIZE - 2097152))-$((SIZE - 1))" -o "$OUT/last_2m.bin" "$URL"
python3 "$RECIPE_DIR/scripts/probe_tail.py" "$OUT/last_2m.bin"
