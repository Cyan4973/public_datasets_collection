#!/usr/bin/env python3
"""Decode the evaluation-only Kodak true-color PNGs without external dependencies."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LANDSCAPE_SHAPE = (768, 512)
PORTRAIT_SHAPE = (512, 768)
PIXELS = 768 * 512
DATASET_ID = "kodak_photo_suite_eval_u8"
SERIES_ID = "kodak_rgb_plane_u8"
IMAGE_COUNT = 24
SAMPLE_COUNT = 72
TOTAL_VALUES = IMAGE_COUNT * PIXELS * 3
CHANNELS = (("red", 0), ("green", 1), ("blue", 2))
RECIPE_DIR = Path(__file__).resolve().parents[1]


def paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def decode_png(path: Path) -> tuple[int, int, bytes]:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError("invalid PNG signature")
    position = len(PNG_SIGNATURE)
    width = height = None
    idat = bytearray()
    saw_iend = False
    while position < len(raw):
        if position + 12 > len(raw):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack_from(">I", raw, position)[0]
        kind = raw[position + 4 : position + 8]
        payload_start = position + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(raw):
            raise ValueError("PNG chunk exceeds source size")
        payload = raw[payload_start:payload_end]
        expected_crc = struct.unpack_from(">I", raw, payload_end)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError(f"PNG CRC mismatch for {kind!r}")
        if kind == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("invalid or repeated PNG IHDR")
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (depth, color_type, compression, filtering, interlace) != (8, 2, 0, 0, 0):
                raise ValueError(
                    f"expected noninterlaced 8-bit true-color PNG, got "
                    f"depth/type/compression/filter/interlace={(depth,color_type,compression,filtering,interlace)}"
                )
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            if length != 0 or crc_end != len(raw):
                raise ValueError("invalid PNG IEND or trailing bytes")
            saw_iend = True
            break
        position = crc_end
    if width is None or height is None or not idat or not saw_iend:
        raise ValueError("incomplete PNG structure")
    if (width, height) not in {LANDSCAPE_SHAPE, PORTRAIT_SHAPE}:
        raise ValueError(f"unexpected dimensions: {width}x{height}")
    stride = width * 3
    filtered = zlib.decompress(bytes(idat))
    if len(filtered) != height * (stride + 1):
        raise ValueError("unexpected decompressed PNG size")
    output = bytearray(height * stride)
    prior = bytearray(stride)
    source_position = 0
    for y in range(height):
        filter_type = filtered[source_position]
        source_position += 1
        encoded = filtered[source_position : source_position + stride]
        source_position += stride
        row = bytearray(stride)
        for x, value in enumerate(encoded):
            left = row[x - 3] if x >= 3 else 0
            above = prior[x]
            upper_left = prior[x - 3] if x >= 3 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = paeth(left, above, upper_left)
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}")
            row[x] = (value + predictor) & 0xFF
        start = y * stride
        output[start : start + stride] = row
        prior = row
    return width, height, bytes(output)


def source_info(path: Path) -> None:
    width, height, rgb = decode_png(path)
    raw = path.read_bytes()
    print(
        f"{width}\t{height}\t{len(raw)}\t{hashlib.sha256(raw).hexdigest()}\t"
        f"{hashlib.sha256(rgb).hexdigest()}"
    )


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sources(eval_root: Path) -> list[dict[str, object]]:
    download_dir = eval_root / "downloads"
    inventory_path = download_dir / "acquisition.tsv"
    if not inventory_path.is_file():
        raise SystemExit("missing acquisition inventory; run download.sh first")
    with (RECIPE_DIR / "selection.tsv").open(encoding="utf-8", newline="") as handle:
        selected = list(csv.DictReader(handle, delimiter="\t"))
    with inventory_path.open(encoding="utf-8", newline="") as handle:
        inventory = list(csv.DictReader(handle, delimiter="\t"))
    if len(selected) != IMAGE_COUNT or len(inventory) != IMAGE_COUNT:
        raise SystemExit("selection and acquisition inventory must each contain 24 rows")
    sources = []
    for selection, acquired in zip(selected, inventory, strict=True):
        for key in (
            "image_id", "image_name", "width", "height", "source_size_bytes",
            "source_sha256", "decoded_rgb_sha256", "url",
        ):
            if selection[key] != acquired[key]:
                raise SystemExit(f"selection/inventory mismatch for {key}")
        if (int(acquired["width"]), int(acquired["height"])) not in {LANDSCAPE_SHAPE, PORTRAIT_SHAPE}:
            raise SystemExit(f"unexpected dimensions for {acquired['image_name']}")
        path = download_dir / acquired["image_name"]
        if not path.is_file() or path.stat().st_size != int(acquired["source_size_bytes"]):
            raise SystemExit(f"missing or wrong-sized source {acquired['image_name']}")
        if file_hash(path) != acquired["source_sha256"]:
            raise SystemExit(f"source SHA-256 mismatch for {acquired['image_name']}")
        try:
            width, height, rgb = decode_png(path)
        except (OSError, ValueError, zlib.error) as error:
            raise SystemExit(f"invalid source {path}: {error}") from error
        if hashlib.sha256(rgb).hexdigest() != acquired["decoded_rgb_sha256"]:
            raise SystemExit(f"decoded RGB identity mismatch for {acquired['image_name']}")
        sources.append({
            "image_id": acquired["image_id"],
            "image_name": acquired["image_name"],
            "url": acquired["url"],
            "width": width,
            "height": height,
            "source_size_bytes": int(acquired["source_size_bytes"]),
            "source_sha256": acquired["source_sha256"],
            "decoded_rgb_sha256": acquired["decoded_rgb_sha256"],
            "rgb": rgb,
        })
    return sources


def plane_stats(payload: bytes) -> dict[str, object]:
    minimum = min(payload)
    maximum = max(payload)
    distinct = len(set(payload))
    if maximum - minimum < 128 or distinct < 128:
        raise SystemExit(
            f"degenerate Kodak plane: minimum={minimum} maximum={maximum} distinct={distinct}"
        )
    return {
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
    }


def decoded_planes(sources: list[dict[str, object]]):
    for source in sources:
        rgb = source["rgb"]
        for channel, offset in CHANNELS:
            payload = rgb[offset::3]
            yield source, channel, payload, plane_stats(payload)


def make_summary(sources: list[dict[str, object]], profiles: list[dict[str, object]]) -> dict[str, object]:
    if len(profiles) != SAMPLE_COUNT or len({row["sha256"] for row in profiles}) != SAMPLE_COUNT:
        raise SystemExit("unexpected or duplicate decoded planes")
    values = sum(int(row["value_count"]) for row in profiles)
    if values != TOTAL_VALUES:
        raise SystemExit(f"unexpected decoded value count: {values}")
    return {
        "dataset_id": DATASET_ID,
        "intended_use": "evaluation_only",
        "training_eligible": False,
        "redistribution_authorized": False,
        "source_image_count": len(sources),
        "sample_count": len(profiles),
        "value_count": values,
        "total_size_bytes": values,
        "source_sha256": {row["image_name"]: row["source_sha256"] for row in sources},
        "profiles": profiles,
    }


def inspect(eval_root: Path) -> None:
    sources = load_sources(eval_root)
    profiles = []
    for source, channel, _payload, stats in decoded_planes(sources):
        profiles.append({
            "image_id": source["image_id"], "channel": channel,
            "width": source["width"], "height": source["height"], "value_count": PIXELS, **stats,
        })
    print(json.dumps(make_summary(sources, profiles), indent=2, sort_keys=True))


def build(eval_root: Path) -> None:
    sources = load_sources(eval_root)
    samples_root = eval_root / "samples"
    series_dir = samples_root / SERIES_ID
    if samples_root.exists():
        shutil.rmtree(samples_root)
    series_dir.mkdir(parents=True)
    rows = []
    profiles = []
    for source, channel, payload, stats in decoded_planes(sources):
        output = series_dir / f"kodim{source['image_id']}_{channel}_u8.bin"
        output.write_bytes(payload)
        profile = {
            "image_id": source["image_id"], "channel": channel,
            "width": source["width"], "height": source["height"], "value_count": len(payload), **stats,
        }
        profiles.append(profile)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "evaluation",
            "intended_use": "evaluation_only",
            "training_eligible": False,
            "sample_path": output.relative_to(eval_root).as_posix(),
            "source_sample": f"downloads/{source['image_name']}",
            "image_id": source["image_id"],
            "channel": channel,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(payload),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous uint8 Kodak photograph color plane",
            "sample_geometry": "2d_photo_color_plane",
            "sample_rank": 2,
            "sample_shape": [source["height"], source["width"]],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "decoded_photo_color_plane",
            **stats,
        })
    result = make_summary(sources, profiles)
    index = eval_root / "index" / "samples.jsonl"
    stats_path = eval_root / "filtered" / "ingest_stats.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "profiles"}, indent=2, sort_keys=True))


def verify(eval_root: Path) -> None:
    sources = load_sources(eval_root)
    index = eval_root / "index" / "samples.jsonl"
    stats_path = eval_root / "filtered" / "ingest_stats.json"
    if not index.is_file() or not stats_path.is_file():
        raise SystemExit("missing evaluation index or stats; run build.sh first")
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != SAMPLE_COUNT:
        raise SystemExit("unexpected evaluation index row count")
    profiles = []
    expected_outputs: set[Path] = set()
    for row, decoded in zip(rows, decoded_planes(sources), strict=True):
        source, channel, payload, stats = decoded
        if row.get("role") != "evaluation" or row.get("intended_use") != "evaluation_only":
            raise SystemExit("evaluation isolation metadata changed")
        if row.get("training_eligible") is not False:
            raise SystemExit("Kodak evaluation sample became training-eligible")
        if row.get("image_id") != source["image_id"] or row.get("channel") != channel:
            raise SystemExit("evaluation index ordering changed")
        if row.get("sample_shape") != [source["height"], source["width"]] or row.get("numeric_kind") != "uint":
            raise SystemExit("evaluation sample representation changed")
        output = eval_root / row["sample_path"]
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"evaluation output differs for {source['image_name']} {channel}")
        if row.get("sha256") != stats["sha256"]:
            raise SystemExit("evaluation index hash changed")
        profiles.append({
            "image_id": source["image_id"], "channel": channel,
            "width": source["width"], "height": source["height"], "value_count": len(payload), **stats,
        })
    actual_outputs = {path.resolve() for path in (eval_root / "samples").glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("evaluation sample directory contains stale or extra outputs")
    expected_summary = make_summary(sources, profiles)
    if json.loads(stats_path.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("evaluation ingest stats differ from fresh decode")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "intended_use": "evaluation_only",
        "verified_samples": SAMPLE_COUNT,
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_VALUES,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    info = subparsers.add_parser("source-info")
    info.add_argument("path", type=Path)
    for command in ("inspect", "build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--eval-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "source-info":
        try:
            source_info(args.path)
        except (OSError, ValueError, zlib.error) as error:
            raise SystemExit(f"invalid Kodak PNG {args.path}: {error}") from error
    elif args.command == "inspect":
        inspect(args.eval_root)
    elif args.command == "build":
        build(args.eval_root)
    else:
        verify(args.eval_root)


if __name__ == "__main__":
    main()
