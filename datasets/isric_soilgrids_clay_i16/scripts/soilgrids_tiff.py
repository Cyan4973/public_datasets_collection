#!/usr/bin/env python3
"""Decode and verify uncompressed native-int16 SoilGrids GeoTIFF tiles."""
from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys


DATASET_ID = "isric_soilgrids_clay_i16"
SERIES_ID = "soilgrids_clay_0_5cm_mean_i16"
EXPECTED_FILES = 256
WIDTH = 450
HEIGHT = 450
VALUES_PER_TILE = WIDTH * HEIGHT
BYTES_PER_TILE = VALUES_PER_TILE * 2
EXPECTED_PRIMARY_VALUES = EXPECTED_FILES * VALUES_PER_TILE
EXPECTED_PRIMARY_BYTES = EXPECTED_FILES * BYTES_PER_TILE
NODATA = -32_768
TYPE_WIDTHS = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sources(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    if len(raw) != EXPECTED_FILES:
        raise SystemExit("source-plan count changed")
    rows = []
    for ordinal, row in enumerate(raw, 1):
        if int(row["selection_ordinal"]) != ordinal:
            raise SystemExit("source-plan ordinal changed")
        if int(row["source_x_size"]) != WIDTH or int(row["source_y_size"]) != HEIGHT:
            raise SystemExit("source-plan geometry changed")
        if row["source_data_type"] != "Int16" or int(row["decoded_bytes"]) != BYTES_PER_TILE:
            raise SystemExit("source-plan type or decoded size changed")
        if len(row["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in row["sha256"]):
            raise SystemExit("source-plan SHA256 is invalid")
        rows.append({
            "decoded_bytes": int(row["decoded_bytes"]),
            "filename": row["filename"],
            "selection_ordinal": ordinal,
            "sha256": row["sha256"],
            "source_bytes": int(row["source_bytes"]),
            "url": row["url"],
            "x_offset": int(row["x_offset"]),
            "y_offset": int(row["y_offset"]),
        })
    return rows


def load_inventory(
    download_dir: Path, sources_path: Path, sources: list[dict[str, object]]
) -> list[dict[str, object]]:
    payload = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_FILES:
        raise SystemExit("download inventory count changed")
    if int(payload.get("decoded_bytes", 0)) != EXPECTED_PRIMARY_BYTES:
        raise SystemExit("download inventory decoded-byte total changed")
    if int(payload.get("source_bytes", 0)) != 104_067_284:
        raise SystemExit("download inventory source-byte total changed")
    if payload.get("source_plan_sha256") != hashlib.sha256(sources_path.read_bytes()).hexdigest():
        raise SystemExit("download inventory was not built from this pinned source plan")
    for source, record in zip(sources, records):
        for key in ("filename", "selection_ordinal", "url", "x_offset", "y_offset", "decoded_bytes"):
            if source[key] != record.get(key):
                raise SystemExit(f"download inventory differs from source plan: {key}")
        if source["source_bytes"] != record.get("source_bytes") or source["sha256"] != record.get("sha256"):
            raise SystemExit("download inventory source identity differs from pinned plan")
        path = download_dir / str(source["filename"])
        if path.name != source["filename"]:
            raise SystemExit("unsafe source filename")
        if path.stat().st_size != int(record["source_bytes"]):
            raise SystemExit(f"source size mismatch: {path.name}")
        if sha256_file(path) != record["sha256"]:
            raise SystemExit(f"source SHA256 mismatch: {path.name}")
    return records


def parse_ifd(data: bytes) -> tuple[str, dict[int, tuple[int, int, bytes]]]:
    if len(data) < 8 or data[:2] not in {b"II", b"MM"}:
        raise ValueError("not a TIFF file")
    endian = "<" if data[:2] == b"II" else ">"
    if struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise ValueError("not classic TIFF")
    ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
    if ifd_offset + 2 > len(data):
        raise ValueError("IFD outside source")
    entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
    if entry_count > 512 or ifd_offset + 2 + entry_count * 12 + 4 > len(data):
        raise ValueError("invalid TIFF IFD size")
    tags: dict[int, tuple[int, int, bytes]] = {}
    for index in range(entry_count):
        position = ifd_offset + 2 + index * 12
        tag, value_type, count = struct.unpack_from(endian + "HHI", data, position)
        width = TYPE_WIDTHS.get(value_type)
        if width is None or count > 1_000_000:
            raise ValueError(f"unsupported TIFF field type/count for tag {tag}")
        byte_count = width * count
        if byte_count <= 4:
            offset = position + 8
        else:
            offset = struct.unpack_from(endian + "I", data, position + 8)[0]
        if offset + byte_count > len(data):
            raise ValueError(f"TIFF tag payload outside source: {tag}")
        tags[tag] = (value_type, count, data[offset:offset + byte_count])
    return endian, tags


def integer_values(tags: dict[int, tuple[int, int, bytes]], tag: int, endian: str) -> list[int]:
    if tag not in tags:
        raise ValueError(f"missing TIFF tag {tag}")
    value_type, count, payload = tags[tag]
    format_code = TYPE_FORMATS.get(value_type)
    if format_code is None or value_type in {11, 12}:
        raise ValueError(f"TIFF tag {tag} is not integer-valued")
    return [int(value) for value in struct.unpack(endian + str(count) + format_code, payload)]


def scalar(
    tags: dict[int, tuple[int, int, bytes]], tag: int, endian: str, default: int | None = None
) -> int:
    if tag not in tags:
        if default is None:
            raise ValueError(f"missing TIFF scalar tag {tag}")
        return default
    values = integer_values(tags, tag, endian)
    if len(values) != 1:
        raise ValueError(f"TIFF tag {tag} is not scalar")
    return values[0]


def ascii_value(tags: dict[int, tuple[int, int, bytes]], tag: int) -> str:
    if tag not in tags:
        raise ValueError(f"missing TIFF ASCII tag {tag}")
    value_type, _, payload = tags[tag]
    if value_type != 2:
        raise ValueError(f"TIFF tag {tag} is not ASCII")
    return payload.rstrip(b"\x00").decode("ascii", "strict")


def decode_tiff(path: Path) -> tuple[bytes, dict[str, object]]:
    data = path.read_bytes()
    endian, tags = parse_ifd(data)
    if endian != "<":
        raise ValueError("SoilGrids source is not little-endian TIFF")
    expected_scalars = {
        256: WIDTH, 257: HEIGHT, 258: 16, 259: 1, 262: 1,
        266: 1, 274: 1, 277: 1, 278: 9, 284: 1, 317: 1, 339: 2,
    }
    defaults = {266: 1, 274: 1, 284: 1, 317: 1}
    for tag, expected in expected_scalars.items():
        if scalar(tags, tag, endian, defaults.get(tag)) != expected:
            raise ValueError(f"unexpected TIFF tag {tag}")
    if ascii_value(tags, 42113).strip() != str(NODATA):
        raise ValueError("unexpected GDAL nodata declaration")
    offsets = integer_values(tags, 273, endian)
    byte_counts = integer_values(tags, 279, endian)
    expected_strips = (HEIGHT + 8) // 9
    if len(offsets) != expected_strips or len(byte_counts) != expected_strips:
        raise ValueError("unexpected TIFF strip count")
    parts = []
    regions = []
    for index, (offset, byte_count) in enumerate(zip(offsets, byte_counts)):
        rows = min(9, HEIGHT - index * 9)
        expected_bytes = rows * WIDTH * 2
        if byte_count != expected_bytes or offset + byte_count > len(data):
            raise ValueError("invalid uncompressed TIFF strip bounds")
        regions.append((offset, offset + byte_count))
        parts.append(data[offset:offset + byte_count])
    for (_, end), (next_start, _) in zip(sorted(regions), sorted(regions)[1:]):
        if end > next_start:
            raise ValueError("overlapping TIFF strips")
    decoded = b"".join(parts)
    if len(decoded) != BYTES_PER_TILE:
        raise ValueError("decoded TIFF byte count changed")
    values = array("h")
    values.frombytes(decoded)
    if sys.byteorder != "little":
        values.byteswap()
    nodata_count = values.count(NODATA)
    valid = [value for value in values if value != NODATA]
    if not valid:
        raise ValueError("tile contains only nodata")
    valid_minimum = min(valid)
    valid_maximum = max(valid)
    if valid_minimum < 0 or valid_maximum > 1000 or valid_minimum >= valid_maximum:
        raise ValueError("implausible or degenerate clay-content code range")
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if distinct < 3 or transitions == 0:
        raise ValueError("degenerate clay tile")
    return decoded, {
        "distinct_values": distinct,
        "maximum": max(values),
        "minimum": min(values),
        "nodata_count": nodata_count,
        "sha256": hashlib.sha256(decoded).hexdigest(),
        "transition_count": transitions,
        "valid_count": len(valid),
        "valid_maximum": valid_maximum,
        "valid_minimum": valid_minimum,
        "value_count": len(values),
    }


def collect(
    *,
    mode: str,
    sources_path: Path,
    download_dir: Path,
    samples_dir: Path,
    data_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    sources = parse_sources(sources_path)
    inventory = load_inventory(download_dir, sources_path, sources)
    if mode == "build":
        if samples_dir.exists():
            for path in samples_dir.glob("*.bin"):
                path.unlink()
        samples_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    details = []
    output_hashes = set()
    for source, record in zip(sources, inventory):
        source_path = download_dir / str(source["filename"])
        decoded, result = decode_tiff(source_path)
        output = samples_dir / (source_path.stem + ".bin")
        if mode == "build":
            output.write_bytes(decoded)
        elif output.read_bytes() != decoded:
            raise ValueError(f"built sample differs from TIFF decode: {output.name}")
        if result["sha256"] in output_hashes:
            raise ValueError("duplicate complete SoilGrids tile")
        output_hashes.add(result["sha256"])
        detail = {
            "filename": source["filename"],
            "selection_ordinal": source["selection_ordinal"],
            "source_bytes": record["source_bytes"],
            "source_sha256": record["sha256"],
            "x_offset": source["x_offset"],
            "y_offset": source["y_offset"],
            **result,
        }
        details.append(detail)
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "distinct_values": result["distinct_values"],
            "element_size_bytes": 2,
            "endianness": "little",
            "maximum": result["maximum"],
            "minimum": result["minimum"],
            "natural_record_kind": "complete_soilgrids_source_tiff_tile",
            "nodata_count": result["nodata_count"],
            "nodata_value": NODATA,
            "numeric_kind": "int",
            "role": "primary",
            "sample_axes": ["projected_y", "projected_x"],
            "sample_format": "raw homogeneous little-endian signed-int16 raster tile",
            "sample_geometry": "fixed_450x450_soil_property_raster",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 2,
            "sample_shape": [HEIGHT, WIDTH],
            "sample_size_bytes": len(decoded),
            "selection_ordinal": source["selection_ordinal"],
            "semantic_field": "mean_clay_content_0_to_5cm",
            "series_id": SERIES_ID,
            "sha256": result["sha256"],
            "source_sample": source_path.relative_to(data_root).as_posix(),
            "source_variable": "GeoTIFF band 1",
            "transition_count": result["transition_count"],
            "valid_count": result["valid_count"],
            "value_count": result["value_count"],
            "x_offset_in_global_vrt": source["x_offset"],
            "y_offset_in_global_vrt": source["y_offset"],
        })
    expected_names = {Path(str(source["filename"])).stem + ".bin" for source in sources}
    actual_names = {path.name for path in samples_dir.glob("*.bin")}
    if actual_names != expected_names:
        raise SystemExit("sample directory differs from source plan")
    if len(entries) != EXPECTED_FILES:
        raise SystemExit("selected tile count changed")
    if sum(int(entry["value_count"]) for entry in entries) != EXPECTED_PRIMARY_VALUES:
        raise SystemExit("aggregate value count changed")
    if sum(int(entry["sample_size_bytes"]) for entry in entries) != EXPECTED_PRIMARY_BYTES:
        raise SystemExit("aggregate primary byte count changed")
    stats = {
        "candidate_id": DATASET_ID,
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "global_valid_maximum": max(int(detail["valid_maximum"]) for detail in details),
        "global_valid_minimum": min(int(detail["valid_minimum"]) for detail in details),
        "primary_bytes": EXPECTED_PRIMARY_BYTES,
        "primary_values": EXPECTED_PRIMARY_VALUES,
        "records": details,
        "samples": len(entries),
        "series_id": SERIES_ID,
        "source_bytes": sum(int(record["source_bytes"]) for record in inventory),
        "source_files": len(inventory),
        "total_nodata_count": sum(int(entry["nodata_count"]) for entry in entries),
        "total_transition_count": sum(int(entry["transition_count"]) for entry in entries),
        "valid_values": sum(int(entry["valid_count"]) for entry in entries),
        "values_per_tile": VALUES_PER_TILE,
    }
    return entries, stats


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "verify" and not args.samples_dir.is_dir():
        raise SystemExit("missing built sample directory")
    entries, stats = collect(
        mode=args.mode,
        sources_path=args.sources,
        download_dir=args.download_dir,
        samples_dir=args.samples_dir,
        data_root=args.data_root,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independent TIFF decode")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independent TIFF decode")
    print(
        f"mode={args.mode} samples={stats['samples']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} valid_values={stats['valid_values']} "
        f"nodata={stats['total_nodata_count']}"
    )


if __name__ == "__main__":
    main()
