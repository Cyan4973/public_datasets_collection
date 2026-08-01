#!/usr/bin/env python3
"""Build and source-byte-verify native SigMF ci16_le RF recordings."""

from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys


DATASET_ID = "zenodo_v16_nb_iot_sigmf_ci16"
SERIES_ID = "v16_nb_iot_iq_ci16"
EXPECTED = (
    {
        "stem": "V16-beacon-NB-IoT-uplink-20251231",
        "record_id": "18202739",
        "bytes": 438_824_272,
        "md5": "2894a6a90a556bffd24dd70043298658",
        "sha512": "5fc28d94abe70f473cd68dbb20cdd011357fcaf5a0b1eb843c682d89e74d54f40d50901195d3c13385a15fada8221c030ac6185d47a8d74330d961c3e86fc2bd",
        "frequency": 832_300_000.0,
    },
    {
        "stem": "V16-beacon-NB-IoT-downlink-20251231",
        "record_id": "19771729",
        "bytes": 438_824_272,
        "md5": "f1b0a3cc4484dd7418657a031404d422",
        "sha512": "6cc5bebad45854ea2e308ca510359962f018d4a7b5ee924411bffffb05a2a94a71d40bcea8070b42fee868e38447918d50487c5b015c08c66adaad707ed78a7b",
        "frequency": 791_300_000.0,
    },
)
SAMPLE_RATE = 320_000.0
MAX_PRIMARY_BYTES = 1_000_000_000
CHUNK_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Recording:
    source: Path
    metadata: Path
    complex_samples: int
    sample_rate: float
    frequency: float
    datetime: str
    minimum_i: int
    maximum_i: int
    minimum_q: int
    maximum_q: int


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            value.update(chunk)
    return value.hexdigest()


def scan_components(path: Path) -> tuple[int, int, int, int]:
    min_i = min_q = 32767
    max_i = max_q = -32768
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            if len(chunk) % 4:
                raise ValueError(f"{path.name}: incomplete complex sample frame")
            values = array("h")
            values.frombytes(chunk)
            if sys.byteorder != "little":
                values.byteswap()
            i_values = values[0::2]
            q_values = values[1::2]
            min_i = min(min_i, min(i_values))
            max_i = max(max_i, max(i_values))
            min_q = min(min_q, min(q_values))
            max_q = max(max_q, max(q_values))
    if min_i == max_i or min_q == max_q:
        raise ValueError(f"{path.name}: constant I or Q component")
    return min_i, max_i, min_q, max_q


def load_recording(download_dir: Path, expected: dict[str, object], *, verify_hashes: bool) -> Recording:
    stem = str(expected["stem"])
    source = download_dir / f"{stem}.sigmf-data"
    metadata = download_dir / f"{stem}.sigmf-meta"
    if not source.is_file() or not metadata.is_file():
        raise ValueError(f"missing SigMF pair for {stem}")
    if source.stat().st_size != int(expected["bytes"]):
        raise ValueError(f"{source.name}: wrong byte size")
    if source.stat().st_size % 4:
        raise ValueError(f"{source.name}: incomplete ci16 frame")
    if verify_hashes:
        if digest(source, "md5") != expected["md5"]:
            raise ValueError(f"{source.name}: MD5 mismatch")
        if digest(source, "sha512") != expected["sha512"]:
            raise ValueError(f"{source.name}: SHA-512 mismatch")
    obj = json.loads(metadata.read_text(encoding="utf-8"))
    global_meta = obj.get("global", {})
    captures = obj.get("captures", [])
    if not isinstance(global_meta, dict) or not isinstance(captures, list) or len(captures) != 1:
        raise ValueError(f"{metadata.name}: invalid SigMF structure")
    if global_meta.get("core:datatype") != "ci16_le":
        raise ValueError(f"{metadata.name}: expected ci16_le")
    if int(global_meta.get("core:num_channels", 0)) != 1:
        raise ValueError(f"{metadata.name}: expected one channel")
    sample_rate = float(global_meta.get("core:sample_rate", 0))
    if sample_rate != SAMPLE_RATE or not math.isfinite(sample_rate):
        raise ValueError(f"{metadata.name}: unexpected sample rate {sample_rate}")
    capture = captures[0]
    if not isinstance(capture, dict) or int(capture.get("core:sample_start", -1)) != 0:
        raise ValueError(f"{metadata.name}: capture does not start at zero")
    frequency = float(capture.get("core:frequency", 0))
    if frequency != float(expected["frequency"]) or not math.isfinite(frequency):
        raise ValueError(f"{metadata.name}: unexpected center frequency {frequency}")
    min_i, max_i, min_q, max_q = scan_components(source)
    return Recording(
        source=source,
        metadata=metadata,
        complex_samples=source.stat().st_size // 4,
        sample_rate=sample_rate,
        frequency=frequency,
        datetime=str(capture.get("core:datetime", "")),
        minimum_i=min_i,
        maximum_i=max_i,
        minimum_q=min_q,
        maximum_q=max_q,
    )


def build(download_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    records = []
    for expected in EXPECTED:
        recording = load_recording(download_dir, expected, verify_hashes=True)
        output = output_dir / f"{expected['stem']}_ci16_n{recording.complex_samples:012d}.bin"
        try:
            os.link(recording.source, output)
        except OSError:
            shutil.copyfile(recording.source, output)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": recording.source.stat().st_size,
            "value_count": recording.complex_samples * 2,
            "sample_format": "raw homogeneous interleaved signed-int16 I/Q array",
            "sample_geometry": "complex_time_series",
            "sample_rank": 2,
            "sample_shape": [recording.complex_samples, 2],
            "sample_axes": ["complex_sample", "component_iq"],
            "natural_record_kind": "sigmf_recording",
            "source_sample": recording.source.name,
            "source_metadata": recording.metadata.name,
            "source_record_id": expected["record_id"],
            "source_datatype": "ci16_le",
            "sample_rate_hz": recording.sample_rate,
            "center_frequency_hz": recording.frequency,
            "capture_datetime": recording.datetime,
            "min_i": recording.minimum_i,
            "max_i": recording.maximum_i,
            "min_q": recording.minimum_q,
            "max_q": recording.maximum_q,
        }
        rows.append(row)
        records.append({
            "source_name": recording.source.name,
            "complex_samples": recording.complex_samples,
            "sample_bytes": recording.source.stat().st_size,
            "sample_rate_hz": recording.sample_rate,
            "center_frequency_hz": recording.frequency,
            "min_i": recording.minimum_i,
            "max_i": recording.maximum_i,
            "min_q": recording.minimum_q,
            "max_q": recording.maximum_q,
        })
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    counts = [int(row["value_count"]) for row in rows]
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    if sum(counts) < 10_000 or statistics.median(counts) < 1_000:
        raise ValueError("acceptance floor failed")
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "primary_values": sum(counts),
        "primary_bytes": total_bytes,
        "median_value_count": statistics.median(counts),
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built samples={len(rows)} primary_values={sum(counts)} "
        f"primary_bytes={total_bytes} median={statistics.median(counts):g}"
    )


def verify(download_dir: Path, index_path: Path, data_root: Path) -> None:
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != len(EXPECTED):
        raise ValueError(f"expected {len(EXPECTED)} index rows, found {len(rows)}")
    total_bytes = 0
    counts = []
    for row, expected in zip(rows, EXPECTED, strict=True):
        recording = load_recording(download_dir, expected, verify_hashes=True)
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise ValueError("index identity mismatch")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16:
            raise ValueError("indexed sample is not int16")
        if row.get("sample_shape") != [recording.complex_samples, 2]:
            raise ValueError("indexed sample shape mismatch")
        sample = data_root / row["sample_path"]
        if sample.stat().st_size != recording.source.stat().st_size:
            raise ValueError(f"{sample}: size mismatch")
        if digest(sample, "sha512") != expected["sha512"]:
            raise ValueError(f"{sample}: source-byte mismatch")
        for key, value in (
            ("min_i", recording.minimum_i), ("max_i", recording.maximum_i),
            ("min_q", recording.minimum_q), ("max_q", recording.maximum_q),
        ):
            if int(row[key]) != value:
                raise ValueError(f"{sample}: {key} mismatch")
        total_bytes += sample.stat().st_size
        counts.append(recording.complex_samples * 2)
    if total_bytes > MAX_PRIMARY_BYTES or sum(counts) < 10_000 or statistics.median(counts) < 1_000:
        raise ValueError("acceptance constraints failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} "
        f"median={statistics.median(counts):g}"
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
