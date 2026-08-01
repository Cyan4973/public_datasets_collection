#!/usr/bin/env python3
"""Extract and source-value-verify native float32 NIfTI-1 MRI volumes."""

from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys


DATASET_ID = "openneuro_ds000030_t1w_mri_f32"
SERIES_ID = "openneuro_t1w_mri_f32"
EXPECTED_SAMPLES = 20
EXPECTED_DATATYPE = 16
EXPECTED_BITPIX = 32
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


@dataclass(frozen=True)
class Volume:
    source_name: str
    source_bytes: int
    source_endianness: str
    shape: tuple[int, int, int]
    value_count: int
    vox_offset: int
    payload_le: bytes
    minimum: float
    maximum: float


def parse_volume(path: Path) -> Volume:
    try:
        data = gzip.decompress(path.read_bytes())
    except (OSError, gzip.BadGzipFile) as exc:
        raise ValueError(f"{path.name}: invalid gzip stream") from exc
    if len(data) < 352:
        raise ValueError(f"{path.name}: decompressed NIfTI is too small")
    if struct.unpack_from("<I", data, 0)[0] == 348:
        endian = "<"
        source_endianness = "little"
    elif struct.unpack_from(">I", data, 0)[0] == 348:
        endian = ">"
        source_endianness = "big"
    else:
        raise ValueError(f"{path.name}: invalid NIfTI sizeof_hdr")
    if data[344:348] != b"n+1\0":
        raise ValueError(f"{path.name}: expected NIfTI-1 single-file magic")
    dims = struct.unpack_from(endian + "8h", data, 40)
    rank = int(dims[0])
    if rank != 3:
        raise ValueError(f"{path.name}: expected rank 3, found {rank}")
    shape = tuple(int(value) for value in dims[1:4])
    if any(value <= 0 for value in shape):
        raise ValueError(f"{path.name}: invalid shape {shape}")
    datatype = struct.unpack_from(endian + "h", data, 70)[0]
    bitpix = struct.unpack_from(endian + "h", data, 72)[0]
    if datatype != EXPECTED_DATATYPE or bitpix != EXPECTED_BITPIX:
        raise ValueError(
            f"{path.name}: expected datatype=16 bitpix=32, "
            f"found datatype={datatype} bitpix={bitpix}"
        )
    vox_offset_float = struct.unpack_from(endian + "f", data, 108)[0]
    if not math.isfinite(vox_offset_float) or not vox_offset_float.is_integer():
        raise ValueError(f"{path.name}: invalid vox_offset {vox_offset_float}")
    vox_offset = int(vox_offset_float)
    if vox_offset < 352:
        raise ValueError(f"{path.name}: vox_offset before payload boundary")
    slope = struct.unpack_from(endian + "f", data, 112)[0]
    intercept = struct.unpack_from(endian + "f", data, 116)[0]
    if slope not in (0.0, 1.0) or intercept != 0.0:
        raise ValueError(
            f"{path.name}: nonidentity scaling slope={slope} intercept={intercept}"
        )
    value_count = math.prod(shape)
    expected_bytes = value_count * 4
    payload = data[vox_offset : vox_offset + expected_bytes]
    if len(payload) != expected_bytes:
        raise ValueError(
            f"{path.name}: truncated payload {len(payload)} != {expected_bytes}"
        )
    values = array("f")
    values.frombytes(payload)
    source_is_native = (source_endianness == "little") == (sys.byteorder == "little")
    if not source_is_native:
        values.byteswap()
    iterator = iter(values)
    first = next(iterator)
    if not math.isfinite(first):
        raise ValueError(f"{path.name}: non-finite voxel value")
    minimum = first
    maximum = first
    for value in iterator:
        if not math.isfinite(value):
            raise ValueError(f"{path.name}: non-finite voxel value")
        minimum = min(minimum, value)
        maximum = max(maximum, value)
    if minimum == maximum:
        raise ValueError(f"{path.name}: constant voxel volume")
    if sys.byteorder != "little":
        values.byteswap()
    payload_le = values.tobytes()
    return Volume(
        source_name=path.name,
        source_bytes=path.stat().st_size,
        source_endianness=source_endianness,
        shape=shape,
        value_count=value_count,
        vox_offset=vox_offset,
        payload_le=payload_le,
        minimum=minimum,
        maximum=maximum,
    )


def source_paths(download_dir: Path) -> list[Path]:
    paths = sorted((download_dir / "volumes").glob("*_T1w.nii.gz"))
    if len(paths) != EXPECTED_SAMPLES:
        raise ValueError(f"expected {EXPECTED_SAMPLES} source volumes, found {len(paths)}")
    return paths


def build(download_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for source in source_paths(download_dir):
        volume = parse_volume(source)
        shape_text = "x".join(str(value) for value in volume.shape)
        output = output_dir / f"{source.name.removesuffix('.nii.gz')}_f32_{shape_text}.bin"
        output.write_bytes(volume.payload_le)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(volume.payload_le),
            "value_count": volume.value_count,
            "sample_format": "raw homogeneous float32 MRI voxel array",
            "sample_geometry": "3d_mri_volume",
            "sample_rank": 3,
            "sample_shape": list(volume.shape),
            "sample_axes": ["i", "j", "k"],
            "natural_record_kind": "t1w_nifti_volume",
            "source_sample": volume.source_name,
            "source_format": "NIfTI-1 single-file gzip",
            "source_field": "3D image voxel payload",
            "source_datatype_code": EXPECTED_DATATYPE,
            "source_bitpix": EXPECTED_BITPIX,
            "source_endianness": volume.source_endianness,
            "source_vox_offset": volume.vox_offset,
            "min": volume.minimum,
            "max": volume.maximum,
        }
        rows.append(row)
        records.append(
            {
                "source_name": volume.source_name,
                "source_bytes": volume.source_bytes,
                "shape": list(volume.shape),
                "value_count": volume.value_count,
                "sample_bytes": len(volume.payload_le),
                "min": volume.minimum,
                "max": volume.maximum,
            }
        )

    counts = [int(row["value_count"]) for row in rows]
    total_values = sum(counts)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median={median_values:g}"
    )


def verify(download_dir: Path, index_path: Path, data_root: Path) -> None:
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    paths = source_paths(download_dir)
    if [row.get("source_sample") for row in rows] != [path.name for path in paths]:
        raise ValueError("index source set/order mismatch")
    counts = []
    total_bytes = 0
    for row, source in zip(rows, paths, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise ValueError("index identity mismatch")
        if row.get("role") != "primary":
            raise ValueError("indexed sample is not primary")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 32:
            raise ValueError("indexed sample is not float32")
        volume = parse_volume(source)
        sample = data_root / row["sample_path"]
        actual = sample.read_bytes()
        if actual != volume.payload_le:
            raise ValueError(f"{sample}: source-value byte mismatch")
        if row.get("sample_shape") != list(volume.shape):
            raise ValueError(f"{sample}: shape mismatch")
        if int(row["value_count"]) != volume.value_count:
            raise ValueError(f"{sample}: value-count mismatch")
        if float(row["min"]) != volume.minimum or float(row["max"]) != volume.maximum:
            raise ValueError(f"{sample}: range mismatch")
        counts.append(volume.value_count)
        total_bytes += len(actual)
    median_values = statistics.median(counts)
    if sum(counts) < MIN_TOTAL_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} median={median_values:g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--download-dir", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--download-dir", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args.download_dir, args.samples_dir, args.index, args.stats)
    else:
        verify(args.download_dir, args.index, args.data_root)


if __name__ == "__main__":
    main()
