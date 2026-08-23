#!/usr/bin/env python3
"""Build and verify accepted temporal YUV420 plane windows from pinned VP9 videos."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


DATASET_ID = "blender_open_movies_yuv420_u8"
FRAME_COUNT = 80
WINDOW_FRACTIONS = (Fraction(1, 5), Fraction(2, 5), Fraction(3, 5), Fraction(4, 5))
SERIES = {
    "y": "video_luma_y_u8",
    "cb": "video_chroma_cb_u8",
    "cr": "video_chroma_cr_u8",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tools() -> tuple[str, str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise SystemExit("ffmpeg and ffprobe are required")
    version = subprocess.run(
        [ffmpeg, "-version"], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    ).stdout.splitlines()[0].strip()
    return ffmpeg, ffprobe, version


def load_sources(path: Path, download_dir: Path, ffprobe: str) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 3 or len({row["project_id"] for row in rows}) != 3:
        raise SystemExit("sources.tsv must contain three unique films")
    result = []
    for row in rows:
        source = download_dir / row["local_file"]
        if not source.is_file() or source.stat().st_size != int(row["bytes"]):
            raise SystemExit(f"missing or size-mismatched source: {source}")
        if file_hash(source) != row["sha256"]:
            raise SystemExit(f"source SHA-256 mismatch: {source}")
        probe = json.loads(subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout)
        videos = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
        if len(videos) != 1:
            raise SystemExit(f"expected one video stream: {source}")
        video = videos[0]
        actual = (
            video.get("codec_name"), video.get("pix_fmt"), int(video.get("width", 0)),
            int(video.get("height", 0)), video.get("avg_frame_rate"),
            f"{float(probe.get('format', {}).get('duration', 0)):.6f}",
        )
        expected = (
            "vp9", "yuv420p", int(row["width"]), int(row["height"]),
            row["frame_rate"], row["duration_seconds"],
        )
        if actual != expected:
            raise SystemExit(f"source video schema mismatch for {row['project_id']}: {actual} != {expected}")
        result.append({
            **row,
            "path": source,
            "width": int(row["width"]),
            "height": int(row["height"]),
            "duration": Fraction(row["duration_seconds"]),
            "fps": Fraction(row["frame_rate"]),
        })
    return result


def window_start(source: dict[str, object], fraction: Fraction) -> Fraction:
    duration = source["duration"]
    fps = source["fps"]
    assert isinstance(duration, Fraction) and isinstance(fps, Fraction)
    start = duration * fraction - Fraction(FRAME_COUNT, 2) / fps
    if start <= 0 or start + Fraction(FRAME_COUNT, 1) / fps >= duration:
        raise SystemExit(f"invalid window placement for {source['project_id']}")
    return start


def decode_window(source: dict[str, object], fraction: Fraction, ffmpeg: str) -> dict[str, bytes]:
    start = window_start(source, fraction)
    timestamp = f"{float(start):.6f}"
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-threads", "1", "-fflags", "+bitexact",
        "-ss", timestamp, "-i", str(source["path"]), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-frames:v", str(FRAME_COUNT), "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
        "-f", "rawvideo", "-",
    ]
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    width = int(source["width"])
    height = int(source["height"])
    chroma_width = width // 2
    chroma_height = height // 2
    y_size = width * height
    c_size = chroma_width * chroma_height
    frame_size = y_size + 2 * c_size
    if len(completed.stdout) != FRAME_COUNT * frame_size:
        raise SystemExit(
            f"short or oversized decode for {source['project_id']} at {timestamp}: "
            f"{len(completed.stdout)} != {FRAME_COUNT * frame_size}"
        )
    planes = {"y": bytearray(), "cb": bytearray(), "cr": bytearray()}
    for frame in range(FRAME_COUNT):
        offset = frame * frame_size
        planes["y"].extend(completed.stdout[offset:offset + y_size])
        offset += y_size
        planes["cb"].extend(completed.stdout[offset:offset + c_size])
        offset += c_size
        planes["cr"].extend(completed.stdout[offset:offset + c_size])
    return {key: bytes(value) for key, value in planes.items()}


def validate_payload(payload: bytes, sample_id: str) -> dict[str, object]:
    counts = Counter(payload)
    distinct = len(counts)
    dominant = max(counts.values())
    transitions = sum(left != right for left, right in zip(payload, payload[1:]))
    if distinct < 16 or dominant / len(payload) > 0.99 or transitions < 10_000:
        raise SystemExit(f"degenerate decoded video plane: {sample_id}")
    return {
        "minimum": min(payload),
        "maximum": max(payload),
        "distinct_values": distinct,
        "dominant_value_count": dominant,
        "transition_count": transitions,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def iter_samples(sources: list[dict[str, object]], ffmpeg: str):
    hashes: set[str] = set()
    for source in sources:
        width = int(source["width"])
        height = int(source["height"])
        for window_index, fraction in enumerate(WINDOW_FRACTIONS):
            start = window_start(source, fraction)
            planes = decode_window(source, fraction, ffmpeg)
            for plane_id in ("y", "cb", "cr"):
                payload = planes[plane_id]
                sample_id = f"{source['project_id']}_w{window_index + 1:02d}_{plane_id}"
                measured = validate_payload(payload, sample_id)
                if measured["sha256"] in hashes:
                    raise SystemExit(f"duplicate decoded plane window: {sample_id}")
                hashes.add(str(measured["sha256"]))
                plane_width = width if plane_id == "y" else width // 2
                plane_height = height if plane_id == "y" else height // 2
                yield {
                    "sample_id": sample_id,
                    "project_id": source["project_id"],
                    "source": source,
                    "window_index": window_index + 1,
                    "window_fraction": f"{fraction.numerator}/{fraction.denominator}",
                    "start_seconds": f"{float(start):.6f}",
                    "plane_id": plane_id,
                    "series_id": SERIES[plane_id],
                    "width": plane_width,
                    "height": plane_height,
                    "payload": payload,
                    **measured,
                }


def summary(samples: list[dict[str, object]], sources: list[dict[str, object]], version: str) -> dict[str, object]:
    reports = []
    for sample in samples:
        reports.append({key: value for key, value in sample.items() if key not in {"payload", "source"}})
    return {
        "dataset_id": DATASET_ID,
        "decoder": version,
        "source_count": len(sources),
        "sample_count": len(samples),
        "value_count": sum(len(sample["payload"]) for sample in samples),
        "total_size_bytes": sum(len(sample["payload"]) for sample in samples),
        "samples": reports,
    }


def build(args: argparse.Namespace) -> None:
    ffmpeg, ffprobe, version = tools()
    sources = load_sources(args.sources, args.download_dir, ffprobe)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    samples = list(iter_samples(sources, ffmpeg))
    rows = []
    for sample in samples:
        series_dir = args.samples_dir / str(sample["series_id"])
        series_dir.mkdir(parents=True, exist_ok=True)
        output = series_dir / f"{sample['sample_id']}_f{FRAME_COUNT:03d}.bin"
        output.write_bytes(sample["payload"])
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": sample["series_id"],
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": sample["source"]["path"].relative_to(args.data_root).as_posix(),
            "source_sha256": sample["source"]["sha256"],
            "project_id": sample["project_id"],
            "window_index": sample["window_index"],
            "window_fraction": sample["window_fraction"],
            "start_seconds": sample["start_seconds"],
            "frame_count": FRAME_COUNT,
            "frame_rate": sample["source"]["frame_rate"],
            "plane_id": sample["plane_id"],
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(sample["payload"]),
            "sample_size_bytes": len(sample["payload"]),
            "sample_format": "raw homogeneous uint8 temporal YUV420 plane tensor",
            "sample_geometry": "3d_video_plane_window",
            "sample_rank": 3,
            "sample_shape": [FRAME_COUNT, sample["height"], sample["width"]],
            "sample_axes": ["frame", "y", "x"],
            "natural_record_kind": "open_movie_temporal_plane_window",
            "minimum": sample["minimum"],
            "maximum": sample["maximum"],
            "distinct_values": sample["distinct_values"],
            "sha256": sample["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = summary(samples, sources, version)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    ffmpeg, ffprobe, version = tools()
    sources = load_sources(args.sources, args.download_dir, ffprobe)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    samples = list(iter_samples(sources, ffmpeg))
    if len(rows) != len(samples) or json.loads(args.stats.read_text(encoding="utf-8")) != summary(samples, sources, version):
        raise SystemExit("index/stats differ from fresh source decode")
    expected_outputs = set()
    for row, sample in zip(rows, samples, strict=True):
        expected_shape = [FRAME_COUNT, sample["height"], sample["width"]]
        if row.get("series_id") != sample["series_id"] or row.get("project_id") != sample["project_id"]:
            raise SystemExit(f"sample identity mismatch: {sample['sample_id']}")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little":
            raise SystemExit(f"numeric schema mismatch: {sample['sample_id']}")
        if row.get("sample_shape") != expected_shape or row.get("value_count") != len(sample["payload"]):
            raise SystemExit(f"sample shape mismatch: {sample['sample_id']}")
        output = args.data_root / row["sample_path"]
        if not output.is_file() or output.read_bytes() != sample["payload"]:
            raise SystemExit(f"output differs from fresh decode: {output}")
        if row.get("sha256") != sample["sha256"]:
            raise SystemExit(f"output hash mismatch: {output}")
        expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(samples),
        "verified_values": sum(len(sample["payload"]) for sample in samples),
        "verified_bytes": sum(len(sample["payload"]) for sample in samples),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--sources", type=Path, required=True)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
