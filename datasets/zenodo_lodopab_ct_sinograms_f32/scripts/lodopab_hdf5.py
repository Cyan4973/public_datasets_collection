#!/usr/bin/env python3
from __future__ import annotations

import argparse
import array
import hashlib
import importlib.util
import json
import math
import mmap
from pathlib import Path
import shutil
import statistics
import sys


DATASET_ID = "zenodo_lodopab_ct_sinograms_f32"
SERIES_ID = "lodopab_ct_observation_sinogram_f32"
SOURCE_NAME = "observation_validation_000.hdf5"
SOURCE_SIZE = 272735288
SOURCE_SHA256 = "04f0399b1d1d4ff8d012d54312b1b67f84a412d94bf935865963172e996fb977"
SOURCE_SHAPE = (128, 1000, 513)
CHUNK_SHAPE = (8, 63, 33)
SAMPLE_VALUES = SOURCE_SHAPE[1] * SOURCE_SHAPE[2]
SAMPLE_BYTES = SAMPLE_VALUES * 4
EXPECTED_VALUES = math.prod(SOURCE_SHAPE)
EXPECTED_BYTES = EXPECTED_VALUES * 4
EXPECTED_AGGREGATE_SHA256 = "22f4ccaf7abb43e8b657429a25f5ab6e5dc61144e3f695af07caba0a6fbb893e"


def load_hdf5_helpers() -> object:
    path = Path(__file__).resolve().parents[1] / "probe_hdf5.py"
    spec = importlib.util.spec_from_file_location("lodopab_probe_hdf5", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load HDF5 helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H5 = load_hdf5_helpers()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_source(path: Path) -> None:
    if not path.is_file() or path.stat().st_size != SOURCE_SIZE:
        raise ValueError(f"missing or wrong-sized source HDF5: {path}")
    digest = file_sha256(path)
    if digest != SOURCE_SHA256:
        raise ValueError(f"source SHA-256 mismatch: expected={SOURCE_SHA256} actual={digest}")


def validated_chunks(raw: mmap.mmap) -> list[dict[str, object]]:
    layout = H5.source_layout(raw)
    if tuple(layout["shape"]) != SOURCE_SHAPE or tuple(layout["chunk_shape"]) != CHUNK_SHAPE:
        raise ValueError(f"source HDF5 layout changed: {layout}")
    chunks = H5.collect_chunks(raw, int(layout["chunk_btree"]))
    expected_offsets = {
        (sample, angle, detector, 0)
        for sample in range(0, SOURCE_SHAPE[0], CHUNK_SHAPE[0])
        for angle in range(0, SOURCE_SHAPE[1], CHUNK_SHAPE[1])
        for detector in range(0, SOURCE_SHAPE[2], CHUNK_SHAPE[2])
    }
    actual_offsets = {tuple(chunk["offsets"]) for chunk in chunks}
    if actual_offsets != expected_offsets or len(chunks) != len(actual_offsets):
        raise ValueError(
            f"chunk grid mismatch: expected={len(expected_offsets)} actual={len(chunks)}"
        )
    expected_chunk_bytes = math.prod(CHUNK_SHAPE) * 4
    for chunk in chunks:
        if int(chunk["filter_mask"]) != 0 or int(chunk["stored_bytes"]) != expected_chunk_bytes:
            raise ValueError(f"unexpected unfiltered chunk metadata: {chunk}")
        source_offset = int(chunk["source_offset"])
        if source_offset < 0 or source_offset + expected_chunk_bytes > len(raw):
            raise ValueError(f"chunk exceeds source file: {chunk}")
    return chunks


def iter_samples(raw: mmap.mmap, chunks: list[dict[str, object]]):
    by_offsets = {tuple(int(value) for value in chunk["offsets"]): chunk for chunk in chunks}
    for sample_base in range(0, SOURCE_SHAPE[0], CHUNK_SHAPE[0]):
        valid_samples = min(CHUNK_SHAPE[0], SOURCE_SHAPE[0] - sample_base)
        buffers = [bytearray(SAMPLE_BYTES) for _ in range(valid_samples)]
        for angle_base in range(0, SOURCE_SHAPE[1], CHUNK_SHAPE[1]):
            valid_angles = min(CHUNK_SHAPE[1], SOURCE_SHAPE[1] - angle_base)
            for detector_base in range(0, SOURCE_SHAPE[2], CHUNK_SHAPE[2]):
                valid_detectors = min(CHUNK_SHAPE[2], SOURCE_SHAPE[2] - detector_base)
                chunk = by_offsets[(sample_base, angle_base, detector_base, 0)]
                source_offset = int(chunk["source_offset"])
                payload = memoryview(raw)[source_offset : source_offset + int(chunk["stored_bytes"])]
                row_bytes = valid_detectors * 4
                for local_sample in range(valid_samples):
                    target = buffers[local_sample]
                    for local_angle in range(valid_angles):
                        source_start = (
                            (local_sample * CHUNK_SHAPE[1] + local_angle) * CHUNK_SHAPE[2] * 4
                        )
                        target_start = (
                            (angle_base + local_angle) * SOURCE_SHAPE[2] + detector_base
                        ) * 4
                        target[target_start : target_start + row_bytes] = payload[
                            source_start : source_start + row_bytes
                        ]
        for local_sample, payload in enumerate(buffers):
            yield sample_base + local_sample, bytes(payload)


def sample_stats(payload: bytes) -> tuple[float, float, int]:
    if len(payload) != SAMPLE_BYTES:
        raise ValueError(f"sample size mismatch: expected={SAMPLE_BYTES} actual={len(payload)}")
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != SAMPLE_VALUES or not all(math.isfinite(value) for value in values):
        raise ValueError("sample contains missing or non-finite values")
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        raise ValueError("constant sinogram sample")
    zeros = sum(value == 0.0 for value in values)
    return minimum, maximum, zeros


def index_row(path: Path, data_root: Path, sample_number: int, digest: str) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": SAMPLE_BYTES,
        "value_count": SAMPLE_VALUES,
        "shape": [SOURCE_SHAPE[1], SOURCE_SHAPE[2]],
        "natural_record_kind": "complete_lodopab_ct_validation_slice_observation_sinogram",
        "source_shard": SOURCE_NAME,
        "source_record_index": sample_number,
        "sample_sha256": digest,
    }


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    samples_root = args.samples_dir.resolve()
    output_dir = samples_root / SERIES_ID
    temporary_dir = samples_root / f".{SERIES_ID}.tmp"
    index_path = args.index.resolve()
    stats_path = args.stats.resolve()
    data_root = args.data_root.resolve()
    validate_source(source)
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)

    rows: list[dict[str, object]] = []
    aggregate = hashlib.sha256()
    minimum = math.inf
    maximum = -math.inf
    zero_values = 0
    try:
        with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
            chunks = validated_chunks(raw)
            for sample_number, payload in iter_samples(raw, chunks):
                sample_minimum, sample_maximum, sample_zeros = sample_stats(payload)
                minimum = min(minimum, sample_minimum)
                maximum = max(maximum, sample_maximum)
                zero_values += sample_zeros
                digest = hashlib.sha256(payload).hexdigest()
                aggregate.update(payload)
                final_path = output_dir / f"validation_000_sinogram_{sample_number:03d}.bin"
                (temporary_dir / final_path.name).write_bytes(payload)
                rows.append(index_row(final_path, data_root, sample_number, digest))
                if (sample_number + 1) % 16 == 0:
                    print(f"samples_written={sample_number + 1}/{SOURCE_SHAPE[0]}", flush=True)
        if len(rows) != SOURCE_SHAPE[0]:
            raise ValueError(f"sample count mismatch: expected={SOURCE_SHAPE[0]} actual={len(rows)}")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary_dir.replace(output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    total_values = len(rows) * SAMPLE_VALUES
    total_bytes = len(rows) * SAMPLE_BYTES
    if total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError(f"aggregate size mismatch: values={total_values} bytes={total_bytes}")
    aggregate_sha256 = aggregate.hexdigest()
    if EXPECTED_AGGREGATE_SHA256 and aggregate_sha256 != EXPECTED_AGGREGATE_SHA256:
        raise ValueError(f"aggregate decoded SHA-256 mismatch: {aggregate_sha256}")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_tmp = index_path.with_suffix(index_path.suffix + ".tmp")
    with index_tmp.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    index_tmp.replace(index_path)

    stats = {
        "dataset_id": DATASET_ID,
        "source_name": SOURCE_NAME,
        "source_bytes": SOURCE_SIZE,
        "source_sha256": SOURCE_SHA256,
        "source_shape": list(SOURCE_SHAPE),
        "source_chunk_shape": list(CHUNK_SHAPE),
        "source_chunk_count": 4096,
        "sample_count": len(rows),
        "values_per_sample": SAMPLE_VALUES,
        "sample_size_bytes": SAMPLE_BYTES,
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "minimum": minimum,
        "maximum": maximum,
        "zero_values": zero_values,
        "zero_fraction": zero_values / total_values,
        "median_sample_values": statistics.median([SAMPLE_VALUES] * len(rows)),
        "aggregate_decoded_sha256": aggregate_sha256,
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_tmp = stats_path.with_suffix(stats_path.suffix + ".tmp")
    stats_tmp.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stats_tmp.replace(stats_path)
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    output_dir = args.samples_dir.resolve() / SERIES_ID
    index_path = args.index.resolve()
    stats_path = args.stats.resolve()
    data_root = args.data_root.resolve()
    validate_source(source)
    if not output_dir.is_dir() or not index_path.is_file() or not stats_path.is_file():
        raise ValueError("missing samples, index, or ingest statistics")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != SOURCE_SHAPE[0]:
        raise ValueError(f"index count mismatch: {len(rows)}")
    by_number = {int(row["source_record_index"]): row for row in rows}
    if set(by_number) != set(range(SOURCE_SHAPE[0])):
        raise ValueError("index source-record coverage is incomplete or duplicated")

    aggregate = hashlib.sha256()
    minimum = math.inf
    maximum = -math.inf
    zero_values = 0
    expected_files: set[Path] = set()
    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        chunks = validated_chunks(raw)
        for sample_number, expected_payload in iter_samples(raw, chunks):
            row = by_number[sample_number]
            expected_path = output_dir / f"validation_000_sinogram_{sample_number:03d}.bin"
            actual_path = data_root / str(row["sample_path"])
            if actual_path != expected_path or not actual_path.is_file():
                raise ValueError(f"missing or unexpected sample path for record {sample_number}")
            actual_payload = actual_path.read_bytes()
            if actual_payload != expected_payload:
                raise ValueError(f"sample differs from fresh HDF5 dechunking: {actual_path}")
            sample_minimum, sample_maximum, sample_zeros = sample_stats(actual_payload)
            minimum = min(minimum, sample_minimum)
            maximum = max(maximum, sample_maximum)
            zero_values += sample_zeros
            digest = hashlib.sha256(actual_payload).hexdigest()
            expected_metadata = index_row(expected_path, data_root, sample_number, digest)
            if row != expected_metadata:
                raise ValueError(f"index metadata mismatch for record {sample_number}")
            aggregate.update(actual_payload)
            expected_files.add(actual_path)
            if (sample_number + 1) % 16 == 0:
                print(f"samples_verified={sample_number + 1}/{SOURCE_SHAPE[0]}", flush=True)

    actual_files = set(output_dir.glob("*.bin"))
    if actual_files != expected_files:
        raise ValueError("sample file set differs from the indexed source reconstruction")
    aggregate_sha256 = aggregate.hexdigest()
    if EXPECTED_AGGREGATE_SHA256 and aggregate_sha256 != EXPECTED_AGGREGATE_SHA256:
        raise ValueError(f"aggregate decoded SHA-256 mismatch: {aggregate_sha256}")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    expected_stats = {
        "sample_count": SOURCE_SHAPE[0],
        "values_per_sample": SAMPLE_VALUES,
        "sample_size_bytes": SAMPLE_BYTES,
        "total_values": EXPECTED_VALUES,
        "total_size_bytes": EXPECTED_BYTES,
        "minimum": minimum,
        "maximum": maximum,
        "zero_values": zero_values,
        "zero_fraction": zero_values / EXPECTED_VALUES,
        "median_sample_values": SAMPLE_VALUES,
        "aggregate_decoded_sha256": aggregate_sha256,
    }
    for key, expected in expected_stats.items():
        if stats.get(key) != expected:
            raise ValueError(
                f"ingest statistics mismatch key={key}: expected={expected!r} actual={stats.get(key)!r}"
            )
    if EXPECTED_BYTES > 1_000_000_000 or SAMPLE_VALUES < 1_000:
        raise ValueError("accepted output violates repository volume/sample floors")
    print(
        f"verified samples={SOURCE_SHAPE[0]} values={EXPECTED_VALUES} bytes={EXPECTED_BYTES} "
        f"range={minimum}..{maximum} zero_fraction={zero_values / EXPECTED_VALUES:.9f} "
        f"aggregate_sha256={aggregate_sha256}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"{DATASET_ID}: {exc}") from exc
