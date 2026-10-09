#!/usr/bin/env bash
# Download the 29 pinned HDR+ burst first input frames (payload_N000.dng)
# listed in sources.tsv from the anonymous public GCS bucket gs://hdrplusdata.
# Each file is checked against the GCS object size and MD5, then parsed to
# confirm it is a full-resolution Pixel/Pixel XL 4048x3036 BGGR LJ92 CFA DNG.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="google_hdrplus_pixel_raw_bayer_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
DNG_DIR="$DOWNLOAD_DIR/dng"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-hdrplus-download/1.0"
EXPECTED_FILES=29
EXPECTED_BYTES=219795130

mkdir -p "$DNG_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Liveness: one-byte range GET of the first pinned object.
first_url="$(awk -F'\t' 'NR==2 {print $7}' "$RECIPE_DIR/sources.tsv")"
curl -fsSL --max-time 60 -r 0-0 -o /dev/null -A "$UA" "$first_url" \
  || { echo "FATAL: source bucket unreachable: $first_url" >&2; exit 1; }

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'burst\tmodel\tsize_bytes\tmd5_hex\tsha256\tlocal_path\turl\n' > "$plan.tmp"
count=0
bytes=0
while IFS=$'\t' read -r burst model cfa size_bytes md5_hex generation url; do
  [ "$burst" = "burst" ] && continue
  target="$DNG_DIR/${burst}__payload_N000.dng"
  if [ -s "$target" ] && [ "$(stat -c %s "$target")" = "$size_bytes" ] \
     && [ "$(md5sum "$target" | awk '{print $1}')" = "$md5_hex" ]; then
    echo "cache_hit burst=$burst bytes=$size_bytes"
  else
    echo "fetch burst=$burst model=$model bytes=$size_bytes"
    curl --globoff -fSL -C - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 20000000 \
      -A "$UA" -o "$target.part" "$url"
    actual="$(stat -c %s "$target.part")"
    if [ "$actual" != "$size_bytes" ]; then
      echo "FATAL: size mismatch burst=$burst expected=$size_bytes actual=$actual" >&2
      rm -f "$target.part"; exit 1
    fi
    if [ "$(md5sum "$target.part" | awk '{print $1}')" != "$md5_hex" ]; then
      echo "FATAL: MD5 mismatch burst=$burst" >&2
      rm -f "$target.part"; exit 1
    fi
    mv "$target.part" "$target"
  fi
  # Semantic check: full-res Pixel CFA IFD0 (make/model/dims/LJ92/BGGR/WhiteLevel).
  python3 -I - "$RECIPE_DIR/scripts" "$target" "$model" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import hdrplus_dng as hd
buf = open(sys.argv[2], "rb").read()
info = hd.dng_raw_info(hd.parse_tiff_ifd0(buf))
hd.check_pixel_cfa(info)
if info["model"] != sys.argv[3]:
    raise SystemExit(f"model {info['model']!r} != pinned {sys.argv[3]!r}")
end = max(o + c for o, c in zip(info["tile_offsets"], info["tile_byte_counts"]))
if end > len(buf):
    raise SystemExit("tile data truncated")
if buf[info["tile_offsets"][0]:info["tile_offsets"][0] + 4] != b"\xff\xd8\xff\xc3":
    raise SystemExit("first tile is not an SOF3 lossless-JPEG stream")
PY
  sha="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$burst" "$model" "$size_bytes" "$md5_hex" "$sha" \
    "downloads/$DATASET_ID/dng/${burst}__payload_N000.dng" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < "$RECIPE_DIR/sources.tsv"

if [ "$count" != "$EXPECTED_FILES" ] || [ "$bytes" != "$EXPECTED_BYTES" ]; then
  echo "FATAL: expected $EXPECTED_FILES files / $EXPECTED_BYTES bytes, got $count / $bytes" >&2
  exit 1
fi
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
