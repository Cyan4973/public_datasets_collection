#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_reflectance_cogs_u16"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import struct
import subprocess
import zlib
from array import array
from itertools import accumulate
from pathlib import Path

DATASET_ID = "sentinel2_l2a_reflectance_cogs_u16"
SERIES_ID = "sentinel2_l2a_reflectance_pixels_u16"
MAX_PRIMARY_BYTES = int(os.environ.get("SENTINEL2_MAX_PRIMARY_BYTES", "1000000000"))
MIN_PRIMARY_BYTES = int(os.environ.get("SENTINEL2_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_PRIMARY_VALUES = int(os.environ.get("SENTINEL2_MIN_PRIMARY_VALUES", "10000"))
MIN_MEDIAN_VALUES = int(os.environ.get("SENTINEL2_MIN_MEDIAN_VALUES", "1000"))
MIN_SAMPLE_COUNT = int(os.environ.get("SENTINEL2_MIN_SAMPLE_COUNT", "12"))
# Samples are the source COG's own native internal tiles (blue 1024, rededge 512,
# coastal 256). Full-scene rasters are far too large for training samples, so each
# scene contributes many native tiles instead. Keep only full interior tiles that
# are non-constant and mostly in-swath (Sentinel-2 MGRS tiles carry large nodata
# borders stored as zero).
MIN_NONZERO_FRACTION = float(os.environ.get("SENTINEL2_MIN_NONZERO_FRACTION", "0.98"))
MAX_TILES_PER_BAND = int(os.environ.get("SENTINEL2_MAX_TILES_PER_BAND", "0"))  # 0 = unlimited, per (scene, band)
ZSTD_BIN = os.environ.get("ZSTD_BIN", "zstd")

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def tiff_values(data: bytes, endian: str, bigtiff: bool, field_type: int, count: int, raw_value: int) -> list[int]:
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8}
    type_codes = {1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i", 11: "f", 12: "d", 13: "I", 16: "Q", 17: "q", 18: "Q"}
    size = type_sizes.get(field_type)
    if size is None:
        raise ValueError(f"unsupported TIFF field type: {field_type}")
    inline_limit = 8 if bigtiff else 4
    byte_count = count * size
    if byte_count <= inline_limit:
        value_bytes = int(raw_value).to_bytes(inline_limit, byteorder="little" if endian == "<" else "big")[:byte_count]
    else:
        value_bytes = data[raw_value : raw_value + byte_count]
    if len(value_bytes) != byte_count:
        raise ValueError("truncated TIFF tag value")
    if field_type == 2:
        return [0]
    if field_type in {5, 10}:
        code = "I" if field_type == 5 else "i"
        vals = struct.unpack(endian + code * (count * 2), value_bytes)
        return [vals[i] for i in range(0, len(vals), 2)]
    code = type_codes.get(field_type)
    if code is None:
        raise ValueError(f"unsupported numeric TIFF field type: {field_type}")
    return list(struct.unpack(endian + code * count, value_bytes))


def parse_tiff(path: Path) -> dict:
    data = path.read_bytes()
    if data[:2] == b"II":
        endian, endianness = "<", "little"
    elif data[:2] == b"MM":
        endian, endianness = ">", "big"
    else:
        raise ValueError(f"{path.name}: not a TIFF file")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic == 42:
        bigtiff = False
        ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
        entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
        base, entry_size = ifd_offset + 2, 12
        tags: dict[int, tuple[int, int, int]] = {}
        for index in range(entry_count):
            tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", data, base + index * entry_size)
            tags[tag] = (field_type, count, raw_value)
    elif magic == 43:
        bigtiff = True
        bytesize, zero = struct.unpack_from(endian + "HH", data, 4)
        if bytesize != 8 or zero != 0:
            raise ValueError(f"{path.name}: unsupported BigTIFF header")
        ifd_offset = struct.unpack_from(endian + "Q", data, 8)[0]
        entry_count = struct.unpack_from(endian + "Q", data, ifd_offset)[0]
        base, entry_size = ifd_offset + 8, 20
        tags = {}
        for index in range(entry_count):
            tag, field_type, count, raw_value = struct.unpack_from(endian + "HHQQ", data, base + index * entry_size)
            tags[tag] = (field_type, count, raw_value)
    else:
        raise ValueError(f"{path.name}: unsupported TIFF magic {magic}")

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        field_type, count, raw_value = tags[tag]
        return tiff_values(data, endian, bigtiff, field_type, count, raw_value)

    width_vals, height_vals, bits_vals = values(256), values(257), values(258)
    if not width_vals or not height_vals or not bits_vals:
        raise ValueError(f"{path.name}: missing required TIFF image tags")
    width, height, bits = int(width_vals[0]), int(height_vals[0]), int(bits_vals[0])
    compression = int((values(259) or [1])[0])
    samples_per_pixel = int((values(277) or [1])[0])
    predictor = int((values(317) or [1])[0])
    sample_format = int((values(339) or [1])[0])
    if bits != 16 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: not single-band uint16 bits={bits} samples={samples_per_pixel} sample_format={sample_format}"
        )
    # 1=none, 8/32946=Deflate (Element84 COG default), 50000=Zstandard.
    if compression not in {1, 8, 32946, 50000}:
        raise ValueError(f"{path.name}: unsupported TIFF compression {compression}")
    if predictor not in {1, 2}:
        raise ValueError(f"{path.name}: unsupported TIFF predictor {predictor}")
    if not (values(324) and values(325)):
        raise ValueError(f"{path.name}: expected a tiled COG (no tile offset/count tables)")
    tile_width = int(values(322)[0])
    tile_length = int(values(323)[0])
    offsets = [int(v) for v in values(324)]
    counts = [int(v) for v in values(325)]
    if not offsets or not counts or len(offsets) != len(counts):
        raise ValueError(f"{path.name}: invalid tile offset/count table")
    return {
        "data": data,
        "endian": endian,
        "endianness": endianness,
        "width": width,
        "height": height,
        "compression": compression,
        "predictor": predictor,
        "tile_width": tile_width,
        "tile_length": tile_length,
        "offsets": offsets,
        "counts": counts,
    }


def decompress_block(block: bytes, compression: int) -> bytes:
    if compression == 1:
        return block
    if compression in {8, 32946}:
        try:
            return zlib.decompress(block)
        except zlib.error:
            return zlib.decompress(block, -15)
    if compression == 50000:
        proc = subprocess.run([ZSTD_BIN, "-d", "-c", "-q"], input=block, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise ValueError(f"zstd decode failed (rc={proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:200]}")
        return proc.stdout
    raise ValueError(f"unsupported compression {compression}")


def undo_predictor(values_u16: array, endian: str, width: int, height: int, predictor: int) -> None:
    """Reverse TIFF horizontal differencing (predictor=2) in place. Cumulative
    row sums mod 65536 match the per-pixel reference exactly but run in C."""
    if predictor != 2:
        return
    swap = endian == ">"
    if swap:
        values_u16.byteswap()
    for y in range(height):
        start = y * width
        values_u16[start : start + width] = array("H", (v & 0xFFFF for v in accumulate(values_u16[start : start + width])))
    if swap:
        values_u16.byteswap()


def iter_native_tiles(info: dict):
    """Yield (tile_x, tile_y, payload, is_nodata) for full interior native tiles.
    All-zero (nodata) tiles are detected before the predictor undo and returned
    with payload=None so callers can skip them cheaply."""
    width, height = int(info["width"]), int(info["height"])
    tile_width, tile_length = int(info["tile_width"]), int(info["tile_length"])
    tile_bytes = tile_width * tile_length * 2
    tiles_across = (width + tile_width - 1) // tile_width
    for index, (offset, count) in enumerate(zip(info["offsets"], info["counts"])):
        tile_x = (index % tiles_across) * tile_width
        tile_y = (index // tiles_across) * tile_length
        if tile_x + tile_width > width or tile_y + tile_length > height:
            continue  # interior full tiles only
        raw = decompress_block(info["data"][offset : offset + count], int(info["compression"]))
        if len(raw) != tile_bytes:
            raise ValueError(f"decoded tile has unexpected size: got={len(raw)} expected={tile_bytes}")
        values_u16 = array("H")
        values_u16.frombytes(raw)
        if values_u16.count(0) == len(values_u16):
            yield tile_x, tile_y, None, True  # nodata border tile, stays zero after undo
            continue
        undo_predictor(values_u16, str(info["endian"]), tile_width, tile_length, int(info["predictor"]))
        yield tile_x, tile_y, values_u16.tobytes(), False


def tile_quality(payload: bytes) -> tuple[bool, float]:
    """Return (prefix_nonconstant, nonzero_fraction); the prefix test mirrors
    verify.sh's leading-window check. Endianness-independent."""
    values_u16 = array("H")
    values_u16.frombytes(payload)
    total = len(values_u16)
    nonzero_fraction = (total - values_u16.count(0)) / total if total else 0.0
    prefix = values_u16[: min(total, 200_000)]
    prefix_nonconstant = bool(prefix) and prefix.count(prefix[0]) != len(prefix)
    return prefix_nonconstant, nonzero_fraction


def read_plan() -> list[dict]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing download plan: {plan}")
    rows = []
    for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        local_name, url, scene_id, band_label, asset_key, search_label, datetime, cloud_cover = line.split("\t")
        rows.append(
            {
                "local_name": local_name,
                "url": url,
                "scene_id": scene_id,
                "band_label": band_label,
                "asset_key": asset_key,
                "search_label": search_label,
                "datetime": datetime,
                "cloud_cover": cloud_cover,
            }
        )
    return rows


reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
sample_index = 0
dropped_nodata = 0
dropped_constant = 0
dropped_sparse = 0
dropped_over_cap = 0
capped = False

for plan_row in read_plan():
    if capped:
        break
    source = download_dir / plan_row["local_name"]
    if not source.exists():
        raise SystemExit(f"missing download: {source}")
    info = parse_tiff(source)
    scene_kept = 0
    scene_scanned = 0
    for tile_x, tile_y, payload, is_nodata in iter_native_tiles(info):
        scene_scanned += 1
        if is_nodata:
            dropped_nodata += 1
            continue
        prefix_nonconstant, nonzero_fraction = tile_quality(payload)
        if not prefix_nonconstant:
            dropped_constant += 1
            continue
        if nonzero_fraction < MIN_NONZERO_FRACTION:
            dropped_sparse += 1
            continue
        if total_bytes + len(payload) > MAX_PRIMARY_BYTES:
            dropped_over_cap += 1
            capped = True
            break
        sample_index += 1
        scene_kept += 1
        total_bytes += len(payload)
        out = out_dir / f"{sample_index:04d}_{source.stem}_x{tile_x}_y{tile_y}.bin"
        out.write_bytes(payload)
        shape = [int(info["tile_length"]), int(info["tile_width"])]
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": rel(out),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": info["endianness"],
            "element_size_bytes": 2,
            "sample_size_bytes": len(payload),
            "value_count": len(payload) // 2,
            "sample_geometry": "2d_raster",
            "sample_rank": 2,
            "sample_shape": shape,
            "sample_axes": ["y", "x"],
            "natural_record_kind": "sentinel2_l2a_reflectance_tile",
            "source_path": source.as_posix(),
            "scene_id": plan_row["scene_id"],
            "band_label": plan_row["band_label"],
            "asset_key": plan_row["asset_key"],
            "datetime": plan_row["datetime"],
            "cloud_cover": plan_row["cloud_cover"],
            "tile_x": tile_x,
            "tile_y": tile_y,
            "nonzero_fraction": round(nonzero_fraction, 6),
            "tiff_layout": "tiled",
            "tiff_compression": info["compression"],
            "tiff_predictor": info["predictor"],
        }
        rows.append(row)
        records.append(
            {
                **plan_row,
                "source_file": source.name,
                "source_bytes": source.stat().st_size,
                "sample_path": row["sample_path"],
                "tile_x": tile_x,
                "tile_y": tile_y,
                "sample_bytes": len(payload),
                "value_count": len(payload) // 2,
                "shape": shape,
                "endianness": info["endianness"],
                "nonzero_fraction": round(nonzero_fraction, 6),
                "tiff_compression": info["compression"],
                "tiff_predictor": info["predictor"],
            }
        )
        if MAX_TILES_PER_BAND and scene_kept >= MAX_TILES_PER_BAND:
            break
    print(
        f"scene={plan_row['scene_id']} band={plan_row['band_label']} tiles_scanned={scene_scanned} kept={scene_kept} "
        f"tile={info['tile_width']}x{info['tile_length']} compression={info['compression']} predictor={info['predictor']}"
    )

if dropped_nodata or dropped_constant or dropped_sparse or dropped_over_cap:
    print(
        f"dropped tiles: nodata={dropped_nodata} constant={dropped_constant} "
        f"sparse(nonzero<{MIN_NONZERO_FRACTION})={dropped_sparse} over_cap={dropped_over_cap}"
        f"{' (primary cap reached; remaining bands skipped)' if capped else ''}"
    )

sizes = [int(row["sample_size_bytes"]) for row in rows]
values = [int(row["value_count"]) for row in rows]
if not rows:
    raise RuntimeError("no reflectance tiles survived filtering")
if sum(sizes) < MIN_PRIMARY_BYTES or sum(values) < MIN_PRIMARY_VALUES:
    raise RuntimeError("primary payload below aggregate floor")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise RuntimeError("median sample below floor")
if len(rows) < MIN_SAMPLE_COUNT:
    raise RuntimeError(f"expected at least {MIN_SAMPLE_COUNT} reflectance tiles, built {len(rows)}")

stats = {
    "dataset_id": DATASET_ID,
    "record_count": len(records),
    "min_nonzero_fraction": MIN_NONZERO_FRACTION,
    "total_primary_bytes": sum(sizes),
    "total_primary_values": sum(values),
    "scene_count": len({r["scene_id"] for r in records}),
    "band_count": len({r["band_label"] for r in records}),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built_samples={len(rows)} scenes={len({r['scene_id'] for r in records})} "
    f"bands={len({r['band_label'] for r in records})} primary_values={sum(values)} primary_bytes={sum(sizes)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
