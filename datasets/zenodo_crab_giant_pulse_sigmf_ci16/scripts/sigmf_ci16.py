#!/usr/bin/env python3
"""Build and source-byte-verify the Crab giant-pulse SigMF ci16_le recording."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys


DATASET_ID = "zenodo_crab_giant_pulse_sigmf_ci16"
SERIES_ID = "crab_giant_pulse_iq_ci16"
DATA_NAME = "crab-giantpulse.sigmf-data"
META_NAME = "crab-giantpulse.sigmf-meta"
EXPECTED_BYTES = 16_000_000
EXPECTED_MD5 = "a7a72584861a34ca76cb0813f6115749"
EXPECTED_META_MD5 = "e0e46f218f54a283eaaf04cbddf050da"
EXPECTED_COMPLEX_SAMPLES = 4_000_000
EXPECTED_SAMPLE_RATE = 20_000_000.0
EXPECTED_FREQUENCY = 410_000_000.0
EXPECTED_LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
EXPECTED_DOI = "10.5281/zenodo.13143544"
CHUNK_BYTES = 8 * 1024 * 1024


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


def load_recording(download_dir: Path, *, verify_hashes: bool) -> dict[str, object]:
    source = download_dir / DATA_NAME
    metadata = download_dir / META_NAME
    if not source.is_file() or not metadata.is_file():
        raise ValueError("missing Crab giant-pulse SigMF data/meta pair")
    if source.stat().st_size != EXPECTED_BYTES or source.stat().st_size % 4:
        raise ValueError(f"{source.name}: wrong byte size or incomplete ci16 frame")
    if verify_hashes:
        if digest(source, "md5") != EXPECTED_MD5:
            raise ValueError(f"{source.name}: MD5 mismatch")
        if digest(metadata, "md5") != EXPECTED_META_MD5:
            raise ValueError(f"{metadata.name}: MD5 mismatch")

    obj = json.loads(metadata.read_text(encoding="utf-8"))
    global_meta = obj.get("global", {})
    captures = obj.get("captures", [])
    if not isinstance(global_meta, dict) or not isinstance(captures, list) or len(captures) != 1:
        raise ValueError(f"{metadata.name}: invalid SigMF structure")
    if global_meta.get("core:datatype") != "ci16_le":
        raise ValueError(f"{metadata.name}: expected ci16_le")
    if global_meta.get("core:license") != EXPECTED_LICENSE:
        raise ValueError(f"{metadata.name}: expected embedded CC BY-SA 4.0 license")
    if global_meta.get("core:data_doi") != EXPECTED_DOI:
        raise ValueError(f"{metadata.name}: unexpected data DOI")
    sample_rate = float(global_meta.get("core:sample_rate", 0))
    if sample_rate != EXPECTED_SAMPLE_RATE or not math.isfinite(sample_rate):
        raise ValueError(f"{metadata.name}: unexpected sample rate {sample_rate}")
    capture = captures[0]
    if not isinstance(capture, dict) or int(capture.get("core:sample_start", -1)) != 0:
        raise ValueError(f"{metadata.name}: capture does not start at zero")
    frequency = float(capture.get("core:frequency", 0))
    if frequency != EXPECTED_FREQUENCY or not math.isfinite(frequency):
        raise ValueError(f"{metadata.name}: unexpected center frequency {frequency}")
    complex_samples = source.stat().st_size // 4
    if complex_samples != EXPECTED_COMPLEX_SAMPLES:
        raise ValueError(f"{source.name}: unexpected complex sample count")
    minimum_i, maximum_i, minimum_q, maximum_q = scan_components(source)
    return {
        "source": source,
        "metadata": metadata,
        "complex_samples": complex_samples,
        "sample_rate": sample_rate,
        "frequency": frequency,
        "datetime": str(capture.get("core:datetime", "")),
        "minimum_i": minimum_i,
        "maximum_i": maximum_i,
        "minimum_q": minimum_q,
        "maximum_q": maximum_q,
    }


def build(download_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    recording = load_recording(download_dir, verify_hashes=True)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    output = output_dir / "crab_giant_pulse_ci16_n000004000000.bin"
    source = recording["source"]
    assert isinstance(source, Path)
    try:
        os.link(source, output)
    except OSError:
        shutil.copyfile(source, output)

    complex_samples = int(recording["complex_samples"])
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": output.stat().st_size,
        "value_count": complex_samples * 2,
        "sample_format": "raw homogeneous interleaved signed-int16 I/Q array",
        "sample_geometry": "complex_time_series",
        "sample_rank": 2,
        "sample_shape": [complex_samples, 2],
        "sample_axes": ["complex_sample", "component_iq"],
        "natural_record_kind": "sigmf_recording",
        "source_sample": DATA_NAME,
        "source_metadata": META_NAME,
        "source_record_id": "13143544",
        "source_datatype": "ci16_le",
        "sample_rate_hz": recording["sample_rate"],
        "center_frequency_hz": recording["frequency"],
        "capture_datetime": recording["datetime"],
        "min_i": recording["minimum_i"],
        "max_i": recording["maximum_i"],
        "min_q": recording["minimum_q"],
        "max_q": recording["maximum_q"],
    }
    count = int(row["value_count"])
    if count < 10_000 or statistics.median([count]) < 1_000:
        raise ValueError("acceptance floor failed")
    index_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": 1,
        "primary_values": count,
        "primary_bytes": output.stat().st_size,
        "median_value_count": count,
        "record": {
            "source_name": DATA_NAME,
            "complex_samples": complex_samples,
            "sample_bytes": output.stat().st_size,
            "sample_rate_hz": recording["sample_rate"],
            "center_frequency_hz": recording["frequency"],
            "min_i": recording["minimum_i"],
            "max_i": recording["maximum_i"],
            "min_q": recording["minimum_q"],
            "max_q": recording["maximum_q"],
        },
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built samples=1 primary_values={count} primary_bytes={output.stat().st_size} median={count}")


def verify(download_dir: Path, index_path: Path, data_root: Path) -> None:
    recording = load_recording(download_dir, verify_hashes=True)
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError(f"expected one index row, found {len(rows)}")
    row = rows[0]
    complex_samples = int(recording["complex_samples"])
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
        raise ValueError("index identity mismatch")
    if row.get("numeric_kind") != "int" or row.get("bit_width") != 16:
        raise ValueError("indexed sample is not int16")
    if row.get("endianness") != "little" or row.get("sample_shape") != [complex_samples, 2]:
        raise ValueError("indexed sample endianness or shape mismatch")
    sample = data_root / row["sample_path"]
    if sample.stat().st_size != EXPECTED_BYTES or digest(sample, "md5") != EXPECTED_MD5:
        raise ValueError(f"{sample}: source-byte mismatch")
    for key, value in (
        ("min_i", recording["minimum_i"]),
        ("max_i", recording["maximum_i"]),
        ("min_q", recording["minimum_q"]),
        ("max_q", recording["maximum_q"]),
    ):
        if int(row[key]) != int(value):
            raise ValueError(f"{sample}: {key} mismatch")
    print(
        f"verified dataset={DATASET_ID} samples=1 total_values={complex_samples * 2} "
        f"total_bytes={sample.stat().st_size} median={complex_samples * 2}"
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
