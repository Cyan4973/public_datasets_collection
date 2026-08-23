#!/usr/bin/env python3
"""Decode and verify pinned Poly Haven achromatic8 roughness JPEGs."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess


DATASET_ID = "polyhaven_material_roughness_u8"
SERIES_ID = "material_roughness_u8"
WIDTH = 1024
HEIGHT = 1024
VALUE_COUNT = WIDTH * HEIGHT
EXPECTED_SAMPLES = 8
MIN_DISTINCT_VALUES = 8
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def jpeg_info(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) < 4 or raw[:2] != b"\xff\xd8" or raw[-2:] != b"\xff\xd9":
        raise ValueError("not a complete JPEG")
    position = 2
    width = height = precision = components = marker_name = None
    while position < len(raw):
        if raw[position] != 0xFF:
            raise ValueError(f"invalid JPEG marker alignment at byte {position}")
        while position < len(raw) and raw[position] == 0xFF:
            position += 1
        if position >= len(raw):
            break
        marker = raw[position]
        position += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if marker == 0xDA:
            break
        if position + 2 > len(raw):
            raise ValueError("truncated JPEG segment length")
        length = struct.unpack_from(">H", raw, position)[0]
        if length < 2 or position + length > len(raw):
            raise ValueError("invalid JPEG segment length")
        if marker in SOF_MARKERS:
            if length < 8:
                raise ValueError("short JPEG SOF segment")
            precision = raw[position + 2]
            height, width = struct.unpack_from(">HH", raw, position + 3)
            components = raw[position + 7]
            marker_name = f"SOF{marker & 0x0F}"
            break
        position += length
    if None in (width, height, precision, components):
        raise ValueError("JPEG has no supported SOF marker")
    if (width, height, precision) != (WIDTH, HEIGHT, 8) or components not in (1, 3):
        raise ValueError(
            f"expected 1024x1024 8-bit one- or three-component JPEG, got "
            f"{width}x{height} precision={precision} components={components}"
        )
    return {
        "width": width,
        "height": height,
        "precision": precision,
        "components": components,
        "sof_marker": marker_name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def decoder() -> tuple[str, str]:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise SystemExit("FFmpeg is required to decode the official JPEG roughness maps")
    completed = subprocess.run(
        [executable, "-version"], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    version = completed.stdout.splitlines()[0].strip()
    if not version.startswith("ffmpeg version "):
        raise SystemExit("unexpected FFmpeg version output")
    return executable, version


def decode_pixels(path: Path, executable: str, components: int) -> tuple[bytes, bool]:
    pixel_format = "gray" if components == 1 else "rgb24"
    command = [
        executable, "-v", "error", "-nostdin", "-threads", "1",
        "-flags", "+bitexact", "-i", str(path), "-map", "0:v:0",
        "-frames:v", "1", "-sws_flags", "bitexact+accurate_rnd",
        "-pix_fmt", pixel_format, "-f", "rawvideo", "-",
    ]
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    expected_size = VALUE_COUNT * components
    if len(completed.stdout) != expected_size:
        raise SystemExit(f"decoded {pixel_format} size mismatch for {path.name}: {len(completed.stdout)}")
    if components == 1:
        return completed.stdout, False
    rgb = completed.stdout
    if any(rgb[offset] != rgb[offset + 1] or rgb[offset] != rgb[offset + 2]
           for offset in range(0, len(rgb), 3)):
        raise SystemExit(f"three-component roughness JPEG is not exactly achromatic: {path.name}")
    return rgb[0::3], True


def load_plan(path: Path, download_dir: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_SAMPLES or len({row["asset_id"] for row in rows}) != EXPECTED_SAMPLES:
        raise SystemExit("roughness selection must contain eight unique assets")
    result = []
    for row in rows:
        source = download_dir / row["filename"]
        expected_size = int(row["bytes"])
        if not source.is_file() or source.stat().st_size != expected_size:
            raise SystemExit(f"missing or size-mismatched source: {source}")
        if file_hash(source, "md5") != row["md5"]:
            raise SystemExit(f"source MD5 mismatch: {source}")
        result.append({**row, "bytes": expected_size, "path": source})
    return result


def collect(plan: Path, download_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    sources = load_plan(plan, download_dir)
    executable, version = decoder()
    decoded = []
    reports = []
    hashes = set()
    for source in sources:
        try:
            header = jpeg_info(source["path"])
            payload, achromatic_rgb_verified = decode_pixels(
                source["path"], executable, int(header["components"])
            )
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise SystemExit(f"failed to decode {source['filename']}: {exc}") from exc
        digest = hashlib.sha256(payload).hexdigest()
        counts = Counter(payload)
        distinct = len(counts)
        dominant = max(counts.values())
        transitions = sum(left != right for left, right in zip(payload, payload[1:]))
        if (distinct < MIN_DISTINCT_VALUES or dominant / len(payload) > 0.99
                or transitions < 10_000):
            raise SystemExit(f"degenerate roughness map: {source['filename']}")
        if digest in hashes:
            raise SystemExit(f"duplicate decoded roughness plane: {source['filename']}")
        hashes.add(digest)
        decoded.append({**source, "payload": payload})
        reports.append({
            "asset_id": source["asset_id"],
            "source_file": source["filename"],
            "source_bytes": source["bytes"],
            "source_md5": source["md5"],
            **header,
            "achromatic_rgb_verified": achromatic_rgb_verified,
            "value_count": len(payload),
            "minimum": min(payload),
            "maximum": max(payload),
            "distinct_values": distinct,
            "dominant_value_count": dominant,
            "transition_count": transitions,
            "decoded_sha256": digest,
        })
    return decoded, reports, version


def summary(reports: list[dict[str, object]], version: str) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "value_count": len(reports) * VALUE_COUNT,
        "total_size_bytes": len(reports) * VALUE_COUNT,
        "decoder": version,
        "samples": reports,
    }


def inspect(args: argparse.Namespace) -> None:
    _decoded, reports, version = collect(args.plan, args.download_dir)
    result = summary(reports, version)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    decoded, reports, version = collect(args.plan, args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for source, report in zip(decoded, reports, strict=True):
        output = series_dir / f"{source['asset_id']}_rough_1k_u8.bin"
        output.write_bytes(source["payload"])
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source["path"].relative_to(args.data_root).as_posix(),
            "source_file": source["filename"],
            "asset_id": source["asset_id"],
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": VALUE_COUNT,
            "sample_size_bytes": VALUE_COUNT,
            "sample_format": "raw homogeneous uint8 material roughness plane",
            "sample_geometry": "2d_material_roughness_map",
            "sample_rank": 2,
            "sample_shape": [HEIGHT, WIDTH],
            "sample_axes": ["texture_y", "texture_x"],
            "natural_record_kind": "material_roughness_map",
            "minimum": report["minimum"],
            "maximum": report["maximum"],
            "distinct_values": report["distinct_values"],
            "sha256": report["decoded_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = summary(reports, version)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    decoded, reports, version = collect(args.plan, args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(decoded) or json.loads(args.stats.read_text(encoding="utf-8")) != summary(reports, version):
        raise SystemExit("index/stats differ from fresh source decode")
    expected_outputs = set()
    for source, row in zip(decoded, rows, strict=True):
        payload = source["payload"]
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit("dataset/series/role mismatch")
        if row.get("asset_id") != source["asset_id"] or row.get("source_file") != source["filename"]:
            raise SystemExit("source identity mismatch")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little" or row.get("element_size_bytes") != 1:
            raise SystemExit("numeric schema mismatch")
        if row.get("sample_shape") != [HEIGHT, WIDTH] or row.get("value_count") != VALUE_COUNT:
            raise SystemExit("sample geometry mismatch")
        output = args.data_root / row["sample_path"]
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh JPEG decode: {output}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch: {output}")
        expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(rows),
        "verified_values": len(rows) * VALUE_COUNT,
        "verified_bytes": len(rows) * VALUE_COUNT,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--plan", type=Path, required=True)
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--plan", type=Path, required=True)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
