#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="coco_panoptic_val2017_labels_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
MAX_IMAGES="${COCO_PANOPTIC_MAX_IMAGES:-384}"
EMIT_SEGMENT_IDS="${COCO_PANOPTIC_EMIT_SEGMENT_IDS:-1}"
MAX_PRIMARY_BYTES="${COCO_PANOPTIC_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MAX_IMAGES EMIT_SEGMENT_IDS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import io
import os
import shutil
import struct
import sys
import zlib
import zipfile
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_images = int(os.environ["MAX_IMAGES"])
emit_segment_ids = os.environ["EMIT_SEGMENT_IDS"] not in {"0", "false", "False", "no", "NO"}
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "coco_panoptic_val2017_labels_u8"
CAT_FAMILY = "coco_panoptic_category_id_u8"
SEG_FAMILY = "coco_panoptic_segment_id_u32"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgb(blob: bytes) -> tuple[int, int, bytes]:
    if not blob.startswith(PNG_SIG):
        raise ValueError("bad PNG signature")
    pos = len(PNG_SIG)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos + 8 <= len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        ctype = blob[pos + 4:pos + 8]
        start = pos + 8
        end = start + length
        if end + 4 > len(blob):
            raise ValueError("truncated PNG chunk")
        data = blob[start:end]
        pos = end + 4
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _flt, interlace = struct.unpack(">IIBBBBB", data)
        elif ctype == b"IDAT":
            idat.extend(data)
        elif ctype == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("missing IHDR")
    if bit_depth != 8 or color_type not in {2, 6} or interlace != 0:
        raise ValueError(f"unsupported PNG mode bit_depth={bit_depth} color_type={color_type} interlace={interlace}")
    channels = 3 if color_type == 2 else 4
    bpp = channels
    row_bytes = width * channels
    raw = zlib.decompress(bytes(idat))
    expected = height * (1 + row_bytes)
    if len(raw) != expected:
        raise ValueError(f"unexpected decompressed size {len(raw)} != {expected}")
    out = bytearray(width * height * 3)
    prev = bytearray(row_bytes)
    src_pos = 0
    out_pos = 0
    for _y in range(height):
        filt = raw[src_pos]
        src_pos += 1
        row = bytearray(raw[src_pos:src_pos + row_bytes])
        src_pos += row_bytes
        for i, x in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filt == 0:
                val = x
            elif filt == 1:
                val = (x + left) & 255
            elif filt == 2:
                val = (x + up) & 255
            elif filt == 3:
                val = (x + ((left + up) >> 1)) & 255
            elif filt == 4:
                val = (x + paeth(left, up, up_left)) & 255
            else:
                raise ValueError(f"unsupported PNG filter {filt}")
            row[i] = val
        if channels == 3:
            out[out_pos:out_pos + row_bytes] = row
            out_pos += row_bytes
        else:
            for i in range(0, row_bytes, 4):
                out[out_pos:out_pos + 3] = row[i:i + 3]
                out_pos += 3
        prev = row
    return width, height, bytes(out)


src = download_dir / "panoptic_annotations_trainval2017.zip"
if not src.is_file():
    raise SystemExit(f"missing {src}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
cat_dir = samples_dir / CAT_FAMILY
seg_dir = samples_dir / SEG_FAMILY
cat_dir.mkdir(parents=True, exist_ok=True)
if emit_segment_ids:
    seg_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
processed = 0
skipped_constant = 0
unknown_nonzero = 0
total_primary_bytes = 0

with zipfile.ZipFile(src) as zf:
    meta = json.loads(zf.read("annotations/panoptic_val2017.json"))
    annotations = sorted(meta["annotations"], key=lambda a: (a["file_name"], int(a["image_id"])))
    val_zip = zipfile.ZipFile(io.BytesIO(zf.read("annotations/panoptic_val2017.zip")))
    for ann in annotations:
        if processed >= max_images:
            break
        png_name = f"panoptic_val2017/{ann['file_name']}"
        id_to_cat = {int(s["id"]): int(s["category_id"]) for s in ann.get("segments_info", [])}
        width, height, rgb = decode_png_rgb(val_zip.read(png_name))
        pixels = width * height
        sample_bytes = pixels + (pixels * 4 if emit_segment_ids else 0)
        if total_primary_bytes + sample_bytes > max_primary_bytes:
            if processed >= 25:
                break
            raise SystemExit(f"primary byte cap reached before enough samples: cap={max_primary_bytes}")

        cats = bytearray(pixels)
        segs = array("I") if emit_segment_ids else None
        ci = 0
        bad_here = 0
        for i in range(0, len(rgb), 3):
            sid = rgb[i] | (rgb[i + 1] << 8) | (rgb[i + 2] << 16)
            cat = 0 if sid == 0 else id_to_cat.get(sid)
            if cat is None:
                bad_here += 1
                cat = 0
            if cat < 0 or cat > 255:
                raise SystemExit(f"category id out of uint8 range: {cat} in {ann['file_name']}")
            cats[ci] = cat
            if segs is not None:
                segs.append(sid)
            ci += 1
        if bad_here:
            unknown_nonzero += bad_here
            raise SystemExit(f"unknown nonzero segment ids in {ann['file_name']}: {bad_here}")
        if len(set(cats)) <= 1:
            skipped_constant += 1
            continue

        stem = Path(ann["file_name"]).stem
        cat_out = cat_dir / f"{stem}_category_id_{width}x{height}.bin"
        cat_out.write_bytes(bytes(cats))
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": CAT_FAMILY,
            "role": "primary",
            "sample_path": cat_out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": cat_out.stat().st_size,
            "value_count": pixels,
            "sample_geometry": f"grid_{height}x{width}",
            "sample_rank": 2,
            "image_id": int(ann["image_id"]),
            "source_file_name": ann["file_name"],
            "natural_record_kind": "coco_panoptic_label_map",
        })
        total_primary_bytes += cat_out.stat().st_size

        if segs is not None:
            if sys.byteorder != "little":
                segs.byteswap()
            seg_out = seg_dir / f"{stem}_segment_id_{width}x{height}.bin"
            seg_out.write_bytes(segs.tobytes())
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SEG_FAMILY,
                "role": "primary",
                "sample_path": seg_out.relative_to(data_root).as_posix(),
                "numeric_kind": "uint",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": seg_out.stat().st_size,
                "value_count": pixels,
                "sample_geometry": f"grid_{height}x{width}",
                "sample_rank": 2,
                "image_id": int(ann["image_id"]),
                "source_file_name": ann["file_name"],
                "natural_record_kind": "coco_panoptic_label_map",
            })
            total_primary_bytes += seg_out.stat().st_size
        processed += 1

if processed < 25:
    raise SystemExit(f"only {processed} non-constant samples produced")
if total_primary_bytes > max_primary_bytes:
    raise SystemExit(f"primary bytes exceed cap: {total_primary_bytes} > {max_primary_bytes}")

counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "processed_images": processed,
    "skipped_constant_images": skipped_constant,
    "emit_segment_ids": emit_segment_ids,
    "series": {
        CAT_FAMILY: sum(1 for r in index_rows if r["series_id"] == CAT_FAMILY),
        SEG_FAMILY: sum(1 for r in index_rows if r["series_id"] == SEG_FAMILY),
    },
    "primary_values": sum(counts),
    "primary_sample_bytes": total_primary_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "max_primary_bytes": max_primary_bytes,
    "unknown_nonzero_pixels": unknown_nonzero,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built images={processed} rows={len(index_rows)} bytes={total_primary_bytes} "
    f"series={stats['series']} median={stats['median_value_count']} "
    f"range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
