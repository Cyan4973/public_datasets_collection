#!/usr/bin/env python3
"""Download, decode, build, inspect, and verify Fukuchi marker trajectories."""
from __future__ import annotations

from array import array
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import sys
import zipfile
import zlib


DATASET_ID = "figshare_fukuchi_marker_trajectories_f32"
REUSE_DATASET_ID = "figshare_fukuchi_forceplate_c3d_f32"
SERIES_IDS = {
    "x": "walking_marker_x_f32",
    "y": "walking_marker_y_f32",
    "z": "walking_marker_z_f32",
}
ARTICLE_ID = 5_722_711
ARTICLE_API = f"https://api.figshare.com/v2/articles/{ARTICLE_ID}"
ARCHIVE_NAME = "WBDSc3d.zip"
ARCHIVE_SIZE = 732_874_413
ARCHIVE_MD5 = "5d93531eab7acc8ebe786145cd26eea8"
ARCHIVE_URL = "https://ndownloader.figshare.com/files/10058995"
MEMBER_COUNT = 2_019
NAME_RE = re.compile(r"WBDS(?P<subject>\d{2})(?P<trial>static\d+|walkO\d{2}[CFS]|walkT\d{2})\.c3d$")
GLOBAL_SAMPLE_STRIDE = 64
USER_AGENT = "openzl-public-datasets-fukuchi-marker-trajectories-f32/1.0"


def decode_parameter_value(endian: str, field_type: int, dims: list[int], raw: bytes) -> object:
    count = math.prod(dims) if dims else 1
    if field_type == -1:
        if not dims:
            return raw.decode("ascii", "replace")
        width = dims[0]
        if width == 0:
            return ()
        return tuple(
            raw[index * width:(index + 1) * width].decode("ascii", "replace").rstrip(" \x00")
            for index in range(count // width)
        )
    formats = {1: "b", 2: "h", 4: "f"}
    if field_type not in formats:
        raise ValueError(f"unsupported C3D parameter type {field_type}")
    return tuple(struct.unpack(endian + f"{count}{formats[field_type]}", raw))


def parse_parameters(raw: bytes, endian: str, parameter_offset: int, data_offset: int) -> dict[tuple[str, str], object]:
    if len(raw) < data_offset:
        raise ValueError("C3D source does not reach its data block")
    groups: dict[int, str] = {}
    pending: list[tuple[int, str, int, list[int], bytes]] = []
    position = parameter_offset + 4
    while position + 4 <= data_offset:
        name_length = struct.unpack_from("b", raw, position)[0]
        group_id = struct.unpack_from("b", raw, position + 1)[0]
        if name_length == 0 or group_id == 0:
            break
        length = abs(name_length)
        name = raw[position + 2:position + 2 + length].decode("ascii", "replace").upper()
        offset_position = position + 2 + length
        if offset_position + 2 > data_offset:
            raise ValueError("truncated C3D parameter record")
        jump = struct.unpack_from(endian + "H", raw, offset_position)[0]
        next_position = data_offset if jump == 0 else offset_position + jump
        if next_position <= position or next_position > data_offset:
            raise ValueError(f"invalid C3D parameter offset for {name}")
        cursor = offset_position + 2
        if group_id < 0:
            groups[-group_id] = name
        else:
            field_type = struct.unpack_from("b", raw, cursor)[0]
            dimension_count = raw[cursor + 1]
            dims = list(raw[cursor + 2:cursor + 2 + dimension_count])
            cursor += 2 + dimension_count
            size = abs(field_type) * (math.prod(dims) if dims else 1)
            value_raw = raw[cursor:cursor + size]
            if len(value_raw) != size:
                raise ValueError(f"truncated C3D parameter value for {name}")
            pending.append((group_id, name, field_type, dims, value_raw))
        if jump == 0:
            break
        position = next_position
    values = {}
    for group_id, name, field_type, dims, value_raw in pending:
        if group_id not in groups:
            raise ValueError(f"unknown C3D parameter group {group_id}")
        values[(groups[group_id], name)] = decode_parameter_value(endian, field_type, dims, value_raw)
    return values


def scalar(params: dict[tuple[str, str], object], group: str, name: str, default: object = None) -> object:
    value = params.get((group, name))
    if isinstance(value, tuple) and len(value) == 1:
        return value[0]
    return default


def strings(params: dict[tuple[str, str], object], group: str, name: str) -> list[str]:
    value = params.get((group, name), ())
    return [str(item).strip() for item in value] if isinstance(value, tuple) else []


def parse_c3d(raw: bytes) -> dict[str, object]:
    if len(raw) < 1024 or raw[1] != 0x50 or raw[0] < 2:
        raise ValueError("invalid C3D header")
    parameter_offset = (raw[0] - 1) * 512
    if parameter_offset + 4 > len(raw):
        raise ValueError("C3D parameter block lies beyond source")
    parameter_header = raw[parameter_offset:parameter_offset + 4]
    if parameter_header[:2] not in {b"\x00\x00", b"\x01\x50"} or parameter_header[3] != 84:
        raise ValueError("C3D is not supported Intel parameter storage")
    point_count, analog_values, first_frame, last_frame, max_gap = struct.unpack_from("<5H", raw, 2)
    point_scale = struct.unpack_from("<f", raw, 12)[0]
    data_block, analog_samples_per_frame = struct.unpack_from("<2H", raw, 16)
    point_rate = struct.unpack_from("<f", raw, 20)[0]
    if not math.isfinite(point_scale) or point_scale >= 0:
        raise ValueError(f"C3D is not native float32 storage: POINT:SCALE={point_scale}")
    if not point_count or last_frame < first_frame or not analog_samples_per_frame:
        raise ValueError("C3D lacks usable point frames or analog samples")
    frame_count = last_frame - first_frame + 1
    if analog_values == 0 or analog_values % analog_samples_per_frame:
        raise ValueError("C3D analog geometry is empty or inconsistent")
    analog_channels = analog_values // analog_samples_per_frame
    data_offset = (data_block - 1) * 512
    params = parse_parameters(raw, "<", parameter_offset, data_offset)
    if int(scalar(params, "POINT", "USED", -1)) != point_count:
        raise ValueError("POINT:USED contradicts C3D header")
    if int(scalar(params, "POINT", "FRAMES", -1)) != frame_count:
        raise ValueError("POINT:FRAMES contradicts C3D header")
    if float(scalar(params, "POINT", "RATE", -1.0)) != point_rate:
        raise ValueError("POINT:RATE contradicts C3D header")
    if int(scalar(params, "POINT", "DATA_START", -1)) != data_block:
        raise ValueError("POINT:DATA_START contradicts C3D header")
    if int(scalar(params, "ANALOG", "USED", -1)) != analog_channels:
        raise ValueError("ANALOG:USED contradicts C3D header")
    analog_source_bits = int(scalar(params, "ANALOG", "BITS", -1))
    analog_format = str(scalar(params, "ANALOG", "FORMAT", "")).upper()
    labels = strings(params, "ANALOG", "LABELS")
    descriptions = strings(params, "ANALOG", "DESCRIPTIONS")
    units = strings(params, "ANALOG", "UNITS")
    scales = params.get(("ANALOG", "SCALE"), ())
    offsets = params.get(("ANALOG", "OFFSET"), ())
    force_platforms = int(scalar(params, "FORCE_PLATFORM", "USED", 0))
    analog_rate = float(scalar(params, "ANALOG", "RATE", -1.0))
    point_labels = strings(params, "POINT", "LABELS")
    point_descriptions = strings(params, "POINT", "DESCRIPTIONS")
    point_units = strings(params, "POINT", "UNITS")
    bytes_per_frame = point_count * 16 + analog_values * 4
    numeric_end = data_offset + frame_count * bytes_per_frame
    if numeric_end > len(raw):
        raise ValueError("float32 C3D records extend past source")
    return {
        "processor": "intel", "endianness": "little", "point_scale": point_scale,
        "storage_kind": "float32", "bit_width": 32, "point_count": point_count,
        "point_frame_rate_hz": point_rate, "frame_count": frame_count,
        "first_frame": first_frame, "last_frame": last_frame,
        "max_interpolation_gap": max_gap, "data_offset": data_offset,
        "analog_parameter_format": analog_format.lower(),
        "analog_parameter_source_bits": analog_source_bits,
        "analog_channel_count": analog_channels,
        "analog_samples_per_point_frame": analog_samples_per_frame,
        "analog_rate_hz": analog_rate, "analog_values": frame_count * analog_values,
        "analog_payload_bytes": frame_count * analog_values * 4,
        "force_platform_count": force_platforms, "analog_labels": labels,
        "analog_descriptions": descriptions, "analog_units": units,
        "analog_scales": list(scales) if isinstance(scales, tuple) else [],
        "analog_offsets": list(offsets) if isinstance(offsets, tuple) else [],
        "point_labels": point_labels, "point_descriptions": point_descriptions,
        "point_units": point_units,
        "point_payload_bytes": frame_count * point_count * 16,
        "trailing_bytes": len(raw) - numeric_end,
    }


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def fetch_bytes(url: str, maximum: int) -> bytes:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
            "--retry-delay", "2", "--max-time", "600", "--max-filesize", str(maximum),
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode or len(result.stdout) > maximum:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(message or f"failed to fetch {url}")
    return result.stdout


def fetch_file(url: str, target: Path, expected_size: int) -> None:
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
            "--retry-delay", "2", "--max-time", "7200", "--max-filesize", str(expected_size),
            "--user-agent", USER_AGENT, "--output", str(part), url,
        ],
        check=False,
    )
    if result.returncode or not part.is_file() or part.stat().st_size != expected_size:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"failed exact archive download: {url}")
    os.replace(part, target)


def validate_article(article: dict[str, object]) -> None:
    if int(article.get("id", 0)) != ARTICLE_ID:
        raise RuntimeError("unexpected Figshare article identity")
    text = normalize(f"{article.get('title', '')} {article.get('description', '')}")
    if not all(term in text for term in ("overground", "treadmill", "walking", "kinematics", "kinetics")):
        raise RuntimeError("Figshare article semantics changed")
    license_info = article.get("license", {})
    license_text = normalize(
        f"{license_info.get('name', '')} {license_info.get('url', '')}"
        if isinstance(license_info, dict) else license_info
    )
    if "cc by 4 0" not in license_text and "creativecommons org licenses by 4 0" not in license_text:
        raise RuntimeError("Figshare article no longer declares CC BY 4.0")
    files = article.get("files", [])
    matches = [item for item in files if isinstance(item, dict) and item.get("name") == ARCHIVE_NAME]
    if len(matches) != 1:
        raise RuntimeError("pinned archive is absent or ambiguous")
    item = matches[0]
    checksum = item.get("computed_md5") or item.get("supplied_md5")
    if int(item.get("size", 0)) != ARCHIVE_SIZE or checksum != ARCHIVE_MD5 or item.get("download_url") != ARCHIVE_URL:
        raise RuntimeError("pinned archive identity changed")


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    archive = args.download_dir / ARCHIVE_NAME
    article_path = args.download_dir / f"article_{ARTICLE_ID}.json"
    reuse_dir = args.download_dir.parent / REUSE_DATASET_ID
    reuse_archive = reuse_dir / ARCHIVE_NAME
    reuse_article = reuse_dir / f"article_{ARTICLE_ID}.json"
    if (
        (not archive.is_file() or archive.stat().st_size != ARCHIVE_SIZE or file_hash(archive, "md5") != ARCHIVE_MD5)
        and reuse_archive.is_file()
        and reuse_archive.stat().st_size == ARCHIVE_SIZE
        and file_hash(reuse_archive, "md5") == ARCHIVE_MD5
    ):
        archive.unlink(missing_ok=True)
        try:
            os.link(reuse_archive, archive)
            reuse_method = "hardlink"
        except OSError:
            shutil.copy2(reuse_archive, archive)
            reuse_method = "copy"
        print(f"local_reuse method={reuse_method} file={ARCHIVE_NAME} bytes={ARCHIVE_SIZE}")
    if not article_path.is_file() and reuse_article.is_file():
        shutil.copy2(reuse_article, article_path)
        print(f"local_reuse method=copy file={reuse_article.name}")

    if article_path.is_file():
        article = json.loads(article_path.read_text(encoding="utf-8"))
        if not isinstance(article, dict):
            raise SystemExit("cached Figshare response is not an object")
        validate_article(article)
    else:
        article = json.loads(fetch_bytes(ARTICLE_API, 20 * 1024 * 1024))
        if not isinstance(article, dict):
            raise SystemExit("Figshare response is not an object")
        validate_article(article)
        article_path.write_text(
            json.dumps(article, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if not archive.is_file() or archive.stat().st_size != ARCHIVE_SIZE or file_hash(archive, "md5") != ARCHIVE_MD5:
        print(f"download file={ARCHIVE_NAME} bytes={ARCHIVE_SIZE}")
        fetch_file(ARCHIVE_URL, archive, ARCHIVE_SIZE)
        if file_hash(archive, "md5") != ARCHIVE_MD5:
            archive.unlink(missing_ok=True)
            raise SystemExit("downloaded archive MD5 mismatch")
    else:
        print(f"cache_hit file={ARCHIVE_NAME} bytes={ARCHIVE_SIZE}")
    inventory = {
        "candidate_id": DATASET_ID, "article_id": ARTICLE_ID,
        "article_title": article.get("title"), "doi": article.get("doi"),
        "license": "CC BY 4.0", "archive_name": ARCHIVE_NAME,
        "archive_size": ARCHIVE_SIZE, "archive_md5": ARCHIVE_MD5,
        "archive_url": ARCHIVE_URL,
        "excluded_duplicate_archive": "WBDSc3dWithGaitEvents.zip",
    }
    (args.download_dir / "source_inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(inventory, indent=2, sort_keys=True))


def decode_f32le(raw: bytes) -> array:
    values = array("f")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def extract_point_components(raw: bytes, report: dict[str, object]) -> tuple[dict[str, bytes], bytes]:
    frames = int(report["frame_count"])
    points = int(report["point_count"])
    channels = int(report["analog_channel_count"])
    subsamples = int(report["analog_samples_per_point_frame"])
    source_offset = int(report["data_offset"])
    point_bytes = points * 16
    analog_bytes = channels * subsamples * 4
    frame_bytes = point_bytes + analog_bytes
    expected_end = source_offset + frames * frame_bytes
    if expected_end > len(raw) or len(raw) - expected_end != int(report["trailing_bytes"]):
        raise ValueError("C3D data geometry contradicts source bytes")
    point_payload = bytearray(frames * point_bytes)
    target = 0
    for frame in range(frames):
        start = source_offset + frame * frame_bytes
        point_payload[target:target + point_bytes] = raw[start:start + point_bytes]
        target += point_bytes
    words = array("I")
    if words.itemsize != 4:
        raise RuntimeError("this platform does not provide a four-byte unsigned-int array")
    words.frombytes(point_payload)
    components = {
        axis: words[index::4].tobytes()
        for index, axis in enumerate(("x", "y", "z"))
    }
    status = words[3::4].tobytes()
    return components, status


def quantile(sorted_values: list[int], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def validate_local(download_dir: Path) -> Path:
    archive = download_dir / ARCHIVE_NAME
    inventory_path = download_dir / "source_inventory.json"
    article_path = download_dir / "article_5722711.json"
    if not archive.is_file() or not inventory_path.is_file() or not article_path.is_file():
        raise SystemExit("missing pinned archive or metadata; run download.sh")
    if archive.stat().st_size != ARCHIVE_SIZE or file_hash(archive, "md5") != ARCHIVE_MD5:
        raise SystemExit("pinned archive size or MD5 changed")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected = {
        "candidate_id": DATASET_ID, "article_id": ARTICLE_ID,
        "license": "CC BY 4.0", "archive_name": ARCHIVE_NAME,
        "archive_size": ARCHIVE_SIZE, "archive_md5": ARCHIVE_MD5,
        "archive_url": ARCHIVE_URL,
        "excluded_duplicate_archive": "WBDSc3dWithGaitEvents.zip",
    }
    for key, value in expected.items():
        if inventory.get(key) != value:
            raise SystemExit(f"source inventory changed for {key}")
    article = json.loads(article_path.read_text(encoding="utf-8"))
    validate_article(article)
    return archive


def scan(download_dir: Path, samples_dir: Path | None = None) -> dict[str, object]:
    archive = validate_local(download_dir)
    if samples_dir is not None:
        if samples_dir.exists():
            shutil.rmtree(samples_dir)
        for series_id in SERIES_IDS.values():
            (samples_dir / series_id).mkdir(parents=True)

    profiles: list[dict[str, object]] = []
    schemas: dict[tuple[object, ...], dict[str, object]] = {}
    excluded_static: list[dict[str, object]] = []
    point_payload_owners: dict[str, str] = {}
    duplicate_payloads: list[dict[str, str]] = []
    sampled_patterns: set[bytes] = set()
    global_minimum = {axis: math.inf for axis in SERIES_IDS}
    global_maximum = {axis: -math.inf for axis in SERIES_IDS}
    total_values = total_bytes = total_zero = total_transitions = 0
    series_values = Counter()
    series_bytes = Counter()
    series_zeros = Counter()
    series_samples = Counter()
    trial_counts: Counter[str] = Counter()
    subject_counts: Counter[str] = Counter()
    point_counts: Counter[int] = Counter()
    point_rates: Counter[float] = Counter()
    status_values: Counter[float] = Counter()

    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) != MEMBER_COUNT or any(info.is_dir() or not info.filename.lower().endswith(".c3d") for info in infos):
            raise SystemExit("unexpected archive member inventory")
        if len({info.filename for info in infos}) != MEMBER_COUNT:
            raise SystemExit("duplicate member names in archive")
        for index, info in enumerate(infos, 1):
            match = NAME_RE.fullmatch(info.filename)
            if not match:
                raise SystemExit(f"unexpected C3D member name: {info.filename}")
            raw = bundle.read(info)
            if len(raw) != info.file_size or zlib.crc32(raw) & 0xFFFFFFFF != info.CRC:
                raise SystemExit(f"ZIP size or CRC mismatch: {info.filename}")
            if match.group("trial").startswith("static"):
                analog_values = struct.unpack_from("<H", raw, 4)[0]
                point_scale = struct.unpack_from("<f", raw, 12)[0]
                if point_scale >= 0:
                    raise SystemExit(f"unexpected static-trial storage: {info.filename}")
                excluded_static.append({
                    "source_member": info.filename,
                    "source_member_bytes": info.file_size,
                    "analog_values_per_point_frame": analog_values,
                    "point_scale": point_scale,
                })
                continue
            try:
                report = parse_c3d(raw)
            except (ValueError, struct.error) as error:
                raise SystemExit(f"{info.filename}: {error}") from error
            if (
                report["processor"] != "intel"
                or report["endianness"] != "little"
                or report["storage_kind"] != "float32"
                or report["bit_width"] != 32
                or report["trailing_bytes"] != 0
            ):
                raise SystemExit(f"unexpected C3D representation: {info.filename}")
            labels = tuple(str(value) for value in report["point_labels"])
            descriptions = tuple(str(value) for value in report["point_descriptions"])
            units = tuple(str(value) for value in report["point_units"])
            points = int(report["point_count"])
            point_rate = float(report["point_frame_rate_hz"])
            if (
                labels != descriptions
                or len(labels) != points
                or len(set(labels)) != points
                or any(not label for label in labels)
                or units != ("mm",)
                or points not in {20, 21, 22}
                or point_rate not in {100.0, 150.0}
            ):
                raise SystemExit(f"unexpected marker schema: {info.filename}")
            components, status_payload = extract_point_components(raw, report)
            if any(len(payload) != int(report["frame_count"]) * points * 4 for payload in components.values()):
                raise SystemExit(f"point-coordinate extraction size mismatch: {info.filename}")
            point_payload_sha = hashlib.sha256(
                components["x"] + components["y"] + components["z"] + status_payload
            ).hexdigest()
            if point_payload_sha in point_payload_owners:
                duplicate_payloads.append({
                    "source_member": info.filename,
                    "duplicate_of": point_payload_owners[point_payload_sha],
                    "sha256": point_payload_sha,
                })
                continue
            point_payload_owners[point_payload_sha] = info.filename

            status = decode_f32le(status_payload)
            if not all(math.isfinite(value) for value in status) or set(status) - {0.0, 65535.0}:
                raise SystemExit(f"unexpected C3D point status/residual words: {info.filename}")
            status_nonzero = sum(value != 0.0 for value in status)
            status_values.update(status)
            trial = match.group("trial")
            trial_kind = "treadmill" if trial.startswith("walkT") else "overground"
            subject = match.group("subject")
            schema_key = (labels, units, point_rate)
            if schema_key not in schemas:
                schema_id = f"schema_{len(schemas) + 1:02d}"
                schemas[schema_key] = {
                    "schema_id": schema_id, "marker_labels": list(labels),
                    "units": list(units), "point_count": points,
                    "point_frame_rate_hz": point_rate,
                }
            schema_id = str(schemas[schema_key]["schema_id"])
            for axis, payload in components.items():
                values = decode_f32le(payload)
                if not all(math.isfinite(value) for value in values):
                    raise SystemExit(f"non-finite marker {axis} coordinate: {info.filename}")
                minimum, maximum = min(values), max(values)
                zero_values = values.count(0.0)
                distinct_values = len(set(values))
                transitions = sum(left != right for left, right in zip(values, values[1:]))
                if distinct_values < 16 or transitions < len(values) // 10:
                    raise SystemExit(f"degenerate marker {axis} trajectory: {info.filename}")
                if zero_values != status_nonzero:
                    raise SystemExit(
                        f"marker {axis} zeros do not match missing-point status: {info.filename}"
                    )
                payload_sha = hashlib.sha256(payload).hexdigest()
                output_name = f"{Path(info.filename).stem}_marker_{axis}_f32le.bin"
                series_id = SERIES_IDS[axis]
                if samples_dir is not None:
                    (samples_dir / series_id / output_name).write_bytes(payload)
                sampled_patterns.update(
                    payload[offset:offset + 4]
                    for offset in range(0, len(payload), GLOBAL_SAMPLE_STRIDE * 4)
                )
                profile = {
                    "source_member": info.filename, "source_member_bytes": info.file_size,
                    "source_member_crc32": f"{info.CRC:08x}", "subject_code": subject,
                    "trial_code": trial, "trial_kind": trial_kind, "schema_id": schema_id,
                    "frame_count": report["frame_count"], "point_count": points,
                    "point_frame_rate_hz": point_rate, "axis": axis,
                    "series_id": series_id, "value_count": len(values),
                    "sample_size_bytes": len(payload), "minimum": minimum, "maximum": maximum,
                    "zero_values": zero_values, "distinct_values": distinct_values,
                    "flattened_transitions": transitions, "sha256": payload_sha,
                    "output_name": output_name,
                    "status_nonzero_values": status_nonzero,
                    "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
                }
                profiles.append(profile)
                global_minimum[axis] = min(global_minimum[axis], minimum)
                global_maximum[axis] = max(global_maximum[axis], maximum)
                total_values += len(values)
                total_bytes += len(payload)
                total_zero += zero_values
                total_transitions += transitions
                series_values[series_id] += len(values)
                series_bytes[series_id] += len(payload)
                series_zeros[series_id] += zero_values
                series_samples[series_id] += 1
            trial_counts[trial_kind] += 1
            subject_counts[subject] += 1
            point_counts[points] += 1
            point_rates[point_rate] += 1
            if index % 250 == 0:
                print(f"progress members={index}/{MEMBER_COUNT} accepted_trials={len(point_payload_owners)}")

    sizes = sorted(int(profile["sample_size_bytes"]) for profile in profiles)
    distinct_counts = sorted(int(profile["distinct_values"]) for profile in profiles)
    ratios = sorted(float(profile["zlib_ratio"]) for profile in profiles)
    summary = {
        "dataset_id": DATASET_ID, "series_ids": SERIES_IDS, "article_id": ARTICLE_ID,
        "doi": "10.6084/m9.figshare.5722711.v5", "license": "CC BY 4.0",
        "archive_name": ARCHIVE_NAME, "archive_size": ARCHIVE_SIZE,
        "archive_md5": ARCHIVE_MD5, "archive_member_count": MEMBER_COUNT,
        "excluded_static_members": len(excluded_static),
        "excluded_duplicate_payloads": len(duplicate_payloads),
        "sample_count": len(profiles), "trial_count": len(point_payload_owners),
        "subject_count": len(subject_counts), "trial_kind_counts": dict(sorted(trial_counts.items())),
        "point_count_distribution": {str(key): value for key, value in sorted(point_counts.items())},
        "point_rate_distribution": {str(key): value for key, value in sorted(point_rates.items())},
        "point_status_value_counts": {str(key): value for key, value in sorted(status_values.items())},
        "schema_count": len(schemas), "schemas": sorted(schemas.values(), key=lambda row: str(row["schema_id"])),
        "value_count": total_values, "total_size_bytes": total_bytes,
        "minimum_sample_bytes": min(sizes), "p10_sample_bytes": quantile(sizes, 0.10),
        "median_sample_bytes": statistics.median(sizes), "p90_sample_bytes": quantile(sizes, 0.90),
        "maximum_sample_bytes": max(sizes), "global_minimum": global_minimum,
        "global_maximum": global_maximum, "zero_values": total_zero,
        "zero_fraction": round(total_zero / total_values, 9),
        "minimum_sample_distinct_values": min(distinct_counts),
        "median_sample_distinct_values": statistics.median(distinct_counts),
        "maximum_sample_distinct_values": max(distinct_counts),
        "total_flattened_transitions": total_transitions,
        "transition_fraction": round(total_transitions / (total_values - len(profiles)), 9),
        "sampled_distinct_bit_patterns": len(sampled_patterns),
        "global_sample_stride": GLOBAL_SAMPLE_STRIDE,
        "unique_trial_point_payloads": len(point_payload_owners),
        "series": {
            series_id: {
                "sample_count": series_samples[series_id],
                "value_count": series_values[series_id],
                "sample_bytes": series_bytes[series_id],
                "zero_values": series_zeros[series_id],
            }
            for series_id in SERIES_IDS.values()
        },
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios), "maximum_zlib_ratio": max(ratios),
        "excluded_static_profiles": excluded_static,
        "duplicate_payloads": duplicate_payloads, "profiles": profiles,
    }
    expected = {
        "excluded_static_members": 50, "excluded_duplicate_payloads": 3,
        "sample_count": 5898, "trial_count": 1966, "subject_count": 42,
        "trial_kind_counts": {"overground": 1638, "treadmill": 328},
        "point_count_distribution": {"20": 20, "21": 48, "22": 1898},
        "point_rate_distribution": {"100.0": 8, "150.0": 1958},
        "schema_count": 5, "value_count": 144088704, "total_size_bytes": 576354816,
        "minimum_sample_bytes": 19888, "p10_sample_bytes": 27368.0,
        "median_sample_bytes": 39072.0, "p90_sample_bytes": 396000.0,
        "maximum_sample_bytes": 396000,
        "global_minimum": {"x": -1008.7257080078125, "y": 0.0, "z": -703.4877319335938},
        "global_maximum": {"x": 4365.48486328125, "y": 1199.3616943359375, "z": 1525.7314453125},
        "point_status_value_counts": {"0.0": 47904624, "65535.0": 124944},
        "zero_values": 374832, "zero_fraction": 0.002601398,
        "minimum_sample_distinct_values": 4969,
        "median_sample_distinct_values": 9762.5,
        "maximum_sample_distinct_values": 98659,
        "total_flattened_transitions": 144061206,
        "transition_fraction": 0.999850086,
        "sampled_distinct_bit_patterns": 2123446,
        "unique_trial_point_payloads": 1966,
        "minimum_zlib_ratio": 0.767642857,
        "median_zlib_ratio": 0.888315741,
        "maximum_zlib_ratio": 0.923890764,
        "series": {
            "walking_marker_x_f32": {
                "sample_count": 1966, "value_count": 48029568,
                "sample_bytes": 192118272, "zero_values": 124944,
            },
            "walking_marker_y_f32": {
                "sample_count": 1966, "value_count": 48029568,
                "sample_bytes": 192118272, "zero_values": 124944,
            },
            "walking_marker_z_f32": {
                "sample_count": 1966, "value_count": 48029568,
                "sample_bytes": 192118272, "zero_values": 124944,
            },
        },
    }
    for key, value in expected.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {summary[key]} != {value}")
    expected_duplicates = [
        ("WBDS16walkO02C.c3d", "WBDS16walkO01C.c3d"),
        ("WBDS26walkO16C.c3d", "WBDS26walkO01C.c3d"),
        ("WBDS26walkO17C.c3d", "WBDS26walkO02C.c3d"),
    ]
    actual_duplicates = [
        (str(row["source_member"]), str(row["duplicate_of"]))
        for row in duplicate_payloads
    ]
    if actual_duplicates != expected_duplicates:
        raise SystemExit("exact duplicate selection changed")
    return summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    hidden = {"profiles", "excluded_static_profiles", "duplicate_payloads", "schemas"}
    return {key: value for key, value in summary.items() if key not in hidden}


def inspect(args: argparse.Namespace) -> None:
    print(json.dumps(public_summary(scan(args.download_dir)), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    summary = scan(args.download_dir, args.samples_dir)
    rows = []
    schema_by_id = {str(row["schema_id"]): row for row in summary["schemas"]}
    for profile in summary["profiles"]:
        schema = schema_by_id[str(profile["schema_id"])]
        output = args.samples_dir / str(profile["series_id"]) / str(profile["output_name"])
        rows.append({
            "dataset_id": DATASET_ID, "series_id": profile["series_id"], "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/{ARCHIVE_NAME}::{profile['source_member']}",
            "source_member": profile["source_member"], "source_member_crc32": profile["source_member_crc32"],
            "subject_code": profile["subject_code"], "trial_code": profile["trial_code"],
            "trial_kind": profile["trial_kind"], "schema_id": profile["schema_id"],
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_format": "raw homogeneous little-endian float32 C3D marker-coordinate matrix",
            "sample_geometry": "walking_trial_marker_coordinate_matrix_2d", "sample_rank": 2,
            "sample_shape": [profile["frame_count"], profile["point_count"]],
            "sample_axes": ["point_frame", "anatomical_marker"],
            "natural_record_kind": "complete_walking_trial_marker_coordinate_axis",
            "point_frame_rate_hz": profile["point_frame_rate_hz"],
            "coordinate_axis": profile["axis"], "coordinate_units": "mm",
            "marker_labels": schema["marker_labels"],
            "point_status_nonzero_values": profile["status_nonzero_values"],
            "minimum": profile["minimum"], "maximum": profile["maximum"],
            "sha256": profile["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    profiles = summary["profiles"]
    if len(rows) != len(profiles):
        raise SystemExit("unexpected index row count")
    expected_outputs = set()
    for row, profile in zip(rows, profiles, strict=True):
        if (
            row.get("dataset_id") != DATASET_ID
            or row.get("series_id") != profile["series_id"]
            or row.get("source_member") != profile["source_member"]
            or row.get("numeric_kind") != "float"
            or row.get("bit_width") != 32
            or row.get("endianness") != "little"
            or row.get("sample_shape") != [profile["frame_count"], profile["point_count"]]
            or row.get("sample_axes") != ["point_frame", "anatomical_marker"]
            or row.get("coordinate_axis") != profile["axis"]
            or row.get("coordinate_units") != "mm"
            or row.get("natural_record_kind") != "complete_walking_trial_marker_coordinate_axis"
        ):
            raise SystemExit(f"indexed metadata changed: {profile['source_member']}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if (
            not output.is_file()
            or output.stat().st_size != profile["sample_size_bytes"]
            or file_hash(output, "sha256") != profile["sha256"]
        ):
            raise SystemExit(f"output is not byte-identical: {profile['source_member']}")
    actual_outputs = {
        path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs or json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("sample inventory or stored statistics changed")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": len(rows),
        "verified_values": summary["value_count"], "verified_bytes": summary["total_size_bytes"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--download-dir", type=Path, required=True)
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
    if args.command == "download":
        download(args)
    elif args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
