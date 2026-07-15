#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jrc_global_surface_water_occurrence_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
HEADER_DIR="$DOWNLOAD_DIR/headers"
CHUNK_DIR="$DOWNLOAD_DIR/chunks"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$HEADER_DIR" "$CHUNK_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

HEADER_BYTES="${GSW_HEADER_BYTES:-67108864}"
TILES_PER_SOURCE="${GSW_TILES_PER_SOURCE:-6}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
SOURCE_URLS="$DOWNLOAD_DIR/source_urls.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if [ -n "${GSW_URLS_FILE:-}" ]; then
  cp "$GSW_URLS_FILE" "$SOURCE_URLS"
else
  cat > "$SOURCE_URLS" <<'EOF'
source_id	url
0E_50N	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_0E_50Nv1_4_2021.tif
90W_30N	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_90W_30Nv1_4_2021.tif
70W_10S	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_70W_10Sv1_4_2021.tif
30E_0N	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_30E_0Nv1_4_2021.tif
80E_20N	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_80E_20Nv1_4_2021.tif
120E_30N	https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_120E_30Nv1_4_2021.tif
EOF
fi

if [ "$HEADER_BYTES" -lt 65536 ]; then
  echo "FATAL: GSW_HEADER_BYTES must be at least 65536" >&2
  exit 1
fi

tail -n +2 "$SOURCE_URLS" | while IFS=$'\t' read -r source_id url; do
  [ -n "$source_id" ] || continue
  out="$HEADER_DIR/${source_id}.header.bin"
  end=$((HEADER_BYTES - 1))
  cached_size=0
  if [ -f "$out" ]; then
    cached_size="$(wc -c < "$out" | tr -d ' ')"
  fi
  if [ "$cached_size" -ge 8388608 ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "header cache_hit source=$source_id bytes=$cached_size path=$out"
  else
    echo "fetch_header source=$source_id range=0-$end url=$url"
    curl --globoff -fL --retry 5 --retry-delay 3 \
      -H "Range: bytes=0-${end}" \
      --speed-limit 1024 --speed-time 120 \
      -A "$UA" -o "$out.tmp" "$url"
    mv "$out.tmp" "$out"
  fi
done

export SOURCE_URLS HEADER_DIR PLAN TILES_PER_SOURCE
python3 - <<'PY'
from __future__ import annotations

import csv
import math
import os
import struct
from pathlib import Path

source_urls = Path(os.environ["SOURCE_URLS"])
header_dir = Path(os.environ["HEADER_DIR"])
plan_path = Path(os.environ["PLAN"])
tiles_per_source = int(os.environ["TILES_PER_SOURCE"])

TYPE_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8,
    11: 4, 12: 8, 16: 8, 17: 8, 18: 8,
}
TYPE_FORMAT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 16: "Q", 17: "q", 18: "Q"}


def unpack_values(data: bytes, endian: str, field_type: int, count: int, raw: bytes) -> list[int]:
    size = TYPE_SIZES.get(field_type)
    if size is None:
        raise ValueError(f"unsupported TIFF field type {field_type}")
    nbytes = size * count
    if nbytes <= len(raw):
        value_bytes = raw[:nbytes]
    else:
        offset = struct.unpack(endian + ("Q" if len(raw) == 8 else "I"), raw)[0]
        if offset + nbytes > len(data):
            raise ValueError(f"TIFF value table outside fetched header: offset={offset} nbytes={nbytes}")
        value_bytes = data[offset:offset + nbytes]
    fmt = TYPE_FORMAT.get(field_type)
    if fmt is None:
        return []
    return list(struct.unpack(endian + fmt * count, value_bytes))


def parse_tiff_header(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError(f"{path.name}: not TIFF")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    tags: dict[int, tuple[int, int, bytes]] = {}
    if magic == 42:
        ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
        entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
        for i in range(entry_count):
            off = ifd_offset + 2 + i * 12
            tag, field_type, count = struct.unpack_from(endian + "HHI", data, off)
            tags[tag] = (field_type, count, data[off + 8:off + 12])
    elif magic == 43:
        bytesize, zero = struct.unpack_from(endian + "HH", data, 4)
        if bytesize != 8 or zero != 0:
            raise ValueError(f"{path.name}: unsupported BigTIFF header")
        ifd_offset = struct.unpack_from(endian + "Q", data, 8)[0]
        entry_count = struct.unpack_from(endian + "Q", data, ifd_offset)[0]
        for i in range(entry_count):
            off = ifd_offset + 8 + i * 20
            tag, field_type, count = struct.unpack_from(endian + "HHQ", data, off)
            tags[tag] = (field_type, count, data[off + 12:off + 20])
    else:
        raise ValueError(f"{path.name}: unsupported TIFF magic {magic}")

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        field_type, count, raw = tags[tag]
        return unpack_values(data, endian, field_type, count, raw)

    width = values(256)[0]
    height = values(257)[0]
    bits = values(258)[0]
    compression = (values(259) or [1])[0]
    samples_per_pixel = (values(277) or [1])[0]
    sample_format = (values(339) or [1])[0]
    predictor = (values(317) or [1])[0]
    tile_width = values(322)[0]
    tile_length = values(323)[0]
    offsets = values(324)
    byte_counts = values(325)
    if bits != 8 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: not single-band uint8 bits={bits} "
            f"samples={samples_per_pixel} sample_format={sample_format}"
        )
    if compression not in {1, 5, 8, 32946}:
        raise ValueError(f"{path.name}: unsupported compression {compression}")
    if predictor not in {1, 2}:
        raise ValueError(f"{path.name}: unsupported predictor {predictor}")
    if not offsets or len(offsets) != len(byte_counts):
        raise ValueError(f"{path.name}: tile offset/count length mismatch")
    tiles_across = math.ceil(width / tile_width)
    tiles_down = math.ceil(height / tile_length)
    if len(offsets) < tiles_across * tiles_down:
        raise ValueError(f"{path.name}: too few tile offsets")
    return {
        "width": width,
        "height": height,
        "compression": compression,
        "predictor": predictor,
        "tile_width": tile_width,
        "tile_length": tile_length,
        "offsets": offsets,
        "byte_counts": byte_counts,
        "tiles_across": tiles_across,
        "tiles_down": tiles_down,
    }


def select_indices(tiles_across: int, tiles_down: int, count: int) -> list[tuple[int, int, int]]:
    positions = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 2), (2, 3), (3, 3), (1, 3)]
    selected: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for px, py in positions:
        x = round(px * tiles_across / 4)
        y = round(py * tiles_down / 4)
        if tiles_across > 2:
            x = min(max(1, x), tiles_across - 2)
        else:
            x = min(max(0, x), tiles_across - 1)
        if tiles_down > 2:
            y = min(max(1, y), tiles_down - 2)
        else:
            y = min(max(0, y), tiles_down - 1)
        index = y * tiles_across + x
        if index not in seen:
            selected.append((index, x, y))
            seen.add(index)
        if len(selected) >= count:
            break
    return selected


sources = []
with source_urls.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        if row.get("source_id") and row.get("url"):
            sources.append(row)

with plan_path.open("w", encoding="utf-8", newline="") as out:
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow([
        "sample_id", "source_id", "url", "tile_index", "tile_x", "tile_y",
        "raster_width", "raster_height", "tile_width", "tile_length",
        "compression", "predictor", "byte_offset", "byte_count", "chunk_path",
    ])
    for source in sources:
        source_id = source["source_id"]
        info = parse_tiff_header(header_dir / f"{source_id}.header.bin")
        for tile_index, tile_x, tile_y in select_indices(
            int(info["tiles_across"]), int(info["tiles_down"]), tiles_per_source
        ):
            sample_id = f"{source_id}_tile{tile_index:06d}_x{tile_x:04d}_y{tile_y:04d}"
            chunk_path = f"chunks/{sample_id}.tiff_tile"
            writer.writerow([
                sample_id, source_id, source["url"], tile_index, tile_x, tile_y,
                info["width"], info["height"], info["tile_width"], info["tile_length"],
                info["compression"], info["predictor"], info["offsets"][tile_index],
                info["byte_counts"][tile_index], chunk_path,
            ])
print(f"wrote plan {plan_path}")
PY

tail -n +2 "$PLAN" | while IFS=$'\t' read -r sample_id source_id url tile_index tile_x tile_y raster_width raster_height tile_width tile_length compression predictor byte_offset byte_count chunk_path; do
  out="$DOWNLOAD_DIR/$chunk_path"
  header="$HEADER_DIR/${source_id}.header.bin"
  mkdir -p "$(dirname "$out")"
  end=$((byte_offset + byte_count - 1))
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "chunk cache_hit sample=$sample_id bytes=$(wc -c < "$out" | tr -d ' ')"
  elif [ -f "$header" ] && [ "$(wc -c < "$header" | tr -d ' ')" -ge $((byte_offset + byte_count)) ]; then
    echo "chunk extract_from_cached_tiff sample=$sample_id range=${byte_offset}-${end}"
    dd if="$header" of="$out.tmp" bs=1 skip="$byte_offset" count="$byte_count" status=none
    mv "$out.tmp" "$out"
  else
    echo "fetch_chunk sample=$sample_id range=${byte_offset}-${end} url=$url"
    curl --globoff -fL --retry 5 --retry-delay 3 \
      -H "Range: bytes=${byte_offset}-${end}" \
      --speed-limit 1024 --speed-time 120 \
      -A "$UA" -o "$out.tmp" "$url"
    mv "$out.tmp" "$out"
  fi
done

export DOWNLOAD_DIR PLAN
python3 - <<'PY'
from __future__ import annotations

import csv
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
rows = 0
total = 0
with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        rows += 1
        path = download_dir / row["chunk_path"]
        expected = int(row["byte_count"])
        if not path.is_file():
            raise SystemExit(f"missing chunk {path}")
        actual = path.stat().st_size
        if actual != expected:
            raise SystemExit(f"chunk size mismatch {path}: {actual} != {expected}")
        total += actual
if rows < 12:
    raise SystemExit(f"too few planned chunks: {rows}")
print(f"range chunks ok: chunks={rows} compressed_bytes={total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
