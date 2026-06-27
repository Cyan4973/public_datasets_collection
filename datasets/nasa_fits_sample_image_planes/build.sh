#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_fits_sample_image_planes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLE_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLE_DIR
export NASA_FITS_MIN_VALUES="${NASA_FITS_MIN_VALUES:-1000}"
export NASA_FITS_MAX_PRIMARY_BYTES="${NASA_FITS_MAX_PRIMARY_BYTES:-1000000000}"
python3 - <<'PY'
from __future__ import annotations

import bz2
import gzip
import json
import math
import os
import re
import shutil
import statistics
import struct
from pathlib import Path
from typing import BinaryIO

DATASET_ID = os.environ["DATASET_ID"]
ROOT = Path(os.environ["REPO_ROOT"])
DATA_ROOT = ROOT / os.environ["DATA_DIR"]
DOWNLOAD_DIR = Path(os.environ["DOWNLOAD_DIR"])
FILTER_DIR = Path(os.environ["FILTER_DIR"])
INDEX_DIR = Path(os.environ["INDEX_DIR"])
SAMPLE_DIR = Path(os.environ["SAMPLE_DIR"])
MIN_VALUES = int(os.environ["NASA_FITS_MIN_VALUES"])
MAX_PRIMARY_BYTES = int(os.environ["NASA_FITS_MAX_PRIMARY_BYTES"])

BITPIX_SPECS = {
    8: ("fits_image_pixels_u8", "uint", 8, 1, ">B", "<B"),
    16: ("fits_image_pixels_i16", "int", 16, 2, ">h", "<h"),
    32: ("fits_image_pixels_i32", "int", 32, 4, ">i", "<i"),
    -32: ("fits_image_pixels_f32", "float", 32, 4, ">f", "<f"),
    -64: ("fits_image_pixels_f64", "float", 64, 8, ">d", "<d"),
}
SCALED_SERIES = ("fits_scaled_image_pixels_f64", "float", 64, 8, "<d")
CUBE_SPECS = {
    -32: ("fits_image_cubes_f32", "float", 32, 4, ">f", "<f"),
}


def open_fits(path: Path) -> BinaryIO:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".gz"):
        return gzip.open(path, "rb")
    if suffixes.endswith(".bz2"):
        return bz2.open(path, "rb")
    return path.open("rb")


def parse_value(raw: str):
    token = raw.split("/", 1)[0].strip()
    if not token:
        return ""
    if token.startswith("'"):
        end = token.find("'", 1)
        return token[1:end].strip() if end != -1 else token.strip("'").strip()
    upper = token.upper()
    if upper == "T":
        return True
    if upper == "F":
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token.replace("D", "E").replace("d", "e"))
    except ValueError:
        return token


def read_header(fh: BinaryIO) -> tuple[dict[str, object], int] | None:
    cards: list[str] = []
    blocks = 0
    while True:
        block = fh.read(2880)
        if not block:
            if not cards:
                return None
            raise ValueError("truncated FITS header")
        if len(block) != 2880:
            raise ValueError("partial FITS header block")
        blocks += 1
        for offset in range(0, 2880, 80):
            card = block[offset : offset + 80].decode("ascii", errors="replace")
            cards.append(card)
            if card.startswith("END"):
                header: dict[str, object] = {}
                for item in cards:
                    key = item[:8].strip()
                    if not key or key in {"COMMENT", "HISTORY", "END"}:
                        continue
                    if item[8:10] == "= ":
                        header[key] = parse_value(item[10:])
                return header, blocks * 2880


def data_payload_size(header: dict[str, object]) -> int:
    bitpix = int(header.get("BITPIX", 0))
    naxis = int(header.get("NAXIS", 0))
    if bitpix == 0 or naxis < 0:
        raise ValueError("invalid BITPIX/NAXIS")
    elements = 1
    for axis in range(1, naxis + 1):
        elements *= int(header.get(f"NAXIS{axis}", 0))
    pcount = int(header.get("PCOUNT", 0) or 0)
    gcount = int(header.get("GCOUNT", 1) or 1)
    bytes_per_value = abs(bitpix) // 8
    return (elements * bytes_per_value + pcount) * gcount


def padded_size(size: int) -> int:
    return ((size + 2879) // 2880) * 2880


def hdu_name(source_id: str, hdu_index: int, header: dict[str, object]) -> str:
    extname = str(header.get("EXTNAME", "") or "").strip()
    if extname:
        return f"{source_id}.hdu{hdu_index:03d}.{re.sub(r'[^A-Za-z0-9_.-]+', '_', extname)}"
    return f"{source_id}.hdu{hdu_index:03d}"


def iter_values(data: bytes, in_fmt: str, element_size: int):
    for offset in range(0, len(data), element_size):
        yield struct.unpack(in_fmt, data[offset : offset + element_size])[0]


def convert_and_write(
    data: bytes,
    out_path: Path,
    in_fmt: str,
    out_fmt: str,
    element_size: int,
    numeric_kind: str,
    blank_value: int | None,
) -> tuple[float, float]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    min_value: float | None = None
    max_value: float | None = None
    with out_path.open("wb") as out:
        for offset in range(0, len(data), element_size * 8192):
            chunk = data[offset : offset + element_size * 8192]
            values = list(iter_values(chunk, in_fmt, element_size))
            if blank_value is not None and any(int(value) == blank_value for value in values):
                raise ValueError("integer BLANK sentinel present")
            if numeric_kind == "float" and any(not math.isfinite(float(value)) for value in values):
                raise ValueError("non-finite floating pixel present")
            for value in values:
                numeric = float(value)
                min_value = numeric if min_value is None else min(min_value, numeric)
                max_value = numeric if max_value is None else max(max_value, numeric)
            out.write(struct.pack("<" + out_fmt[-1] * len(values), *values))
    if min_value is None or max_value is None:
        raise ValueError("empty image plane")
    return min_value, max_value


def convert_scaled_and_write(
    data: bytes,
    out_path: Path,
    in_fmt: str,
    element_size: int,
    bscale: float,
    bzero: float,
) -> tuple[float, float]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    min_value: float | None = None
    max_value: float | None = None
    with out_path.open("wb") as out:
        for offset in range(0, len(data), element_size * 8192):
            chunk = data[offset : offset + element_size * 8192]
            raw_values = list(iter_values(chunk, in_fmt, element_size))
            values = [float(value) * bscale + bzero for value in raw_values]
            if any(not math.isfinite(value) for value in values):
                raise ValueError("non-finite scaled pixel present")
            for value in values:
                min_value = value if min_value is None else min(min_value, value)
                max_value = value if max_value is None else max(max_value, value)
            out.write(struct.pack("<" + "d" * len(values), *values))
    if min_value is None or max_value is None:
        raise ValueError("empty scaled image plane")
    return min_value, max_value


def fits_files() -> list[Path]:
    files = [
        path for path in (DOWNLOAD_DIR / "fits").rglob("*")
        if path.is_file() and path.name != "download_inventory.json"
    ]
    if not files:
        files = [
            path for path in DOWNLOAD_DIR.rglob("*")
            if path.is_file() and path.name != "download_inventory.json"
        ]
    return sorted(files)


shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
shutil.rmtree(INDEX_DIR, ignore_errors=True)
FILTER_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)
all_series_ids = {spec[0] for spec in BITPIX_SPECS.values()}
all_series_ids.update(spec[0] for spec in CUBE_SPECS.values())
all_series_ids.add(SCALED_SERIES[0])
for series_id in sorted(all_series_ids):
    (SAMPLE_DIR / series_id).mkdir(parents=True, exist_ok=True)

source_files = fits_files()
if not source_files:
    raise SystemExit(f"no local FITS files under {DOWNLOAD_DIR}; run download.sh first")

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skip_counts: dict[str, int] = {}
total_bytes = 0

for source_path in source_files:
    source_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_path.name)
    record: dict[str, object] = {
        "source_path": str(source_path.relative_to(DOWNLOAD_DIR)),
        "source_bytes": source_path.stat().st_size,
        "emitted": [],
        "skipped": [],
    }
    try:
        with open_fits(source_path) as fh:
            hdu_index = 0
            while True:
                parsed = read_header(fh)
                if parsed is None:
                    break
                header, _header_size = parsed
                bitpix = int(header.get("BITPIX", 0))
                naxis = int(header.get("NAXIS", 0))
                payload_size = data_payload_size(header)
                data = fh.read(payload_size)
                if len(data) != payload_size:
                    raise ValueError(f"HDU {hdu_index}: truncated data payload")
                padding = padded_size(payload_size) - payload_size
                if padding:
                    skipped = fh.read(padding)
                    if len(skipped) != padding:
                        raise ValueError(f"HDU {hdu_index}: truncated data padding")

                hdu_index += 1
                reason_prefix = f"hdu{hdu_index:03d}"
                xtension = str(header.get("XTENSION", "") or "").strip().upper()
                bscale = float(header.get("BSCALE", 1) or 1)
                bzero = float(header.get("BZERO", 0) or 0)
                width = int(header.get("NAXIS1", 0) or 0)
                height = int(header.get("NAXIS2", 0) or 0)
                depth = int(header.get("NAXIS3", 0) or 0) if naxis >= 3 else 0

                if payload_size == 0:
                    reason = "empty_hdu"
                elif xtension and xtension != "IMAGE":
                    reason = f"non_image_extension_{xtension.lower()}"
                elif bitpix not in set(BITPIX_SPECS) | set(CUBE_SPECS):
                    reason = f"unsupported_bitpix_{bitpix}"
                elif "BLANK" in header:
                    reason = "blank_missing_value_sentinel"
                elif naxis == 2 and (width <= 0 or height <= 0):
                    reason = "nonpositive_shape"
                elif naxis == 3 and (width <= 0 or height <= 0 or depth <= 0):
                    reason = "nonpositive_shape"
                elif naxis not in {2, 3}:
                    reason = f"naxis_{naxis}_not_image_plane_or_cube"
                elif naxis == 3 and (bscale != 1.0 or bzero != 0.0):
                    reason = "scaled_cube"
                elif naxis == 3 and bitpix not in CUBE_SPECS:
                    reason = f"unsupported_cube_bitpix_{bitpix}"
                else:
                    reason = ""
                if reason:
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    record["skipped"].append({"hdu_index": hdu_index, "reason": f"{reason_prefix}:{reason}"})
                    continue

                scaled_plane = naxis == 2 and (bscale != 1.0 or bzero != 0.0)
                if scaled_plane:
                    if bitpix not in {8, 16, 32}:
                        reason = f"unsupported_scaled_bitpix_{bitpix}"
                        skip_counts[reason] = skip_counts.get(reason, 0) + 1
                        record["skipped"].append({"hdu_index": hdu_index, "reason": f"{reason_prefix}:{reason}"})
                        continue
                    _raw_series, _raw_kind, _raw_width, element_size, in_fmt, _raw_out_fmt = BITPIX_SPECS[bitpix]
                    series_id, numeric_kind, bit_width, sample_element_size, out_fmt = SCALED_SERIES
                    value_count = width * height
                    sample_geometry = "2d_astronomical_image_plane"
                    sample_rank = 2
                    sample_shape = [height, width]
                    sample_axes = ["y", "x"]
                    sample_format = "raw homogeneous FITS scaled physical image plane"
                elif naxis == 3:
                    series_id, numeric_kind, bit_width, element_size, in_fmt, out_fmt = CUBE_SPECS[bitpix]
                    sample_element_size = element_size
                    value_count = width * height * depth
                    sample_geometry = "3d_astronomical_image_cube"
                    sample_rank = 3
                    sample_shape = [depth, height, width]
                    sample_axes = ["plane", "y", "x"]
                    sample_format = "raw homogeneous FITS image cube"
                else:
                    series_id, numeric_kind, bit_width, element_size, in_fmt, out_fmt = BITPIX_SPECS[bitpix]
                    sample_element_size = element_size
                    value_count = width * height
                    sample_geometry = "2d_astronomical_image_plane"
                    sample_rank = 2
                    sample_shape = [height, width]
                    sample_axes = ["y", "x"]
                    sample_format = "raw homogeneous FITS image plane"

                if value_count < MIN_VALUES:
                    reason = "below_min_values"
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    record["skipped"].append({"hdu_index": hdu_index, "reason": f"{reason_prefix}:{reason}", "value_count": value_count})
                    continue
                sample_name = hdu_name(source_id, hdu_index, header)
                rel_sample = Path("samples") / DATASET_ID / series_id / f"{sample_name}.bin"
                try:
                    if scaled_plane:
                        min_value, max_value = convert_scaled_and_write(
                            data,
                            DATA_ROOT / rel_sample,
                            in_fmt,
                            element_size,
                            bscale,
                            bzero,
                        )
                    else:
                        min_value, max_value = convert_and_write(
                            data,
                            DATA_ROOT / rel_sample,
                            in_fmt,
                            out_fmt,
                            element_size,
                            numeric_kind,
                            int(header["BLANK"]) if "BLANK" in header else None,
                        )
                except ValueError as exc:
                    reason = str(exc).replace(" ", "_")
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    record["skipped"].append({"hdu_index": hdu_index, "reason": f"{reason_prefix}:{reason}"})
                    continue
                if min_value == max_value:
                    reason = "constant"
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    (DATA_ROOT / rel_sample).unlink(missing_ok=True)
                    record["skipped"].append({"hdu_index": hdu_index, "reason": f"{reason_prefix}:{reason}"})
                    continue
                sample_size_bytes = value_count * sample_element_size
                if total_bytes + sample_size_bytes > MAX_PRIMARY_BYTES:
                    raise SystemExit(f"primary bytes exceed cap: {total_bytes + sample_size_bytes}")
                total_bytes += sample_size_bytes
                row = {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "role": "primary",
                    "sample_path": str(rel_sample),
                    "source_file": str(source_path.relative_to(DOWNLOAD_DIR)),
                    "hdu_index": hdu_index,
                    "hdu_name": str(header.get("EXTNAME", "") or ""),
                    "instrument": str(header.get("INSTRUME", "") or ""),
                    "telescope": str(header.get("TELESCOP", "") or ""),
                    "bitpix": bitpix,
                    "numeric_kind": numeric_kind,
                    "bit_width": bit_width,
                    "endianness": "little",
                    "element_size_bytes": sample_element_size,
                    "sample_size_bytes": sample_size_bytes,
                    "value_count": value_count,
                    "sample_format": sample_format,
                    "sample_geometry": sample_geometry,
                    "sample_rank": sample_rank,
                    "sample_shape": sample_shape,
                    "sample_axes": sample_axes,
                    "min": min_value,
                    "max": max_value,
                }
                index_rows.append(row)
                record["emitted"].append(
                    {
                        "hdu_index": hdu_index,
                        "series_id": series_id,
                        "shape": sample_shape,
                        "value_count": value_count,
                        "sample_size_bytes": sample_size_bytes,
                    }
                )
    except Exception as exc:
        reason = f"file_parse_error:{type(exc).__name__}"
        skip_counts[reason] = skip_counts.get(reason, 0) + 1
        record["skipped"].append({"reason": reason, "detail": str(exc)})
    records.append(record)

counts = [int(row["value_count"]) for row in index_rows]
byte_counts = [int(row["sample_size_bytes"]) for row in index_rows]
if len(index_rows) < 2:
    raise SystemExit(f"only {len(index_rows)} primary samples emitted; skips={skip_counts}")
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
median_values = statistics.median(counts)
if median_values < 1_000:
    raise SystemExit(f"median sample values below floor: {median_values}")

with (INDEX_DIR / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

series_stats: dict[str, dict[str, int]] = {}
for row in index_rows:
    stats = series_stats.setdefault(str(row["series_id"]), {"sample_count": 0, "total_size_bytes": 0, "total_values": 0})
    stats["sample_count"] += 1
    stats["total_size_bytes"] += int(row["sample_size_bytes"])
    stats["total_values"] += int(row["value_count"])

stats = {
    "dataset_id": DATASET_ID,
    "source_file_count": len(source_files),
    "primary_sample_count": len(index_rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": sum(byte_counts),
    "median_primary_values": median_values,
    "min_values_per_sample": MIN_VALUES,
    "series": series_stats,
    "skip_counts": skip_counts,
    "records": records,
}
(FILTER_DIR / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"built samples={len(index_rows)} bytes={sum(byte_counts)} "
    f"median_values={int(median_values)} series={series_stats} skips={skip_counts}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
