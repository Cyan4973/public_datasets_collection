#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tum_rgbd_depth_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tarfile
import zlib
from array import array
from pathlib import Path

DATASET_ID = "tum_rgbd_depth_u16"
SERIES_ID = "tum_rgbd_depth_u16"
MAX_FRAMES = int(os.environ.get("TUM_MAX_FRAMES", "400"))
MIN_FRAMES = int(os.environ.get("TUM_MIN_FRAMES", "50"))
MAX_PRIMARY_BYTES = int(os.environ.get("TUM_MAX_PRIMARY_BYTES", "1000000000"))

data_root = Path(os.environ["DATA_ROOT"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

DEPTH_RE = re.compile(r"/depth/[^/]+\.png$")


def decode_png_gray16(data: bytes) -> tuple[int, int, array]:
    """Decode a non-interlaced 16-bit grayscale PNG to a little-endian uint16
    array (pure stdlib: zlib + PNG scanline unfiltering)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, n = 8, len(data)
    width = height = None
    idat = bytearray()
    while pos + 8 <= n:
        ln = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln  # length(4) + type(4) + data + crc(4)
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", cdata)
            if bitdepth != 16 or colortype != 0:
                raise ValueError(f"unsupported PNG bit_depth={bitdepth} color_type={colortype}")
            if interlace != 0:
                raise ValueError("interlaced PNG unsupported")
        elif ctype == b"IDAT":
            idat += cdata
        elif ctype == b"IEND":
            break
    if width is None:
        raise ValueError("missing IHDR")
    raw = zlib.decompress(bytes(idat))
    bpp = 2                     # 16-bit grayscale
    stride = width * bpp
    if len(raw) != (stride + 1) * height:
        raise ValueError(f"bad raw size {len(raw)} != {(stride + 1) * height}")
    out = bytearray(height * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        ft = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if ft == 1:      # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:    # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:    # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError(f"bad filter type {ft}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    # PNG stores 16-bit samples big-endian; convert to little-endian uint16.
    a = array("H")
    a.frombytes(bytes(out))
    if sys.byteorder == "little":
        a.byteswap()   # bytes were big-endian; correct the values to native
    return width, height, a


shutil.rmtree(samples_dir, ignore_errors=True)
(samples_dir / SERIES_ID).mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

archives = sorted(p for p in download_dir.glob("*.tgz")) + sorted(download_dir.glob("*.tar.gz"))
if not archives:
    raise SystemExit(f"no .tgz archives under {download_dir}; run download.sh first")

rows = []
total_bytes = 0
skips = {"constant": 0, "decode_error": 0, "wrong_shape": 0}
frames = 0
for arc in archives:
    if frames >= MAX_FRAMES:
        break
    with tarfile.open(arc, "r:gz") as tf:
        for member in tf:  # streaming, archive order (deterministic per file)
            if frames >= MAX_FRAMES:
                break
            if not (member.isfile() and DEPTH_RE.search(member.name)):
                continue
            fh = tf.extractfile(member)
            if fh is None:
                continue
            try:
                width, height, vals = decode_png_gray16(fh.read())
            except Exception:
                skips["decode_error"] += 1
                continue
            if width * height != len(vals):
                skips["wrong_shape"] += 1
                continue
            vmin, vmax = min(vals), max(vals)
            if vmin == vmax:
                skips["constant"] += 1
                continue
            stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(member.name).stem)
            out = samples_dir / SERIES_ID / f"{arc.stem}_{stem}.bin"
            out.write_bytes(vals.tobytes())
            size = out.stat().st_size
            total_bytes += size
            if total_bytes > MAX_PRIMARY_BYTES:
                raise SystemExit(f"primary output exceeds cap: {total_bytes}")
            frames += 1
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": "uint",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": size,
                "value_count": len(vals),
                "min": int(vmin),
                "max": int(vmax),
                "sample_geometry": "2d_raster",
                "sample_rank": 2,
                "sample_shape": [height, width],
                "sample_axes": ["y", "x"],
                "natural_record_kind": "tum_rgbd_depth_frame",
                "source_archive": arc.name,
            })

if len(rows) < MIN_FRAMES:
    raise SystemExit(f"only {len(rows)} depth frames (< {MIN_FRAMES}); skips={skips}")

stats = {
    "dataset_id": DATASET_ID,
    "archives": [a.name for a in archives],
    "frames": len(rows),
    "primary_bytes": total_bytes,
    "skips": skips,
    "shape": rows[0]["sample_shape"],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")

print(f"built frames={len(rows)} shape={rows[0]['sample_shape']} primary_bytes={total_bytes} skips={skips}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
