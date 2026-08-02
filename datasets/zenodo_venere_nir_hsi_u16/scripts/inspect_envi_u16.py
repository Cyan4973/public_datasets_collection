#!/usr/bin/env python3
"""Validate and characterize the pinned Venere uint16 detector cube."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import sys


HEADER_SIZE = 5_918
HEADER_MD5 = "9c3aaf32039f039143f60b8535a86b61"
PAYLOAD_SIZE = 90_685_440
PAYLOAD_MD5 = "523a952df4261d6f3692df74bdc7c699"
SAMPLES = 384
LINES = 410
BANDS = 288
VALUE_COUNT = SAMPLES * LINES * BANDS


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(text: str, name: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([^\r\n]+)", text)
    if not match:
        raise ValueError(f"missing ENVI field {name!r}")
    return match.group(1).strip().strip("{} ")


def validate_header(path: Path) -> list[float]:
    if path.stat().st_size != HEADER_SIZE or md5(path) != HEADER_MD5:
        raise ValueError("ENVI header size or MD5 mismatch")
    text = path.read_text(encoding="utf-8")
    expected = {
        "samples": "384",
        "lines": "410",
        "bands": "288",
        "interleave": "bil",
        "data type": "12",
        "header offset": "0",
        "byte order": "0",
    }
    for key, value in expected.items():
        if scalar(text, key).lower() != value:
            raise ValueError(f"unexpected ENVI {key}: {scalar(text, key)!r}")
    wavelength_match = re.search(r"(?is)^\s*wavelength\s*=\s*\{(.*?)\}", text, re.MULTILINE)
    if not wavelength_match:
        raise ValueError("missing wavelength vector")
    wavelengths = [float(value.strip()) for value in wavelength_match.group(1).split(",") if value.strip()]
    if len(wavelengths) != BANDS or wavelengths != sorted(wavelengths):
        raise ValueError("invalid wavelength vector")
    return wavelengths


def inspect(header_path: Path, payload_path: Path) -> dict[str, object]:
    wavelengths = validate_header(header_path)
    if payload_path.stat().st_size != PAYLOAD_SIZE or md5(payload_path) != PAYLOAD_MD5:
        raise ValueError("ENVI payload size or MD5 mismatch")
    distinct: set[int] = set()
    global_min = 65535
    global_max = 0
    zero_count = 0
    saturated_count = 0
    total_sum = 0
    band_min = [65535] * BANDS
    band_max = [0] * BANDS
    band_sum = [0] * BANDS
    band_zero = [0] * BANDS
    with payload_path.open("rb") as handle:
        for _line in range(LINES):
            for band in range(BANDS):
                raw = handle.read(SAMPLES * 2)
                if len(raw) != SAMPLES * 2:
                    raise ValueError("truncated ENVI BIL payload")
                values = array("H")
                values.frombytes(raw)
                if values.itemsize != 2:
                    raise ValueError("host unsigned-short width is not 16 bits")
                if sys.byteorder == "big":
                    values.byteswap()
                local_min = min(values)
                local_max = max(values)
                local_zero = values.count(0)
                local_sum = sum(values)
                distinct.update(values)
                global_min = min(global_min, local_min)
                global_max = max(global_max, local_max)
                zero_count += local_zero
                saturated_count += values.count(65535)
                total_sum += local_sum
                band_min[band] = min(band_min[band], local_min)
                band_max[band] = max(band_max[band], local_max)
                band_sum[band] += local_sum
                band_zero[band] += local_zero
        if handle.read(1):
            raise ValueError("unexpected bytes after ENVI payload")
    pixels_per_band = LINES * SAMPLES
    band_stats = [
        {
            "band_index": band,
            "wavelength_nm": wavelengths[band],
            "minimum": band_min[band],
            "maximum": band_max[band],
            "mean": band_sum[band] / pixels_per_band,
            "zero_fraction": band_zero[band] / pixels_per_band,
        }
        for band in range(BANDS)
    ]
    return {
        "header_file": header_path.name,
        "header_bytes": header_path.stat().st_size,
        "header_md5": HEADER_MD5,
        "payload_file": payload_path.name,
        "payload_bytes": payload_path.stat().st_size,
        "payload_md5": PAYLOAD_MD5,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "interleave": "bil",
        "lines": LINES,
        "samples": SAMPLES,
        "bands": BANDS,
        "value_count": VALUE_COUNT,
        "wavelength_minimum_nm": wavelengths[0],
        "wavelength_maximum_nm": wavelengths[-1],
        "minimum": global_min,
        "maximum": global_max,
        "distinct_values": len(distinct),
        "zero_values": zero_count,
        "zero_fraction": zero_count / VALUE_COUNT,
        "saturated_values": saturated_count,
        "saturated_fraction": saturated_count / VALUE_COUNT,
        "mean": total_sum / VALUE_COUNT,
        "constant_bands": sum(low == high for low, high in zip(band_min, band_max)),
        "band_stats": band_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.header.is_file() or not args.payload.is_file():
        raise SystemExit("missing ENVI header or payload")
    report = inspect(args.header, args.payload)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "band_stats"}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if int(report["distinct_values"]) < 256:
        raise SystemExit("too few distinct detector values")
    if int(report["constant_bands"]) != 0:
        raise SystemExit("one or more spectral bands are constant")
    if float(report["zero_fraction"]) > 0.95:
        raise SystemExit("spectral cube is overwhelmingly zero")


if __name__ == "__main__":
    main()
