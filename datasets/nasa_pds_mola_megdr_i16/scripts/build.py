#!/usr/bin/env python3
"""Build selected MOLA MEGDR topography quadrants as little-endian int16."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys


DATASET_ID = "nasa_pds_mola_megdr_i16"
SERIES_ID = "mola_megdr_topography_i16"
PRODUCTS = (
    "MEGT00N000GB", "MEGT00N180GB", "MEGT90N000GB", "MEGT90N180GB",
)
LINES = 5760
LINE_SAMPLES = 11520
VALUES_PER_SAMPLE = LINES * LINE_SAMPLES
BYTES_PER_SAMPLE = VALUES_PER_SAMPLE * 2
TOTAL_BYTES = BYTES_PER_SAMPLE * len(PRODUCTS)
CHUNK_BYTES = 8 * 1024 * 1024


def scalar(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*([^\r\n]+)", text)
    if not match:
        return ""
    return match.group(1).strip().strip('"')


def integer(text: str, key: str) -> int:
    value = scalar(text, key)
    match = re.match(r"^[+-]?\d+", value)
    if not match:
        raise ValueError(f"label lacks integer {key}")
    return int(match.group(0))


def optional_integer(text: str, key: str) -> int:
    return integer(text, key) if scalar(text, key) else 0


def validate_label(path: Path, product: str) -> None:
    text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="ascii", errors="replace"), flags=re.S)
    image_match = re.search(r"(?is)OBJECT\s*=\s*IMAGE\b(.*?)END_OBJECT\s*=\s*IMAGE", text)
    if not image_match:
        raise ValueError(f"{path.name}: lacks IMAGE object")
    image = image_match.group(1)
    if integer(image, "LINES") != LINES or integer(image, "LINE_SAMPLES") != LINE_SAMPLES:
        raise ValueError(f"{path.name}: unexpected image geometry")
    if integer(image, "SAMPLE_BITS") != 16 or scalar(image, "SAMPLE_TYPE").upper() != "MSB_INTEGER":
        raise ValueError(f"{path.name}: not big-endian signed int16")
    if optional_integer(image, "LINE_PREFIX_BYTES"):
        raise ValueError(f"{path.name}: line prefixes are unsupported")
    if optional_integer(image, "LINE_SUFFIX_BYTES"):
        raise ValueError(f"{path.name}: line suffixes are unsupported")
    pointer = scalar(text, "^IMAGE").upper().strip("()")
    if f"{product}.IMG" not in pointer:
        raise ValueError(f"{path.name}: unexpected IMAGE pointer {pointer!r}")


def convert(source: Path, output: Path) -> tuple[int, int, str, str]:
    source_digest = hashlib.sha256()
    output_digest = hashlib.sha256()
    minimum = 32767
    maximum = -32768
    written = 0
    with source.open("rb") as src, output.open("wb") as dst:
        while True:
            raw = src.read(CHUNK_BYTES)
            if not raw:
                break
            if len(raw) % 2:
                raise ValueError(f"{source.name}: odd byte count")
            source_digest.update(raw)
            values = array("h")
            values.frombytes(raw)
            values.byteswap()
            if values:
                minimum = min(minimum, min(values))
                maximum = max(maximum, max(values))
            converted = values.tobytes()
            dst.write(converted)
            output_digest.update(converted)
            written += len(converted)
    if written != BYTES_PER_SAMPLE:
        raise ValueError(f"{source.name}: expected {BYTES_PER_SAMPLE} bytes, wrote {written}")
    if minimum >= maximum:
        raise ValueError(f"{source.name}: constant or invalid raster range {minimum}..{maximum}")
    return minimum, maximum, source_digest.hexdigest(), output_digest.hexdigest()


def main() -> None:
    if sys.byteorder != "little":
        raise SystemExit("build requires a little-endian host for canonical output")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_root = args.repo_root / args.data_dir
    download_dir = data_root / "downloads" / DATASET_ID
    filter_dir = data_root / "filtered" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    output_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for product in PRODUCTS:
        label = download_dir / f"{product.lower()}.lbl"
        source = download_dir / f"{product}.IMG"
        if not label.is_file() or not source.is_file():
            raise SystemExit(f"missing local PDS pair for {product}; run download.sh first")
        validate_label(label, product)
        if source.stat().st_size != BYTES_PER_SAMPLE:
            raise SystemExit(f"{source}: unexpected size {source.stat().st_size}")
        output = output_dir / f"{product.lower()}.bin"
        minimum, maximum, source_sha, output_sha = convert(source, output)
        relative = output.relative_to(data_root).as_posix()
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": relative,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": BYTES_PER_SAMPLE,
            "value_count": VALUES_PER_SAMPLE,
            "sample_geometry": "planetary_topography_quadrant_2d",
            "sample_rank": 2,
            "sample_shape": [LINES, LINE_SAMPLES],
            "sample_axes": ["latitude", "longitude"],
            "natural_record_kind": "mola_megdr_topography_quadrant",
            "product_id": product,
            "min": minimum,
            "max": maximum,
            "sha256": output_sha,
        }
        rows.append(row)
        records.append({
            "product_id": product, "source_file": source.name,
            "source_sha256": source_sha, "sample_sha256": output_sha,
            "value_count": VALUES_PER_SAMPLE, "sample_bytes": BYTES_PER_SAMPLE,
            "min": minimum, "max": maximum,
        })

    total = sum(row["sample_size_bytes"] for row in rows)
    if total != TOTAL_BYTES:
        raise SystemExit(f"unexpected primary byte total: {total}")
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID,
        "sample_count": len(rows), "primary_values": VALUES_PER_SAMPLE * len(rows),
        "primary_bytes": total, "sample_shape": [LINES, LINE_SAMPLES],
        "records": records,
    }
    (filter_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        f"built_samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={total} range={min(r['min'] for r in rows)}..{max(r['max'] for r in rows)}"
    )


if __name__ == "__main__":
    main()
