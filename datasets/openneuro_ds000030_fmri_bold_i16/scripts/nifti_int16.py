#!/usr/bin/env python3
"""Build and independently verify native-int16 OpenNeuro BOLD runs."""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import csv
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys


DATASET_ID = "openneuro_ds000030_fmri_bold_i16"
SERIES_ID = "openneuro_fmri_bold_i16"
EXPECTED_SAMPLES = 10
EXPECTED_SUBJECTS = 10
EXPECTED_TASKS = {"bart", "bht", "pamenc", "pamret", "rest", "scap", "stopsignal", "taskswitch"}
EXPECTED_COMPRESSED_BYTES = 309_475_689
EXPECTED_VALUES = 257_499_136
EXPECTED_BYTES = 514_998_272
EXPECTED_SPATIAL_SHAPE = (64, 64, 34)
EXPECTED_PIXDIM = (3.0, 3.0, 4.0, 2.0)
EXPECTED_DATATYPE = 4
EXPECTED_BITPIX = 16
EXPECTED_VOX_OFFSET = 352


@dataclass(frozen=True)
class SourceSpec:
    key: str
    size_bytes: int
    md5: str
    sha256: str
    payload_sha256: str
    subject: str
    task: str
    shape: tuple[int, int, int, int]
    value_count: int
    decoded_bytes: int

    @property
    def filename(self) -> str:
        return Path(self.key).name


@dataclass(frozen=True)
class Volume:
    shape: tuple[int, int, int, int]
    pixdim: tuple[float, float, float, float]
    payload: bytes
    minimum: int
    maximum: int
    unique_values: int
    zero_count: int
    frame_count: int
    payload_sha256: str


def hash_file(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def load_selection(recipe_dir: Path) -> list[SourceSpec]:
    specs: list[SourceSpec] = []
    with (recipe_dir / "selection.tsv").open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            shape = tuple(int(value) for value in row["shape"].split("x"))
            if len(shape) != 4:
                raise ValueError(f"invalid selected shape: {row['shape']}")
            specs.append(
                SourceSpec(
                    key=row["key"],
                    size_bytes=int(row["size_bytes"]),
                    md5=row["md5"],
                    sha256=row["sha256"],
                    payload_sha256=row["payload_sha256"],
                    subject=row["subject"],
                    task=row["task"],
                    shape=shape,  # type: ignore[arg-type]
                    value_count=int(row["value_count"]),
                    decoded_bytes=int(row["decoded_bytes"]),
                )
            )
    if len(specs) != EXPECTED_SAMPLES:
        raise ValueError(f"selection count mismatch: {len(specs)}")
    if len({spec.subject for spec in specs}) != EXPECTED_SUBJECTS:
        raise ValueError("selection does not contain ten distinct subjects")
    if {spec.task for spec in specs} != EXPECTED_TASKS:
        raise ValueError("selection does not cover the exact task set")
    if len({spec.key for spec in specs}) != len(specs) or len({spec.filename for spec in specs}) != len(specs):
        raise ValueError("duplicate selection key or basename")
    if sum(spec.size_bytes for spec in specs) != EXPECTED_COMPRESSED_BYTES:
        raise ValueError("selection compressed-byte total mismatch")
    if sum(spec.value_count for spec in specs) != EXPECTED_VALUES:
        raise ValueError("selection value total mismatch")
    if sum(spec.decoded_bytes for spec in specs) != EXPECTED_BYTES:
        raise ValueError("selection decoded-byte total mismatch")
    for spec in specs:
        if spec.shape[:3] != EXPECTED_SPATIAL_SHAPE:
            raise ValueError(f"unexpected spatial shape: {spec.filename}")
        if math.prod(spec.shape) != spec.value_count or spec.value_count * 2 != spec.decoded_bytes:
            raise ValueError(f"selection geometry mismatch: {spec.filename}")
    return specs


def int16_values(payload: bytes) -> array[int]:
    if len(payload) % 2:
        raise ValueError("odd-length int16 payload")
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def validate_source(path: Path, spec: SourceSpec) -> None:
    if not path.is_file() or path.stat().st_size != spec.size_bytes:
        raise ValueError(f"missing or wrong-sized source: {path}")
    md5, sha256 = hash_file(path)
    if md5 != spec.md5 or sha256 != spec.sha256:
        raise ValueError(f"source digest mismatch: {path.name}")


def parse_volume(path: Path, spec: SourceSpec) -> Volume:
    validate_source(path, spec)
    try:
        raw = gzip.decompress(path.read_bytes())
    except (OSError, gzip.BadGzipFile) as error:
        raise ValueError(f"invalid gzip stream: {path.name}") from error
    if len(raw) < EXPECTED_VOX_OFFSET or struct.unpack_from("<I", raw, 0)[0] != 348:
        raise ValueError(f"not a little-endian NIfTI-1 file: {path.name}")
    if raw[344:348] != b"n+1\0":
        raise ValueError(f"not a NIfTI-1 single-file image: {path.name}")
    dims = struct.unpack_from("<8h", raw, 40)
    if dims[0] != 4:
        raise ValueError(f"expected rank 4: {path.name}")
    shape = tuple(int(value) for value in dims[1:5])
    if shape != spec.shape:
        raise ValueError(f"shape mismatch: {path.name} {shape} != {spec.shape}")
    datatype, bitpix = struct.unpack_from("<2h", raw, 70)
    if datatype != EXPECTED_DATATYPE or bitpix != EXPECTED_BITPIX:
        raise ValueError(f"non-int16 NIfTI representation: {path.name}")
    pixdim_all = struct.unpack_from("<8f", raw, 76)
    pixdim = tuple(float(value) for value in pixdim_all[1:5])
    if pixdim != EXPECTED_PIXDIM:
        raise ValueError(f"unexpected voxel/time spacing: {path.name} {pixdim}")
    vox_offset = struct.unpack_from("<f", raw, 108)[0]
    slope, intercept = struct.unpack_from("<2f", raw, 112)
    if vox_offset != float(EXPECTED_VOX_OFFSET) or slope != 1.0 or intercept != 0.0:
        raise ValueError(
            f"unexpected offset/scaling: {path.name} offset={vox_offset} slope={slope} intercept={intercept}"
        )
    if raw[348:352] != b"\0\0\0\0":
        raise ValueError(f"unexpected NIfTI extension flag: {path.name}")
    expected_raw_size = EXPECTED_VOX_OFFSET + spec.decoded_bytes
    if len(raw) != expected_raw_size:
        raise ValueError(f"truncated or trailing NIfTI bytes: {path.name} {len(raw)} != {expected_raw_size}")
    payload = raw[EXPECTED_VOX_OFFSET:]
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    if payload_sha256 != spec.payload_sha256:
        raise ValueError(f"decoded payload digest mismatch: {path.name}")

    values = int16_values(payload)
    minimum, maximum = min(values), max(values)
    if minimum == maximum:
        raise ValueError(f"constant BOLD run: {path.name}")
    unique_values = len(set(values))
    zero_count = values.count(0)
    spatial_values = math.prod(shape[:3])
    frame_hashes: set[bytes] = set()
    for frame_index in range(shape[3]):
        start = frame_index * spatial_values * 2
        frame_payload = payload[start : start + spatial_values * 2]
        frame = int16_values(frame_payload)
        if min(frame) == max(frame):
            raise ValueError(f"constant BOLD frame: {path.name} frame={frame_index}")
        frame_hash = hashlib.sha256(frame_payload).digest()
        if frame_hash in frame_hashes:
            raise ValueError(f"duplicate BOLD frame: {path.name} frame={frame_index}")
        frame_hashes.add(frame_hash)
    return Volume(
        shape=shape,  # type: ignore[arg-type]
        pixdim=pixdim,  # type: ignore[arg-type]
        payload=payload,
        minimum=int(minimum),
        maximum=int(maximum),
        unique_values=unique_values,
        zero_count=zero_count,
        frame_count=shape[3],
        payload_sha256=payload_sha256,
    )


def validate_source_set(download_dir: Path, specs: list[SourceSpec]) -> None:
    volume_dir = download_dir / "volumes"
    actual = {path.name for path in volume_dir.glob("*.nii.gz") if path.is_file()}
    expected = {spec.filename for spec in specs}
    if actual != expected:
        raise ValueError(f"source file set mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    description = json.loads((download_dir / "dataset_description.json").read_text())
    if description.get("License") != "CC0" or description.get("DatasetDOI") != "10.18112/openneuro.ds000030.v1.0.0":
        raise ValueError("dataset description license/DOI mismatch")


def build(args: argparse.Namespace) -> None:
    specs = load_selection(args.recipe_dir)
    validate_source_set(args.download_dir, specs)
    output_dir = args.samples_root / SERIES_ID
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    payload_hashes: set[str] = set()
    for spec in specs:
        source = args.download_dir / "volumes" / spec.filename
        volume = parse_volume(source, spec)
        if volume.payload_sha256 in payload_hashes:
            raise ValueError(f"duplicate complete BOLD payload: {spec.filename}")
        payload_hashes.add(volume.payload_sha256)
        output = output_dir / f"{spec.filename.removesuffix('.nii.gz')}.i16le.bin"
        output.write_bytes(volume.payload)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(volume.payload),
            "value_count": spec.value_count,
            "sample_format": "raw homogeneous little-endian signed-int16 4D BOLD voxel array",
            "sample_geometry": "variable_time_4d_fmri_bold_run",
            "sample_rank": 4,
            "sample_shape": list(volume.shape),
            "sample_axes": ["x", "y", "z", "time"],
            "natural_record_kind": "complete_bids_bold_nifti_run",
            "subject": spec.subject,
            "task": spec.task,
            "source_key": spec.key,
            "source_sha256": spec.sha256,
            "source_datatype_code": EXPECTED_DATATYPE,
            "source_bitpix": EXPECTED_BITPIX,
            "source_endianness": "little",
            "source_vox_offset": EXPECTED_VOX_OFFSET,
            "spatial_voxel_size_mm": list(volume.pixdim[:3]),
            "repetition_time_seconds": volume.pixdim[3],
            "min": volume.minimum,
            "max": volume.maximum,
            "unique_value_count": volume.unique_values,
            "zero_count": volume.zero_count,
            "zero_fraction": volume.zero_count / spec.value_count,
            "sha256": volume.payload_sha256,
        }
        rows.append(row)
        records.append(
            {
                "source_key": spec.key,
                "subject": spec.subject,
                "task": spec.task,
                "shape": list(volume.shape),
                "value_count": spec.value_count,
                "sample_bytes": len(volume.payload),
                "min": volume.minimum,
                "max": volume.maximum,
                "unique_value_count": volume.unique_values,
                "zero_count": volume.zero_count,
                "payload_sha256": volume.payload_sha256,
            }
        )

    total_values = sum(int(row["value_count"]) for row in rows)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if len(rows) != EXPECTED_SAMPLES or total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError(f"output aggregate mismatch: samples={len(rows)} values={total_values} bytes={total_bytes}")
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "subject_count": len({str(row["subject"]) for row in rows}),
        "task_counts": dict(sorted(Counter(str(row["task"]) for row in rows).items())),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": statistics.median(int(row["value_count"]) for row in rows),
        "minimum_value": min(int(row["min"]) for row in rows),
        "maximum_value": max(int(row["max"]) for row in rows),
        "all_frames_nonconstant_and_unique_within_run": True,
        "all_run_payload_hashes_unique": True,
        "records": records,
    }
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes} "
        f"subjects={stats['subject_count']} tasks={len(stats['task_counts'])}"
    )


def verify(args: argparse.Namespace) -> None:
    specs = load_selection(args.recipe_dir)
    validate_source_set(args.download_dir, specs)
    if not args.index.is_file() or not args.stats.is_file():
        raise ValueError("missing index or ingest stats")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    stats = json.loads(args.stats.read_text())
    if len(rows) != len(specs) or int(stats.get("sample_count", -1)) != EXPECTED_SAMPLES:
        raise ValueError("sample count mismatch")
    indexed_paths: set[str] = set()
    output_hashes: set[str] = set()
    total_values = 0
    total_bytes = 0
    for row, spec in zip(rows, specs, strict=True):
        source = args.download_dir / "volumes" / spec.filename
        volume = parse_volume(source, spec)
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise ValueError("index identity mismatch")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16 or row.get("endianness") != "little":
            raise ValueError("index numeric representation mismatch")
        if row.get("source_key") != spec.key or row.get("subject") != spec.subject or row.get("task") != spec.task:
            raise ValueError("index source identity mismatch")
        if row.get("sample_shape") != list(volume.shape) or row.get("sample_axes") != ["x", "y", "z", "time"]:
            raise ValueError("index sample geometry mismatch")
        if row.get("natural_record_kind") != "complete_bids_bold_nifti_run":
            raise ValueError("index natural boundary mismatch")
        sample_path = str(row.get("sample_path", ""))
        expected_prefix = f"samples/{DATASET_ID}/{SERIES_ID}/"
        if not sample_path.startswith(expected_prefix) or sample_path in indexed_paths:
            raise ValueError(f"invalid or duplicate sample path: {sample_path}")
        indexed_paths.add(sample_path)
        output = args.data_root / sample_path
        payload = output.read_bytes()
        if payload != volume.payload:
            raise ValueError(f"source/output byte mismatch: {output}")
        if hashlib.sha256(payload).hexdigest() != row.get("sha256") or row.get("sha256") in output_hashes:
            raise ValueError(f"output hash mismatch or duplicate: {output}")
        output_hashes.add(str(row["sha256"]))
        if int(row.get("value_count", -1)) != spec.value_count or int(row.get("sample_size_bytes", -1)) != len(payload):
            raise ValueError(f"output size metadata mismatch: {output}")
        if row.get("min") != volume.minimum or row.get("max") != volume.maximum:
            raise ValueError(f"output range metadata mismatch: {output}")
        if row.get("unique_value_count") != volume.unique_values or row.get("zero_count") != volume.zero_count:
            raise ValueError(f"output distribution metadata mismatch: {output}")
        total_values += spec.value_count
        total_bytes += len(payload)

    actual_paths = {
        path.relative_to(args.data_root).as_posix()
        for path in (args.samples_root / SERIES_ID).rglob("*")
        if path.is_file()
    }
    if actual_paths != indexed_paths:
        raise ValueError("sample directory and index differ")
    if total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError("verified aggregate mismatch")
    if int(stats.get("primary_values", -1)) != EXPECTED_VALUES or int(stats.get("primary_bytes", -1)) != EXPECTED_BYTES:
        raise ValueError("ingest stats aggregate mismatch")
    print(
        f"verified_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes} "
        f"unique_payloads={len(output_hashes)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args)
        else:
            verify(args)
    except (OSError, ValueError, gzip.BadGzipFile, struct.error) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
