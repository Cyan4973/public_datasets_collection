#!/usr/bin/env python3
"""Decode pinned Met Open Access painting JPEGs into separate uint8 RGB planes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import zlib


DATASET_ID = "met_open_access_paintings_u8"
SERIES_ID = "met_painting_rgb_plane_u8"
IMAGE_COUNT = 10
SAMPLE_COUNT = 30
TOTAL_VALUES = 329_612_454
TOTAL_BYTES = TOTAL_VALUES
CHANNELS = (("red", 0), ("green", 1), ("blue", 2))
RECIPE_DIR = Path(__file__).resolve().parents[1]


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection() -> list[dict[str, object]]:
    with (RECIPE_DIR / "selection.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "topic", "object_id", "image_name", "width", "height", "size_bytes",
        "sha256", "primary_image_url", "object_url",
    }
    if len(rows) != IMAGE_COUNT or not rows or set(rows[0]) != required:
        raise SystemExit("selection must contain ten rows with the exact schema")
    result: list[dict[str, object]] = []
    for row in rows:
        parsed: dict[str, object] = dict(row)
        for key in ("object_id", "width", "height", "size_bytes"):
            parsed[key] = int(row[key])
        result.append(parsed)
    if len({int(row["object_id"]) for row in result}) != IMAGE_COUNT:
        raise SystemExit("selection contains duplicate object IDs")
    if sum(int(row["width"]) * int(row["height"]) * 3 for row in result) != TOTAL_BYTES:
        raise SystemExit("selection dimensions no longer match the pinned output size")
    return result


def load_expected_planes() -> dict[tuple[int, str], dict[str, object]]:
    with (RECIPE_DIR / "expected_planes.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {"object_id", "channel", "width", "height", "value_count", "sha256"}
    if len(rows) != SAMPLE_COUNT or not rows or set(rows[0]) != required:
        raise SystemExit("expected plane table must contain 30 rows with the exact schema")
    result = {}
    for row in rows:
        key = (int(row["object_id"]), row["channel"])
        if key in result or row["channel"] not in {name for name, _offset in CHANNELS}:
            raise SystemExit(f"duplicate or invalid expected plane key: {key}")
        result[key] = {
            "width": int(row["width"]),
            "height": int(row["height"]),
            "value_count": int(row["value_count"]),
            "sha256": row["sha256"],
        }
    return result


def validate_policy(download_dir: Path) -> None:
    path = download_dir / "metadata" / "open_access_policy.html"
    if not path.is_file():
        raise SystemExit("missing Met Open Access policy evidence; run download.sh first")
    text = html.unescape(re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8"))).lower()
    text = re.sub(r"\s+", " ", text)
    if "open access" not in text or "public domain" not in text:
        raise SystemExit("Met Open Access policy evidence changed")
    if "creative commons zero" not in text and "cc0" not in text:
        raise SystemExit("Met policy evidence no longer identifies CC0")


def validate_sources(download_dir: Path) -> list[dict[str, object]]:
    validate_policy(download_dir)
    sources = []
    for row in load_selection():
        object_id = int(row["object_id"])
        image = download_dir / str(row["image_name"])
        metadata_path = download_dir / "metadata" / f"{object_id}.json"
        if not image.is_file() or image.stat().st_size != int(row["size_bytes"]):
            raise SystemExit(f"missing or wrong-sized image for object {object_id}")
        if hash_file(image) != row["sha256"]:
            raise SystemExit(f"source SHA-256 mismatch for object {object_id}")
        if not metadata_path.is_file():
            raise SystemExit(f"missing object metadata for {object_id}")
        obj = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(obj.get("objectID", 0)) != object_id:
            raise SystemExit(f"metadata identity mismatch for object {object_id}")
        if obj.get("department") != "European Paintings" or obj.get("classification") != "Paintings":
            raise SystemExit(f"object {object_id} is no longer classified as a European painting")
        if obj.get("isPublicDomain") is not True:
            raise SystemExit(f"object {object_id} is no longer marked public domain")
        if obj.get("primaryImage") != row["primary_image_url"] or obj.get("objectURL") != row["object_url"]:
            raise SystemExit(f"image or provenance URL changed for object {object_id}")
        sources.append({
            **row,
            "image_path": image,
            "title": str(obj.get("title", "")).strip(),
            "artist": str(obj.get("artistDisplayName", "")).strip(),
            "object_date": str(obj.get("objectDate", "")).strip(),
            "medium": str(obj.get("medium", "")).strip(),
        })
    return sources


def decoder() -> tuple[str, str]:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise SystemExit("FFmpeg is required to decode the pinned JPEG sources")
    completed = subprocess.run(
        [executable, "-version"], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    version = completed.stdout.splitlines()[0].strip()
    if not version.startswith("ffmpeg version "):
        raise SystemExit("unexpected FFmpeg version output")
    return executable, version


def decode_rgb(source: dict[str, object], executable: str) -> bytes:
    command = [
        executable, "-v", "error", "-nostdin", "-threads", "1",
        "-flags", "+bitexact", "-i", str(source["image_path"]),
        "-map", "0:v:0", "-frames:v", "1",
        "-sws_flags", "bitexact+accurate_rnd+full_chroma_int",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    expected = int(source["width"]) * int(source["height"]) * 3
    if len(completed.stdout) != expected:
        raise SystemExit(
            f"decoded RGB size mismatch for object {source['object_id']}: "
            f"{len(completed.stdout)} != {expected}"
        )
    return completed.stdout


def plane_stats(payload: bytes) -> dict[str, object]:
    minimum = min(payload)
    maximum = max(payload)
    distinct = len(set(payload))
    if maximum - minimum < 128 or distinct < 128:
        raise SystemExit(
            f"degenerate decoded plane: minimum={minimum} maximum={maximum} distinct={distinct}"
        )
    return {
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
    }


def decoded_planes(sources: list[dict[str, object]], executable: str):
    expected_planes = load_expected_planes()
    seen: set[tuple[int, str]] = set()
    for source in sources:
        rgb = decode_rgb(source, executable)
        for channel, offset in CHANNELS:
            payload = rgb[offset::3]
            stats = plane_stats(payload)
            key = (int(source["object_id"]), channel)
            expected = expected_planes.get(key)
            actual = {
                "width": source["width"],
                "height": source["height"],
                "value_count": len(payload),
                "sha256": stats["sha256"],
            }
            if expected != actual:
                raise SystemExit(f"decoded plane identity changed for object/channel {key}: {actual} != {expected}")
            seen.add(key)
            yield source, channel, payload, stats
    if seen != set(expected_planes):
        raise SystemExit("decoded plane keys do not match the pinned table")


def profile(source: dict[str, object], channel: str, stats: dict[str, object]) -> dict[str, object]:
    return {
        "object_id": source["object_id"],
        "topic": source["topic"],
        "title": source["title"],
        "artist": source["artist"],
        "channel": channel,
        "width": source["width"],
        "height": source["height"],
        "value_count": int(source["width"]) * int(source["height"]),
        **stats,
    }


def summary(
    sources: list[dict[str, object]], profiles: list[dict[str, object]], version: str
) -> dict[str, object]:
    if len(profiles) != SAMPLE_COUNT or len({str(row["sha256"]) for row in profiles}) != SAMPLE_COUNT:
        raise SystemExit("decoded plane count or uniqueness changed")
    value_count = sum(int(row["value_count"]) for row in profiles)
    if value_count != TOTAL_VALUES:
        raise SystemExit(f"decoded value count changed: {value_count} != {TOTAL_VALUES}")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_image_count": len(sources),
        "sample_count": len(profiles),
        "value_count": value_count,
        "total_size_bytes": value_count,
        "ffmpeg_version": version,
        "decoder_parameters": [
            "-threads", "1", "-flags", "+bitexact",
            "-sws_flags", "bitexact+accurate_rnd+full_chroma_int",
            "-pix_fmt", "rgb24",
        ],
        "source_sha256": {str(row["object_id"]): row["sha256"] for row in sources},
        "profiles": profiles,
    }


def inspect(args: argparse.Namespace) -> None:
    sources = validate_sources(args.download_dir)
    executable, version = decoder()
    profiles = [profile(source, channel, stats) for source, channel, _payload, stats in decoded_planes(sources, executable)]
    print(json.dumps(summary(sources, profiles, version), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    sources = validate_sources(args.download_dir)
    executable, version = decoder()
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows = []
    profiles = []
    for source, channel, payload, stats in decoded_planes(sources, executable):
        object_id = int(source["object_id"])
        topic = str(source["topic"])
        output = series_dir / f"{topic}_{object_id}_{channel}_u8.bin"
        output.write_bytes(payload)
        item = profile(source, channel, stats)
        profiles.append(item)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/{source['image_name']}",
            "object_id": object_id,
            "topic": topic,
            "title": source["title"],
            "artist": source["artist"],
            "channel": channel,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(payload),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous uint8 decoded painting color plane",
            "sample_geometry": "2d_painting_color_plane",
            "sample_rank": 2,
            "sample_shape": [source["height"], source["width"]],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "decoded_painting_color_plane",
            **stats,
        })
    result = summary(sources, profiles, version)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    sources = validate_sources(args.download_dir)
    executable, version = decoder()
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != SAMPLE_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    profiles = []
    expected_outputs: set[Path] = set()
    for row, decoded in zip(rows, decoded_planes(sources, executable), strict=True):
        source, channel, payload, stats = decoded
        object_id = int(source["object_id"])
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role for object {object_id} channel {channel}")
        if int(row.get("object_id", 0)) != object_id or row.get("channel") != channel:
            raise SystemExit(f"index ordering mismatch for object {object_id} channel {channel}")
        if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 8 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch for object {object_id} channel {channel}")
        if row.get("sample_shape") != [source["height"], source["width"]]:
            raise SystemExit(f"sample shape mismatch for object {object_id} channel {channel}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh JPEG decode for object {object_id} channel {channel}")
        if row.get("sha256") != stats["sha256"] or int(row.get("value_count", 0)) != len(payload):
            raise SystemExit(f"indexed hash or size mismatch for object {object_id} channel {channel}")
        profiles.append(profile(source, channel, stats))
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    expected_summary = summary(sources, profiles, version)
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    if stored != expected_summary:
        raise SystemExit("stored ingest statistics differ from independent source decode")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": SAMPLE_COUNT,
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_BYTES,
        "ffmpeg_version": version,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
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
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
