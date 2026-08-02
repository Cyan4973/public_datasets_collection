#!/usr/bin/env python3
"""Strictly decode, inspect, build, and verify pinned grayscale16 PNG maps."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import zlib


DATASET_ID = "polyhaven_material_displacement_png_u16"
SERIES_ID = "material_displacement_u16"
WIDTH = 1024
HEIGHT = 1024
VALUE_COUNT = WIDTH * HEIGHT
OUTPUT_BYTES = VALUE_COUNT * 2
SOURCES = (
    ("black_painted_planks_disp_1k.png", 1_033_118, "a2f1a8983e70687538946bff5d737a08"),
    ("concrete_wall_008_disp_1k.png", 1_108_458, "98c7c2c3cccb4f5992e09c77ee3e6706"),
    ("decrepit_wallpaper_disp_1k.png", 1_473_765, "92590700030fda709fbecf20f2c33653"),
    ("marble_cliff_01_disp_1k.png", 1_494_165, "4a976db8538f16444e54e708d82666c2"),
    ("rusty_metal_03_disp_1k.png", 1_643_570, "6b560f4adaab0a436283c4ccf1692782"),
    ("trident_maple_bark_disp_1k.png", 1_687_901, "4472649d09f2b4fc2c0cb5072f2fb42f"),
    ("gravelly_sand_disp_1k.png", 1_694_619, "592e4c98c6d4ccc821547f5fb9e1e11b"),
    ("denim_fabric_06_disp_1k.png", 1_995_611, "47b98dd5e19439255e76ac66f329c02e"),
)
EXPECTED_STATS = {
    "black_painted_planks_disp_1k.png": (53276, 63711, 8555, 0, 0, 1018468, "f3959efef156e7f78b1317d8d5f4d9fe047f6b3e870214df0dd57931503a47e2"),
    "concrete_wall_008_disp_1k.png": (8961, 47145, 8747, 0, 0, 1044021, "1a5e37c50ed6ae505281b1e23c36afb27137b29019c4afcd39637f1c500b53d2"),
    "decrepit_wallpaper_disp_1k.png": (29764, 40405, 7081, 0, 0, 1043087, "3857b362989346fa4f119f0f1e168ee9e6a957ea62a5eb9e178c522c3a0a785d"),
    "marble_cliff_01_disp_1k.png": (25, 57200, 45464, 0, 0, 1046657, "3bb71868fef9db1c69bbeccd59f4743815e56c360e1f69c86d08ec64940796e2"),
    "rusty_metal_03_disp_1k.png": (11117, 34858, 10331, 0, 0, 1046026, "47ec0dc1c3ab23d8d01c721f29de767923ee6cf0d4615efc963148104f28e85d"),
    "trident_maple_bark_disp_1k.png": (5806, 60860, 34619, 0, 0, 1047855, "5dba6da29ce2e81ba930bf1edbc5c7fdeec1edc2bd685ab814c7f5c1923fd04b"),
    "gravelly_sand_disp_1k.png": (7677, 30534, 15379, 0, 0, 1047401, "de0d15aaf231b9a4049c0f7c0d5cafac783c2e3546f1752f4ca04066a8792a3f"),
    "denim_fabric_06_disp_1k.png": (6374, 53449, 31096, 0, 0, 1048483, "f66b414f5495d10b09136e4aefbda6dc3ea67711f5ec61f88a12515b7c204dbb"),
}


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def decode_png(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name}: invalid PNG signature")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    saw_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError(f"{path.name}: truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError(f"{path.name}: PNG chunk exceeds file bounds")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"{path.name}: CRC mismatch in {chunk_type!r}")
        chunks.append((chunk_type, payload))
        offset = end
        if chunk_type == b"IEND":
            saw_iend = True
            break
    if not saw_iend or offset != len(data):
        raise ValueError(f"{path.name}: missing IEND or trailing data")
    if not chunks or chunks[0][0] != b"IHDR" or sum(kind == b"IHDR" for kind, _ in chunks) != 1:
        raise ValueError(f"{path.name}: invalid IHDR placement/count")
    if sum(kind == b"IEND" for kind, _ in chunks) != 1:
        raise ValueError(f"{path.name}: invalid IEND count")
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise ValueError(f"{path.name}: invalid IHDR size")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    if (width, height, depth, color, compression, filtering, interlace) != (WIDTH, HEIGHT, 16, 0, 0, 0, 0):
        raise ValueError(
            f"{path.name}: expected {WIDTH}x{HEIGHT} grayscale16 non-interlaced PNG, "
            f"got {(width, height, depth, color, compression, filtering, interlace)}"
        )
    idat_indices = [index for index, (kind, _) in enumerate(chunks) if kind == b"IDAT"]
    if not idat_indices or idat_indices != list(range(idat_indices[0], idat_indices[-1] + 1)):
        raise ValueError(f"{path.name}: missing or nonconsecutive IDAT chunks")
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    decoder = zlib.decompressobj()
    filtered = decoder.decompress(compressed) + decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError(f"{path.name}: malformed or trailing zlib stream")
    row_bytes = WIDTH * 2
    expected_filtered = HEIGHT * (row_bytes + 1)
    if len(filtered) != expected_filtered:
        raise ValueError(f"{path.name}: decoded scanline size {len(filtered)} != {expected_filtered}")
    reconstructed = bytearray()
    prior = bytes(row_bytes)
    for row_index in range(HEIGHT):
        start = row_index * (row_bytes + 1)
        filter_type = filtered[start]
        raw = filtered[start + 1 : start + 1 + row_bytes]
        if filter_type > 4:
            raise ValueError(f"{path.name}: invalid PNG filter {filter_type}")
        row = bytearray(row_bytes)
        for index, byte in enumerate(raw):
            left = row[index - 2] if index >= 2 else 0
            up = prior[index]
            upper_left = prior[index - 2] if index >= 2 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            else:
                predictor = paeth(left, up, upper_left)
            row[index] = (byte + predictor) & 0xFF
        reconstructed.extend(row)
        prior = row
    # PNG stores 16-bit samples in network byte order; corpus samples are LE.
    output = bytearray(OUTPUT_BYTES)
    output[0::2] = reconstructed[1::2]
    output[1::2] = reconstructed[0::2]
    return bytes(output)


def source_paths(download_dir: Path) -> list[Path]:
    paths = []
    for name, size, expected_md5 in SOURCES:
        path = download_dir / name
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
        actual_md5 = file_hash(path, "md5")
        if path.stat().st_size != size or actual_md5 != expected_md5:
            raise SystemExit(f"size or MD5 mismatch: {path}")
        paths.append(path)
    return paths


def characterize(path: Path, payload: bytes) -> dict[str, object]:
    values = array("H")
    values.frombytes(payload)
    if values.itemsize != 2:
        raise ValueError("host unsigned-short width is not 16 bits")
    if sys.byteorder == "big":
        values.byteswap()
    distinct = len(set(values))
    zero_count = values.count(0)
    saturated_count = values.count(65535)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if distinct < 256:
        raise ValueError(f"{path.name}: only {distinct} distinct values")
    if zero_count / VALUE_COUNT > 0.99:
        raise ValueError(f"{path.name}: more than 99% zero")
    return {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_md5": file_hash(path, "md5"),
        "width": WIDTH,
        "height": HEIGHT,
        "value_count": VALUE_COUNT,
        "decoded_bytes": OUTPUT_BYTES,
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": distinct,
        "zero_values": zero_count,
        "saturated_values": saturated_count,
        "flattened_transitions": transitions,
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
    }


def inspect_all(download_dir: Path) -> tuple[list[tuple[Path, bytes]], list[dict[str, object]]]:
    decoded = []
    reports = []
    for path in source_paths(download_dir):
        payload = decode_png(path)
        decoded.append((path, payload))
        report = characterize(path, payload)
        observed = (
            report["minimum"],
            report["maximum"],
            report["distinct_values"],
            report["zero_values"],
            report["saturated_values"],
            report["flattened_transitions"],
            report["decoded_sha256"],
        )
        if observed != EXPECTED_STATS[path.name]:
            raise ValueError(f"{path.name}: decoded statistics or hash changed: {observed}")
        reports.append(report)
    return decoded, reports


def inspect_command(args: argparse.Namespace) -> None:
    _decoded, reports = inspect_all(args.download_dir)
    result = {
        "dataset_id": DATASET_ID,
        "sample_count": len(reports),
        "value_count": sum(int(report["value_count"]) for report in reports),
        "total_size_bytes": sum(int(report["decoded_bytes"]) for report in reports),
        "samples": reports,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    decoded, reports = inspect_all(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    rows = []
    for (source, payload), report in zip(decoded, reports):
        stem = source.name.removesuffix(".png")
        output = family_dir / f"{stem}_h{HEIGHT}_w{WIDTH}_u16le.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "source_file": source.name,
            "value_count": VALUE_COUNT,
            "sample_size_bytes": OUTPUT_BYTES,
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "sample_geometry": "2d_material_displacement_map",
            "sample_shape": [HEIGHT, WIDTH],
            "sample_axes": ["texture_y", "texture_x"],
            "natural_record_kind": "material_displacement_map",
            "minimum": report["minimum"],
            "maximum": report["maximum"],
            "distinct_values": report["distinct_values"],
            "sha256": report["decoded_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    aggregate = hashlib.sha256()
    for _source, payload in decoded:
        aggregate.update(payload)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "value_count": len(rows) * VALUE_COUNT,
        "total_size_bytes": len(rows) * OUTPUT_BYTES,
        "aggregate_payload_sha256": aggregate.hexdigest(),
        "source_inspections": reports,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: stats[key] for key in (
        "dataset_id", "sample_count", "value_count", "total_size_bytes", "aggregate_payload_sha256"
    )}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    decoded, _reports = inspect_all(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != len(SOURCES):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs = set()
    aggregate = hashlib.sha256()
    for row, (source, payload) in zip(rows, decoded):
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if row.get("source_file") != source.name or not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output mismatch for {source.name}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch for {source.name}")
        if int(row["value_count"]) != VALUE_COUNT or int(row["sample_size_bytes"]) != OUTPUT_BYTES:
            raise SystemExit(f"indexed totals mismatch for {source.name}")
        aggregate.update(payload)
    actual_outputs = {
        path.resolve()
        for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    expected_values = len(SOURCES) * VALUE_COUNT
    expected_bytes = len(SOURCES) * OUTPUT_BYTES
    if (
        stats.get("sample_count") != len(SOURCES)
        or stats.get("value_count") != expected_values
        or stats.get("total_size_bytes") != expected_bytes
        or stats.get("aggregate_payload_sha256") != aggregate.hexdigest()
    ):
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(SOURCES),
        "verified_values": expected_values,
        "verified_bytes": expected_bytes,
        "aggregate_payload_sha256": aggregate.hexdigest(),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect_command(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
