#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bbbc038_nuclei_masks_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export BBBC038_MIN_VALUES="${BBBC038_MIN_VALUES:-1000}"
export BBBC038_MAX_PRIMARY_BYTES="${BBBC038_MAX_PRIMARY_BYTES:-950000000}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
import zlib
import zipfile
from collections import Counter
from pathlib import Path

DATASET_ID = "bbbc038_nuclei_masks_u8"
SERIES_ID = "bbbc038_nuclei_mask_u8"
MIN_VALUES = int(os.environ["BBBC038_MIN_VALUES"])
MAX_PRIMARY_BYTES = int(os.environ["BBBC038_MAX_PRIMARY_BYTES"])

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


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


def decode_png(data: bytes) -> tuple[bytes, int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not PNG")
    offset = 8
    width = height = bit_depth = color_type = None
    palette: list[tuple[int, int, int]] = []
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        ctype = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk)
            if compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported PNG compression/filter/interlace")
            if bit_depth != 8 or color_type not in {0, 3}:
                raise ValueError(f"unsupported PNG bit_depth={bit_depth} color_type={color_type}")
        elif ctype == b"PLTE":
            palette = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk), 3)]
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ValueError("missing IHDR")
    raw = zlib.decompress(bytes(idat))
    channels = 1
    stride = width * channels
    rows: list[bytearray] = []
    pos = 0
    prev = bytearray(stride)
    for _ in range(height):
        ftype = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            if ftype == 0:
                pass
            elif ftype == 1:
                row[i] = (row[i] + left) & 255
            elif ftype == 2:
                row[i] = (row[i] + up) & 255
            elif ftype == 3:
                row[i] = (row[i] + ((left + up) >> 1)) & 255
            elif ftype == 4:
                row[i] = (row[i] + paeth(left, up, up_left)) & 255
            else:
                raise ValueError(f"bad PNG filter {ftype}")
        rows.append(row)
        prev = row
    decoded = b"".join(rows)
    if color_type == 3 and palette:
        # For indexed masks, preserve the source index byte rather than RGB expansion.
        return decoded, width, height
    return decoded, width, height


for path in (extract_dir, out_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

archives = sorted(download_dir.glob("*.zip"))
if not archives:
    raise SystemExit(f"no ZIP archives found in {download_dir}")
for archive in archives:
    dest = extract_dir / archive.stem
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)

pngs = sorted(p for p in extract_dir.rglob("*.png") if "/masks/" in p.as_posix().lower())
if not pngs:
    raise SystemExit("no mask PNG files extracted")

rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_tiny = 0
skipped_constant = 0
decode_failures = 0
total_bytes = 0

for idx, png in enumerate(pngs, start=1):
    try:
        decoded, width, height = decode_png(png.read_bytes())
    except Exception as exc:
        decode_failures += 1
        records.append({"source_file": png.as_posix(), "status": "decode_failed", "error": str(exc)})
        continue
    value_count = width * height
    if len(decoded) != value_count:
        decode_failures += 1
        records.append({"source_file": png.as_posix(), "status": "bad_size", "decoded_bytes": len(decoded), "expected": value_count})
        continue
    if value_count < MIN_VALUES:
        skipped_tiny += 1
        continue
    hist = Counter(decoded)
    if len(hist) <= 1:
        skipped_constant += 1
        continue
    if total_bytes + len(decoded) > MAX_PRIMARY_BYTES:
        break
    safe_parent = png.parent.parent.name if png.parent.parent.name else "sample"
    out = out_dir / f"{idx:06d}_{safe_parent}_{png.stem}_n{value_count:07d}.bin"
    out.write_bytes(decoded)
    total_bytes += len(decoded)
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(decoded),
        "value_count": value_count,
        "sample_format": "raw homogeneous uint8 mask grid",
        "sample_geometry": "2d_microscopy_segmentation_mask",
        "sample_rank": 2,
        "sample_shape": [height, width],
        "sample_axes": ["y", "x"],
        "source_path": png.as_posix(),
        "source_file": png.name,
        "natural_record_kind": "bbbc038_mask_png",
    })
    records.append({
        "source_file": png.as_posix(),
        "status": "kept",
        "shape": [height, width],
        "distinct_values": len(hist),
        "min_value": min(hist),
        "max_value": max(hist),
        "most_common_value": hist.most_common(1)[0][0],
        "most_common_fraction": hist.most_common(1)[0][1] / len(decoded),
    })

if not rows:
    raise SystemExit(
        f"no qualifying samples; skipped_tiny={skipped_tiny} "
        f"skipped_constant={skipped_constant} decode_failures={decode_failures}"
    )
counts = sorted(int(r["value_count"]) for r in rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "archives": len(archives),
    "pngs_seen": len(pngs),
    "samples": len(rows),
    "skipped_tiny": skipped_tiny,
    "skipped_constant": skipped_constant,
    "decode_failures": decode_failures,
    "total_values": sum(counts),
    "total_bytes": total_bytes,
    "min_values": counts[0],
    "median_values": counts[len(counts) // 2],
    "max_values": counts[-1],
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built samples={len(rows)} total_bytes={total_bytes} median_values={stats['median_values']}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
