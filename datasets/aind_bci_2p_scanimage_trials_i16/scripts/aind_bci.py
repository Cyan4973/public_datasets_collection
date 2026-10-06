#!/usr/bin/env python3
"""AIND BCI two-photon ScanImage trial movies (int16): source pins, download
validation, build, and a synthetic parser self-test.

Pure standard library. Network I/O happens only in download.sh (curl); this
module parses what curl fetched.

Subcommands
  check-sources      validate the pin table (counts, totals, uniqueness)
  plan               print the download plan for download.sh
  validate           validate one fetched object against its pins (size,
                     S3 ETag, optional SHA-256, semantic content checks)
  build              decode every pinned trial TIFF into one raw int16 sample
  selftest           exercise the BigTIFF/ScanImage parser on synthetic files
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import json
import mmap
import os
import re
import struct
import sys
import tempfile
import urllib.parse
from pathlib import Path

DATASET_ID = "aind_bci_2p_scanimage_trials_i16"
SERIES_ID = "bci_2p_trial_movie_i16"
BUCKET_URL = "https://aind-open-data.s3.amazonaws.com"

WIDTH = 512
HEIGHT = 256
FRAME_VALUES = WIDTH * HEIGHT
FRAME_BYTES = FRAME_VALUES * 2
FRAME_RATE_HZ = 58.29007352941176
SI_MAGIC = 117637889
SI_HEADER_VERSION = 4

EXPECTED_TRIALS = 11
EXPECTED_TRIAL_BYTES = 984250298
EXPECTED_FRAMES = 3718
MIN_TRIAL_FRAMES = 300
MAX_TRIAL_FRAMES = 360

RIG_ID = "442_Bergamo_2p_photostim"
PROJECT_NAME = "Brain Computer Interface"
LICENSE_ID = "CC-BY-4.0"

# Frame-invariant ScanImage settings every selected trial must carry
# (values exactly as serialized in the SI header text).
EXPECTED_SI = {
    "SI.VERSION_MAJOR": "2023",
    "SI.VERSION_MINOR": "1",
    "SI.TIFF_FORMAT_VERSION": "4",
    "SI.imagingSystem": "'ResScan'",
    "SI.hScan2D.scanMode": "'resonant'",
    "SI.hScan2D.bidirectional": "true",
    "SI.hScan2D.channelsDataType": "'int16'",
    "SI.hScan2D.channelsAdcResolution": "16",
    "SI.hScan2D.logAverageFactor": "1",
    "SI.hChannels.channelSave": "2",
    "SI.hChannels.channelsActive": "2",
    "SI.hRoiManager.pixelsPerLine": "512",
    "SI.hRoiManager.linesPerFrame": "256",
    "SI.hRoiManager.scanZoomFactor": "2",
    "SI.hStackManager.enable": "false",
}

TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}

SOURCE_COLUMNS = [
    "kind",
    "subject_id",
    "session_name",
    "file_index",
    "key",
    "version_id",
    "size_bytes",
    "etag",
    "part_size_bytes",
    "crc64nvme",
    "sha256",
    "last_modified",
    "expected_frames",
    "first_ifd_offset",
    "local_name",
]


class ValidationError(Exception):
    pass


class IntegrityError(ValidationError):
    """Transfer-level mismatch (size, ETag, SHA-256): the local bytes are bad."""


def fail(message: str) -> None:
    raise ValidationError(message)


# --------------------------------------------------------------------------
# pin table


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != SOURCE_COLUMNS:
            fail(f"unexpected sources.tsv columns: {reader.fieldnames}")
        rows = []
        for row in reader:
            rows.append({key: (None if value == "-" else value) for key, value in row.items()})
    return rows


def trial_rows(rows: list[dict]) -> list[dict]:
    return sorted((row for row in rows if row["kind"] == "trial_tiff"), key=lambda row: row["subject_id"])


def object_url(row: dict) -> str:
    key = urllib.parse.quote(row["key"], safe="/")
    version = urllib.parse.quote(row["version_id"], safe="")
    return f"{BUCKET_URL}/{key}?versionId={version}"


def check_sources(rows: list[dict]) -> None:
    trials = trial_rows(rows)
    if len(trials) != EXPECTED_TRIALS:
        fail(f"expected {EXPECTED_TRIALS} trial TIFF pins, found {len(trials)}")
    subjects = [row["subject_id"] for row in trials]
    if len(set(subjects)) != len(subjects):
        fail("trial pins must cover distinct subjects (one trial per mouse)")
    total = sum(int(row["size_bytes"]) for row in trials)
    frames = sum(int(row["expected_frames"]) for row in trials)
    if total != EXPECTED_TRIAL_BYTES or frames != EXPECTED_FRAMES:
        fail(f"pin totals changed: bytes={total} frames={frames}")
    names = [row["local_name"] for row in rows]
    if len(set(names)) != len(names):
        fail("duplicate local_name in sources.tsv")
    sessions = {row["session_name"] for row in trials}
    for session in sessions:
        kinds = sorted(row["kind"] for row in rows if row["session_name"] == session)
        if kinds != ["data_description", "session", "trial_tiff"]:
            fail(f"session {session} needs exactly one data_description, session, and trial pin: {kinds}")
    for row in trials:
        expected_frames = int(row["expected_frames"])
        if not MIN_TRIAL_FRAMES <= expected_frames <= MAX_TRIAL_FRAMES:
            fail(f"{row['local_name']}: pinned frame count {expected_frames} outside selection window")
        if not re.fullmatch(r"single-plane-ophys_\d{6}_2026-\d\d-\d\d_\d\d-\d\d-\d\d/pophys/bci_\d{5}\.tif", row["key"]):
            fail(f"unexpected trial key {row['key']}")
        if int(row["key"][-9:-4]) != int(row["file_index"]):
            fail(f"{row['key']}: file_index column mismatch")


# --------------------------------------------------------------------------
# hashing


def file_digests(path: Path, part_size: int | None) -> tuple[str, str]:
    """Return (sha256, S3-style ETag) in one pass."""
    sha = hashlib.sha256()
    whole_md5 = hashlib.md5()
    part_digests: list[bytes] = []
    part_md5 = hashlib.md5()
    in_part = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(4 * 1024 * 1024)
            if not block:
                break
            sha.update(block)
            whole_md5.update(block)
            if part_size:
                view = memoryview(block)
                while view:
                    take = min(len(view), part_size - in_part)
                    part_md5.update(view[:take])
                    in_part += take
                    view = view[take:]
                    if in_part == part_size:
                        part_digests.append(part_md5.digest())
                        part_md5 = hashlib.md5()
                        in_part = 0
    if part_size:
        if in_part:
            part_digests.append(part_md5.digest())
        etag = hashlib.md5(b"".join(part_digests)).hexdigest() + f"-{len(part_digests)}"
    else:
        etag = whole_md5.hexdigest()
    return sha.hexdigest(), etag


# --------------------------------------------------------------------------
# ScanImage BigTIFF parsing


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.split("\n"):
        if " = " in line:
            key, value = line.split(" = ", 1)
            values[key.strip()] = value.strip()
    return values


def parse_scanimage_header(buf) -> dict:
    if len(buf) < 32:
        fail("file shorter than BigTIFF + ScanImage header")
    if bytes(buf[:4]) != b"II+\x00":
        fail("not a little-endian BigTIFF (expected 'II', version 43)")
    offset_size, reserved = struct.unpack_from("<HH", buf, 4)
    if offset_size != 8 or reserved != 0:
        fail(f"unexpected BigTIFF offset size {offset_size}/{reserved}")
    first_ifd = struct.unpack_from("<Q", buf, 8)[0]
    magic, version, text_len, roi_len = struct.unpack_from("<IIII", buf, 16)
    if magic != SI_MAGIC or version != SI_HEADER_VERSION:
        fail(f"missing ScanImage static header (magic={magic} version={version})")
    if 32 + text_len + roi_len > first_ifd or first_ifd >= len(buf):
        fail("ScanImage header overlaps the first IFD")
    text = bytes(buf[32 : 32 + text_len]).rstrip(b"\x00").decode("utf-8", errors="strict")
    roi_raw = bytes(buf[32 + text_len : 32 + text_len + roi_len]).rstrip(b"\x00")
    try:
        roi = json.loads(roi_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"ScanImage ROI JSON does not parse: {exc}")
    if "RoiGroups" not in roi:
        fail("ScanImage ROI JSON lacks RoiGroups")
    si = parse_key_values(text)
    for key, expected in EXPECTED_SI.items():
        if si.get(key) != expected:
            fail(f"ScanImage setting {key} = {si.get(key)!r}, expected {expected!r}")
    try:
        frame_rate = float(si.get("SI.hRoiManager.scanFrameRate", "nan"))
    except ValueError:
        frame_rate = float("nan")
    if not abs(frame_rate - FRAME_RATE_HZ) < 1e-6:
        fail(f"scanFrameRate {si.get('SI.hRoiManager.scanFrameRate')!r} != {FRAME_RATE_HZ}")
    subtract = si.get("SI.hScan2D.channelsSubtractOffsets", "")
    flags = subtract.strip("[]").split()
    if len(flags) < 2 or flags[1] != "true":
        fail(f"channel 2 offset subtraction not enabled: {subtract!r}")
    offsets = si.get("SI.hScan2D.channelOffsets", "").strip("[]").split()
    if len(offsets) < 2:
        fail("missing SI.hScan2D.channelOffsets")
    return {
        "first_ifd": first_ifd,
        "si": si,
        "frame_rate_hz": frame_rate,
        "channel2_offset": int(offsets[1]),
    }


def _tag_scalar(buf, entry_offset: int, typ: int, count: int) -> int:
    if count != 1:
        fail(f"expected scalar tag value, count={count}")
    value_offset = entry_offset + 12
    if typ == 3:
        return struct.unpack_from("<H", buf, value_offset)[0]
    if typ == 4:
        return struct.unpack_from("<I", buf, value_offset)[0]
    if typ == 16:
        return struct.unpack_from("<Q", buf, value_offset)[0]
    fail(f"unexpected scalar tag type {typ}")
    return 0


def _tag_ascii(buf, entry_offset: int, typ: int, count: int) -> str:
    if typ != 2:
        fail(f"expected ASCII tag, type={typ}")
    if count <= 8:
        raw = bytes(buf[entry_offset + 12 : entry_offset + 12 + count])
    else:
        pointer = struct.unpack_from("<Q", buf, entry_offset + 12)[0]
        if pointer + count > len(buf):
            fail("ASCII tag points past end of file")
        raw = bytes(buf[pointer : pointer + count])
    return raw.rstrip(b"\x00").decode("latin-1")


REQUIRED_PAGE_TAGS = {
    256: WIDTH,  # ImageWidth
    257: HEIGHT,  # ImageLength
    258: 16,  # BitsPerSample
    259: 1,  # Compression: none
    262: 1,  # PhotometricInterpretation: BlackIsZero
    277: 1,  # SamplesPerPixel
    278: HEIGHT,  # RowsPerStrip (one strip per page)
    279: FRAME_BYTES,  # StripByteCounts
    284: 1,  # PlanarConfiguration: contiguous
    339: 2,  # SampleFormat: signed integer
}


def walk_pages(buf, first_ifd: int) -> tuple[list[int], int]:
    """Follow the IFD chain; return (strip offset of every page in order,
    ScanImage acquisition number).

    Asserts every page is one uncompressed 512x256 int16 strip and that the
    per-frame ScanImage descriptors describe one complete acquisition: one
    constant acquisitionNumbers value (ScanImage's acquisition counter, which
    need not equal the file's _NNNNN index), contiguous frame numbering, and
    endOfAcquisition = 1 on the last page only.
    """
    size = len(buf)
    strips: list[int] = []
    offset = first_ifd
    visited: set[int] = set()
    previous_frame_number = None
    previous_timestamp = None
    end_seen = False
    acquisition = None
    while offset:
        if offset in visited or offset + 8 > size:
            fail(f"bad IFD offset {offset}")
        if end_seen:
            fail("pages continue after endOfAcquisition = 1")
        visited.add(offset)
        count = struct.unpack_from("<Q", buf, offset)[0]
        if not 8 <= count <= 64 or offset + 8 + count * 20 + 8 > size:
            fail(f"implausible IFD entry count {count} at {offset}")
        values: dict[int, int] = {}
        description = None
        strip_offset = None
        for index in range(count):
            entry = offset + 8 + index * 20
            tag, typ, n = struct.unpack_from("<HHQ", buf, entry)
            if typ not in TIFF_TYPE_SIZES:
                fail(f"unknown TIFF type {typ} for tag {tag}")
            if tag in REQUIRED_PAGE_TAGS:
                values[tag] = _tag_scalar(buf, entry, typ, n)
            elif tag == 273:
                strip_offset = _tag_scalar(buf, entry, typ, n)
            elif tag == 270:
                description = _tag_ascii(buf, entry, typ, n)
        for tag, expected in REQUIRED_PAGE_TAGS.items():
            if values.get(tag) != expected:
                fail(f"page {len(strips)}: tag {tag} = {values.get(tag)!r}, expected {expected}")
        if strip_offset is None or strip_offset + FRAME_BYTES > size:
            fail(f"page {len(strips)}: missing or truncated strip")
        if strips and strip_offset < strips[-1] + FRAME_BYTES:
            fail(f"page {len(strips)}: strips overlap or are out of order")
        if description is None:
            fail(f"page {len(strips)}: missing ScanImage frame descriptor")
        frame = parse_key_values(description)
        try:
            frame_in_acq = int(frame["frameNumberAcquisition"])
            acq_number = int(frame["acquisitionNumbers"])
            frame_number = int(frame["frameNumbers"])
            end_flag = int(frame["endOfAcquisition"])
            timestamp = float(frame["frameTimestamps_sec"])
        except (KeyError, ValueError) as exc:
            fail(f"page {len(strips)}: malformed frame descriptor ({exc})")
        if frame_in_acq != len(strips) + 1:
            fail(f"page {len(strips)}: frameNumberAcquisition {frame_in_acq} is not contiguous")
        if acquisition is None:
            if acq_number < 1:
                fail(f"page 0: acquisitionNumbers {acq_number}")
            acquisition = acq_number
        elif acq_number != acquisition:
            fail(f"page {len(strips)}: acquisitionNumbers {acq_number} != {acquisition} (pages from several acquisitions)")
        if previous_frame_number is not None and frame_number != previous_frame_number + 1:
            fail(f"page {len(strips)}: frameNumbers gap ({previous_frame_number} -> {frame_number})")
        if previous_timestamp is not None and not timestamp > previous_timestamp:
            fail(f"page {len(strips)}: frame timestamps not increasing")
        if end_flag not in (0, 1):
            fail(f"page {len(strips)}: endOfAcquisition = {end_flag}")
        end_seen = end_flag == 1
        previous_frame_number = frame_number
        previous_timestamp = timestamp
        strips.append(strip_offset)
        next_offset = struct.unpack_from("<Q", buf, offset + 8 + count * 20)[0]
        if next_offset and next_offset <= offset:
            fail("IFD chain moves backwards")
        offset = next_offset
    if not strips:
        fail("no pages")
    if not end_seen:
        fail("final page lacks endOfAcquisition = 1 (incomplete acquisition)")
    if strips[-1] + FRAME_BYTES != size:
        fail(f"final strip ends at {strips[-1] + FRAME_BYTES}, file size {size}")
    return strips, acquisition


def inspect_trial(path: Path) -> dict:
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as buf:
        header = parse_scanimage_header(buf)
        strips, acquisition = walk_pages(buf, header["first_ifd"])
    header.pop("si")
    header["frames"] = len(strips)
    header["strips"] = strips
    header["scanimage_acquisition_number"] = acquisition
    return header


# --------------------------------------------------------------------------
# metadata JSON checks


def check_data_description(path: Path, row: dict) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("license") != LICENSE_ID:
        fail(f"{path.name}: license {doc.get('license')!r} != {LICENSE_ID}")
    if doc.get("restrictions") not in (None, ""):
        fail(f"{path.name}: restrictions {doc.get('restrictions')!r}")
    if doc.get("project_name") != PROJECT_NAME:
        fail(f"{path.name}: project_name {doc.get('project_name')!r}")
    if str(doc.get("subject_id")) != row["subject_id"] or doc.get("name") != row["session_name"]:
        fail(f"{path.name}: subject/name mismatch")
    if doc.get("data_level") != "raw":
        fail(f"{path.name}: data_level {doc.get('data_level')!r}")


def check_session(path: Path, row: dict) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("rig_id") != RIG_ID:
        fail(f"{path.name}: rig_id {doc.get('rig_id')!r} != {RIG_ID}")
    if doc.get("session_type") != "BCI" or str(doc.get("subject_id")) != row["subject_id"]:
        fail(f"{path.name}: session_type/subject mismatch")
    streams = [s for s in doc.get("data_streams", []) if (s.get("notes") or "") == "tiff_stem:bci"]
    if len(streams) != 1:
        fail(f"{path.name}: expected one tiff_stem:bci stream, found {len(streams)}")
    stream = streams[0]
    detectors = [d.get("name") for d in stream.get("detectors", [])]
    if detectors != ["Red PMT"]:
        fail(f"{path.name}: bci stream detectors {detectors}")
    fovs = stream.get("ophys_fovs", [])
    if len(fovs) != 1:
        fail(f"{path.name}: expected one FOV")
    fov = fovs[0]
    if fov.get("fov_width") != WIDTH or fov.get("fov_height") != HEIGHT:
        fail(f"{path.name}: FOV {fov.get('fov_width')}x{fov.get('fov_height')}")
    if abs(float(fov.get("frame_rate")) - FRAME_RATE_HZ) > 1e-6:
        fail(f"{path.name}: frame_rate {fov.get('frame_rate')}")


# --------------------------------------------------------------------------
# subcommands


def cmd_check_sources(args) -> int:
    check_sources(load_sources(args.sources))
    print(f"sources_ok trials={EXPECTED_TRIALS} trial_bytes={EXPECTED_TRIAL_BYTES} frames={EXPECTED_FRAMES}")
    return 0


def cmd_plan(args) -> int:
    rows = load_sources(args.sources)
    check_sources(rows)
    order = {"data_description": 0, "session": 1, "trial_tiff": 2}
    for row in sorted(rows, key=lambda r: (order[r["kind"]], r["subject_id"])):
        print("\t".join([row["kind"], row["local_name"], row["size_bytes"], object_url(row)]))
    return 0


def find_row(rows: list[dict], local_name: str) -> dict:
    matches = [row for row in rows if row["local_name"] == local_name]
    if len(matches) != 1:
        fail(f"no unique pin for {local_name}")
    return matches[0]


def validate_object(path: Path, row: dict) -> dict:
    size = path.stat().st_size
    if size != int(row["size_bytes"]):
        raise IntegrityError(f"{row['local_name']}: size {size} != pinned {row['size_bytes']}")
    part_size = int(row["part_size_bytes"]) if row["part_size_bytes"] else None
    sha256, etag = file_digests(path, part_size)
    if etag != row["etag"]:
        raise IntegrityError(f"{row['local_name']}: S3 ETag mismatch computed={etag} pinned={row['etag']}")
    if row["sha256"] and sha256 != row["sha256"]:
        raise IntegrityError(f"{row['local_name']}: SHA-256 mismatch computed={sha256} pinned={row['sha256']}")
    frames = "-"
    if row["kind"] == "data_description":
        check_data_description(path, row)
    elif row["kind"] == "session":
        check_session(path, row)
    elif row["kind"] == "trial_tiff":
        info = inspect_trial(path)
        if info["frames"] != int(row["expected_frames"]) or info["first_ifd"] != int(row["first_ifd_offset"]):
            fail(f"{row['local_name']}: frames={info['frames']} first_ifd={info['first_ifd']} differ from pins")
        frames = str(info["frames"])
    else:
        fail(f"unknown kind {row['kind']}")
    return {"sha256": sha256, "etag": etag, "frames": frames, "size": size}


def cmd_validate(args) -> int:
    rows = load_sources(args.sources)
    row = find_row(rows, args.local_name)
    try:
        result = validate_object(args.path, row)
    except IntegrityError as exc:
        print(f"CORRUPT {args.local_name}: {exc}", file=sys.stderr)
        return 3
    except ValidationError as exc:
        print(f"INVALID {args.local_name}: {exc}", file=sys.stderr)
        return 2
    print(
        "\t".join(
            [row["kind"], row["local_name"], str(result["size"]), result["etag"], result["sha256"], result["frames"], row["version_id"], row["key"]]
        )
    )
    return 0


def histogram_summary(histogram: list[int]) -> dict:
    """Summaries of a signed int16 histogram indexed by value & 0xFFFF."""
    ordered = [(index - 65536 if index >= 32768 else index, count) for index, count in enumerate(histogram) if count]
    ordered.sort()
    total = sum(count for _, count in ordered)
    def quantile(q: float) -> int:
        threshold = q * (total - 1)
        running = 0
        for value, count in ordered:
            running += count
            if running - 1 >= threshold:
                return value
        return ordered[-1][0]
    mode_value = max(ordered, key=lambda item: item[1])[0]
    return {
        "values": total,
        "min": ordered[0][0],
        "max": ordered[-1][0],
        "distinct_values": len(ordered),
        "mode": mode_value,
        "p01": quantile(0.01),
        "p50": quantile(0.50),
        "p99": quantile(0.99),
        "negative_fraction": round(sum(c for v, c in ordered if v < 0) / total, 6),
        "saturated_values": histogram[0x8000] + histogram[0x7FFF],
    }


def sample_name(row: dict) -> str:
    session_tag = row["session_name"].replace("single-plane-ophys_", "")
    return f"{session_tag}_bci_{int(row['file_index']):05d}.i16"


def cmd_build(args) -> int:
    rows = load_sources(args.sources)
    check_sources(rows)
    downloads = args.downloads
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    data_root = args.data_root.resolve()

    for row in rows:
        if row["kind"] == "data_description":
            check_data_description(downloads / row["local_name"], row)
        elif row["kind"] == "session":
            check_session(downloads / row["local_name"], row)

    index_rows = []
    stats = []
    expected_names = set()
    for row in trial_rows(rows):
        source = downloads / row["local_name"]
        if not source.is_file() or source.stat().st_size != int(row["size_bytes"]):
            fail(f"missing or wrong-sized local source {source}")
        if row["sha256"]:
            sha256, _ = file_digests(source, None)
            if sha256 != row["sha256"]:
                fail(f"{source.name}: SHA-256 changed since download")
        info = inspect_trial(source)
        if info["frames"] != int(row["expected_frames"]):
            fail(f"{source.name}: {info['frames']} frames, pinned {row['expected_frames']}")
        name = sample_name(row)
        expected_names.add(name)
        target = series_dir / name
        tmp = target.with_suffix(".i16.tmp")
        digest = hashlib.sha256()
        histogram = [0] * 65536  # indexed by value & 0xFFFF
        constant_frames = 0
        with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as buf, tmp.open("wb") as out:
            for strip in info["strips"]:
                raw = buf[strip : strip + FRAME_BYTES]
                out.write(raw)
                digest.update(raw)
                if raw == raw[:2] * FRAME_VALUES:
                    constant_frames += 1
                values = array.array("h")
                values.frombytes(raw)
                if sys.byteorder != "little":
                    values.byteswap()
                for value, count in collections.Counter(values).items():
                    histogram[value & 0xFFFF] += count
        os.replace(tmp, target)
        frames = info["frames"]
        size = frames * FRAME_BYTES
        if target.stat().st_size != size:
            fail(f"{name}: wrote {target.stat().st_size} bytes, expected {size}")
        summary = histogram_summary(histogram)
        minimum = summary["min"]
        maximum = summary["max"]
        distinct = summary["distinct_values"]
        if summary["values"] != frames * FRAME_VALUES:
            fail(f"{name}: histogram covers {summary['values']} values")
        if constant_frames or distinct < 256 or minimum == maximum:
            fail(f"{name}: degenerate output (constant_frames={constant_frames} distinct={distinct})")
        sample_sha = digest.hexdigest()
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(target.resolve().relative_to(data_root)),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": size,
                "value_count": frames * FRAME_VALUES,
                "shape": [frames, HEIGHT, WIDTH],
                "axes": ["frame", "scan_line", "pixel"],
                "frame_rate_hz": info["frame_rate_hz"],
                "subject_id": row["subject_id"],
                "session_name": row["session_name"],
                "file_index": int(row["file_index"]),
                "scanimage_acquisition_number": info["scanimage_acquisition_number"],
                "source_key": row["key"],
                "source_version_id": row["version_id"],
                "source_size_bytes": int(row["size_bytes"]),
                "channel2_offset_subtracted": info["channel2_offset"],
                "min": minimum,
                "max": maximum,
                "distinct_values": distinct,
                "sample_sha256": sample_sha,
            }
        )
        stats.append({"sample": name, "subject_id": row["subject_id"], "frames": frames, **summary})
        print(f"sample {name} frames={frames} bytes={size} min={minimum} max={maximum} distinct={distinct}", flush=True)

    for stale in series_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
    with args.index.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    total_bytes = sum(item["sample_size_bytes"] for item in index_rows)
    total_values = sum(item["value_count"] for item in index_rows)
    args.stats.write_text(
        json.dumps(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "samples": len(index_rows),
                "frames": sum(item["shape"][0] for item in index_rows),
                "total_values": total_values,
                "total_bytes": total_bytes,
                "per_sample": stats,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"build_ok samples={len(index_rows)} values={total_values} bytes={total_bytes}")
    return 0


# --------------------------------------------------------------------------
# synthetic self-test


def synthetic_trial(
    frames: int,
    acquisition: int = 7,
    width: int = WIDTH,
    compression: int = 1,
    channel_save: str = "2",
    final_eoa: int = 1,
    truncate: int = 0,
    acquisition_change_page: int | None = None,
) -> tuple[bytes, list[bytes]]:
    """Build a ScanImage-2023-like BigTIFF with per-page descriptors."""
    si_lines = [f"{key} = {value}" for key, value in EXPECTED_SI.items() if key != "SI.hChannels.channelSave"]
    si_lines += [
        f"SI.hChannels.channelSave = {channel_save}",
        f"SI.hRoiManager.scanFrameRate = {FRAME_RATE_HZ!r}",
        "SI.hScan2D.channelsSubtractOffsets = [true true true true]",
        "SI.hScan2D.channelOffsets = [850 -597 1477 648]",
    ]
    si_text = ("\n".join(si_lines) + "\n").encode() + b"\x00"
    roi_text = json.dumps({"RoiGroups": {"imagingRoiGroup": {"rois": {}}}}).encode() + b"\x00"
    header = bytearray(b"II+\x00" + struct.pack("<HHQ", 8, 0, 0))
    header += struct.pack("<IIII", SI_MAGIC, SI_HEADER_VERSION, len(si_text), len(roi_text))
    header += si_text + roi_text
    first_ifd = len(header)
    struct.pack_into("<Q", header, 8, first_ifd)
    out = bytearray(header)
    payloads = []
    desc_len = 2001
    tags_count = 14
    ifd_bytes = 8 + tags_count * 20 + 8
    for page in range(frames):
        ifd_offset = len(out)
        desc_offset = ifd_offset + ifd_bytes
        strip_offset = desc_offset + desc_len + (2384 - ifd_bytes - desc_len)
        next_offset = 0 if page == frames - 1 else strip_offset + FRAME_BYTES
        eoa = final_eoa if page == frames - 1 else 0
        desc = (
            f"frameNumbers = {100 + page}\nacquisitionNumbers = {acquisition + (1 if acquisition_change_page is not None and page >= acquisition_change_page else 0)}\n"
            f"frameNumberAcquisition = {page + 1}\n"
            f"frameTimestamps_sec = {1.0 + page / FRAME_RATE_HZ:.9f}\nendOfAcquisition = {eoa}\n"
        ).encode()
        desc = desc.ljust(desc_len - 1, b" ") + b"\x00"
        entries = [
            (256, 3, 1, width),
            (257, 3, 1, HEIGHT),
            (258, 3, 1, 16),
            (259, 3, 1, compression),
            (262, 3, 1, 1),
            (270, 2, desc_len, desc_offset),
            (273, 16, 1, strip_offset),
            (274, 3, 1, 1),
            (277, 3, 1, 1),
            (278, 3, 1, HEIGHT),
            (279, 16, 1, FRAME_BYTES),
            (284, 3, 1, 1),
            (296, 3, 1, 3),
            (339, 3, 1, 2),
        ]
        block = bytearray(struct.pack("<Q", len(entries)))
        for tag, typ, count, value in entries:
            if typ == 3:
                block += struct.pack("<HHQHHI", tag, typ, count, value, 0, 0)
            else:
                block += struct.pack("<HHQQ", tag, typ, count, value)
        block += struct.pack("<Q", next_offset)
        out += block
        out += desc
        out += b"\x00" * (strip_offset - len(out))
        values = array.array("h", [((page * 7919 + i * 31) % 5000) - 80 for i in range(FRAME_VALUES)])
        if sys.byteorder != "little":
            values.byteswap()
        payload = values.tobytes()
        payloads.append(payload)
        out += payload
    data = bytes(out)
    if truncate:
        data = data[:-truncate]
    return data, payloads


def cmd_selftest(_args) -> int:
    with tempfile.TemporaryDirectory(prefix="aind_bci_selftest_") as tmp:
        tmpdir = Path(tmp)
        good, payloads = synthetic_trial(frames=4)
        path = tmpdir / "good.tif"
        path.write_bytes(good)
        info = inspect_trial(path)
        assert info["frames"] == 4 and info["scanimage_acquisition_number"] == 7, info
        with path.open("rb") as handle:
            data = handle.read()
        for strip, payload in zip(info["strips"], payloads):
            assert data[strip : strip + FRAME_BYTES] == payload
        assert info["channel2_offset"] == -597
        print("selftest good file: ok (4 pages, byte-exact strips)")
        bad_cases = {
            "wrong_width": dict(width=256),
            "compressed": dict(compression=5),
            "two_channels": dict(channel_save="[1 2]"),
            "no_end_of_acquisition": dict(final_eoa=0),
            "truncated_last_page": dict(truncate=1000),
            "mixed_acquisition_numbers": dict(acquisition_change_page=2),
        }
        for label, kwargs in bad_cases.items():
            blob, _ = synthetic_trial(frames=3, **kwargs)
            bad = tmpdir / f"{label}.tif"
            bad.write_bytes(blob)
            try:
                inspect_trial(bad)
            except (ValidationError, struct.error) as exc:
                print(f"selftest {label}: rejected ({exc})")
            else:
                raise SystemExit(f"selftest {label}: NOT rejected")
        # A file numbered differently from its ScanImage acquisition counter
        # (observed upstream: 820614 bci_00011.tif carries acquisitionNumbers 9)
        # is valid as long as the number is constant across its pages.
        renumbered, _ = synthetic_trial(frames=3, acquisition=9)
        other = tmpdir / "bci_00011.tif"
        other.write_bytes(renumbered)
        assert inspect_trial(other)["scanimage_acquisition_number"] == 9
        print("selftest file_index != acquisitionNumbers: accepted")
        sha, etag = file_digests(path, 1 << 20)
        parts = [good[i : i + (1 << 20)] for i in range(0, len(good), 1 << 20)]
        expected_etag = hashlib.md5(b"".join(hashlib.md5(p).digest() for p in parts)).hexdigest() + f"-{len(parts)}"
        assert etag == expected_etag and sha == hashlib.sha256(good).hexdigest()
        print("selftest multipart etag: ok")
    print("selftest_ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-sources")
    p.add_argument("--sources", type=Path, required=True)
    p.set_defaults(func=cmd_check_sources)
    p = sub.add_parser("plan")
    p.add_argument("--sources", type=Path, required=True)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("validate")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--local-name", required=True)
    p.add_argument("--path", type=Path, required=True)
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("build")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.add_argument("--samples-dir", type=Path, required=True)
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--stats", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)
    args = parser.parse_args()
    try:
        return args.func(args)
    except ValidationError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
