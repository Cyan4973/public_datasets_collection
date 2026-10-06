#!/usr/bin/env python3
"""Cartographer 2D-backpack Hokuyo horizontal-laser range recipe helper.

Pure standard library. Subcommands:

  index-summary  summarize a bag from its header bytes and index-section tail
                 (used by discover.sh and download.sh; no message payloads)
  validate-bag   validate one downloaded bag's header and index section
                 against its sources.tsv pins (used by download.sh)
  build          sequentially decode every chunk of every pinned bag and emit
                 one scans x 1079 little-endian float32 first-echo range
                 matrix per bag, plus the sample index
  verify         independently re-derive every sample through the bag index
                 section (chunk-info -> chunk -> index-data offsets), compare
                 byte-for-byte, and check the index, manifest and value policy

ROS bag v2.0 record layout: uint32 header_len, header fields
(uint32 field_len + b"name=value"), uint32 data_len, data.
Ops: 2 message data, 3 bag header, 4 index data, 5 chunk, 6 chunk info,
7 connection.
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import math
import multiprocessing
import os
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "cartographer_backpack2d_hokuyo_ranges_f32"
SERIES_ID = "hokuyo_horizontal_first_echo_range_f32"
TOPIC = "horizontal_laser_2d"
MSG_TYPE = "sensor_msgs/MultiEchoLaserScan"
MSG_MD5 = "6fefb0c6da89d7c8abe4b339f5c2f8fb"
EXPECTED_TOPICS = {"horizontal_laser_2d", "vertical_laser_2d", "imu"}
MAGIC = b"#ROSBAG V2.0\n"
HEAD_BYTES = 8192
BEAMS = 1079
# float32 bit patterns of the fixed scan geometry shared by b0/b1/b2.
GEOMETRY_BITS = {
    "angle_min": 0xC0168467,
    "angle_max": 0x40168467,
    "angle_increment": 0x3B8EFA35,
    "scan_time": 0x3CCCCCCD,
    "range_min": 0x3CBC6A7F,
    "range_max": 0x42700000,
}
RANGE_MIN = struct.unpack("<f", struct.pack("<I", GEOMETRY_BITS["range_min"]))[0]
RANGE_MAX = 60.0
SENTINEL_BYTES = struct.pack("<f", RANGE_MAX)
NAN_BYTES = struct.pack("<I", 0x7FC00000)
MAX_SENTINEL_FRACTION = 0.5
MIN_DISTINCT_VALUES = 1000
MIN_LATTICE_FRACTION = 0.999
MAX_SCAN_GAP_NS = 1_000_000_000  # reject sessions whose horizontal stream has a >1 s hole
U32 = struct.Struct("<I")
F32 = struct.Struct("<f")


class BagError(Exception):
    pass


# --------------------------------------------------------------------------
# generic record helpers
# --------------------------------------------------------------------------

def parse_fields(header: bytes) -> dict[str, bytes]:
    fields: dict[str, bytes] = {}
    pos = 0
    end = len(header)
    while pos < end:
        if pos + 4 > end:
            raise BagError("truncated header field length")
        (length,) = U32.unpack_from(header, pos)
        pos += 4
        if pos + length > end:
            raise BagError("truncated header field")
        field = header[pos : pos + length]
        pos += length
        name, sep, value = field.partition(b"=")
        if not sep:
            raise BagError(f"header field without '=': {field[:40]!r}")
        fields[name.decode("ascii")] = value
    return fields


def u32(fields: dict[str, bytes], name: str) -> int:
    value = fields.get(name)
    if value is None or len(value) != 4:
        raise BagError(f"missing or malformed uint32 field {name!r}")
    return U32.unpack(value)[0]


def u64(fields: dict[str, bytes], name: str) -> int:
    value = fields.get(name)
    if value is None or len(value) != 8:
        raise BagError(f"missing or malformed uint64 field {name!r}")
    return struct.unpack("<Q", value)[0]


def op_of(fields: dict[str, bytes]) -> int:
    value = fields.get("op")
    if value is None or len(value) != 1:
        raise BagError("record without a one-byte op field")
    return value[0]


def iter_buffer_records(buf: bytes, start: int = 0, end: int | None = None):
    """Yield (offset, fields, data_start, data_end) for complete records in buf[start:end]."""
    pos = start
    end = len(buf) if end is None else end
    while pos < end:
        if pos + 4 > end:
            raise BagError("truncated record header length")
        (header_len,) = U32.unpack_from(buf, pos)
        header_end = pos + 4 + header_len
        if header_end + 4 > end:
            raise BagError("truncated record header")
        fields = parse_fields(buf[pos + 4 : header_end])
        (data_len,) = U32.unpack_from(buf, header_end)
        data_start = header_end + 4
        data_end = data_start + data_len
        if data_end > end:
            raise BagError("truncated record data")
        yield pos, fields, data_start, data_end
        pos = data_end


def read_file_record(handle, offset: int, file_size: int):
    """Read one top-level record at offset; return (fields, data, next_offset)."""
    handle.seek(offset)
    raw = handle.read(4)
    if len(raw) != 4:
        raise BagError(f"truncated record at {offset}")
    (header_len,) = U32.unpack(raw)
    if offset + 8 + header_len > file_size:
        raise BagError(f"record header at {offset} overruns file")
    header = handle.read(header_len)
    fields = parse_fields(header)
    (data_len,) = U32.unpack(handle.read(4))
    next_offset = offset + 8 + header_len + data_len
    if next_offset > file_size:
        raise BagError(f"record data at {offset} overruns file")
    data = handle.read(data_len)
    if len(data) != data_len:
        raise BagError(f"short read at {offset}")
    return fields, data, next_offset


def parse_bag_header(head: bytes) -> dict:
    if head[: len(MAGIC)] != MAGIC:
        raise BagError("missing '#ROSBAG V2.0' magic")
    # the bag-header record pads header+data to 4,096 bytes (plus two length words)
    _, fields, data_start, data_end = next(iter_buffer_records(head, len(MAGIC)))
    if op_of(fields) != 3:
        raise BagError("first record is not a bag header")
    return {
        "index_pos": u64(fields, "index_pos"),
        "conn_count": u32(fields, "conn_count"),
        "chunk_count": u32(fields, "chunk_count"),
        "header_end": data_end,
    }


def parse_connection_data(data: bytes) -> dict[str, str]:
    fields = parse_fields(data)
    return {
        "topic": fields.get("topic", b"").decode("utf-8"),
        "type": fields.get("type", b"").decode("utf-8"),
        "md5sum": fields.get("md5sum", b"").decode("ascii"),
    }


def parse_index_section(tail: bytes, conn_count: int, chunk_count: int) -> dict:
    """Parse the connection and chunk-info records after index_pos."""
    connections: dict[int, dict[str, str]] = {}
    chunk_infos: list[dict] = []
    for _, fields, data_start, data_end in iter_buffer_records(tail, 0):
        op = op_of(fields)
        data = tail[data_start:data_end]
        if op == 7:
            conn = u32(fields, "conn")
            info = parse_connection_data(data)
            if fields.get("topic", b"").decode("utf-8") != info["topic"]:
                raise BagError("connection record topic mismatch")
            if conn in connections:
                raise BagError(f"duplicate connection {conn}")
            connections[conn] = info
        elif op == 6:
            if u32(fields, "ver") != 1:
                raise BagError("unsupported chunk-info version")
            count = u32(fields, "count")
            if len(data) != 8 * count:
                raise BagError("chunk-info data length mismatch")
            counts = {}
            for index in range(count):
                conn, messages = struct.unpack_from("<II", data, 8 * index)
                counts[conn] = messages
            start_sec, start_nsec = struct.unpack("<II", fields["start_time"])
            end_sec, end_nsec = struct.unpack("<II", fields["end_time"])
            chunk_infos.append(
                {
                    "chunk_pos": u64(fields, "chunk_pos"),
                    "start": (start_sec, start_nsec),
                    "end": (end_sec, end_nsec),
                    "counts": counts,
                }
            )
        else:
            raise BagError(f"unexpected op {op} in index section")
    if len(connections) != conn_count:
        raise BagError(f"index section has {len(connections)} connections, header says {conn_count}")
    if len(chunk_infos) != chunk_count:
        raise BagError(f"index section has {len(chunk_infos)} chunk infos, header says {chunk_count}")
    return {"connections": connections, "chunk_infos": chunk_infos}


def summarize_index(header: dict, index: dict) -> dict:
    connections = index["connections"]
    topics = {info["topic"] for info in connections.values()}
    if topics != EXPECTED_TOPICS:
        raise BagError(f"unexpected topic set {sorted(topics)}")
    laser = [conn for conn, info in connections.items() if info["topic"] == TOPIC]
    if len(laser) != 1:
        raise BagError(f"expected exactly one {TOPIC} connection, found {len(laser)}")
    conn = laser[0]
    if connections[conn]["type"] != MSG_TYPE or connections[conn]["md5sum"] != MSG_MD5:
        raise BagError(f"{TOPIC} connection type/md5 changed: {connections[conn]}")
    per_topic: dict[str, int] = {}
    for info in index["chunk_infos"]:
        for c, messages in info["counts"].items():
            if c not in connections:
                raise BagError(f"chunk info references unknown connection {c}")
            topic = connections[c]["topic"]
            per_topic[topic] = per_topic.get(topic, 0) + messages
    starts = [info["start"] for info in index["chunk_infos"]]
    ends = [info["end"] for info in index["chunk_infos"]]
    positions = [info["chunk_pos"] for info in index["chunk_infos"]]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise BagError("chunk positions are not strictly increasing")
    if positions and positions[-1] >= header["index_pos"]:
        raise BagError("chunk position beyond index_pos")
    first = min(starts)
    last = max(ends)
    return {
        "index_pos": header["index_pos"],
        "conn_count": header["conn_count"],
        "chunk_count": header["chunk_count"],
        "laser_conn": conn,
        "messages_per_topic": dict(sorted(per_topic.items())),
        "scan_count": per_topic.get(TOPIC, 0),
        "start_time": f"{first[0]}.{first[1]:09d}",
        "end_time": f"{last[0]}.{last[1]:09d}",
        "span_seconds": round((last[0] - first[0]) + (last[1] - first[1]) * 1e-9, 3),
    }


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

SOURCE_COLUMNS = [
    "bag",
    "unit",
    "floor",
    "duration_s",
    "size_bytes",
    "md5_base64",
    "crc32c_base64",
    "gcs_generation",
    "index_pos",
    "chunk_count",
    "scan_count",
]


def load_sources(path: Path) -> list[dict]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    header = lines[0].split("\t")
    if header != SOURCE_COLUMNS:
        raise SystemExit(f"unexpected sources.tsv header {header}")
    rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(header):
            raise SystemExit(f"malformed sources.tsv row: {line!r}")
        row = dict(zip(header, parts))
        for key in ("duration_s", "size_bytes", "gcs_generation", "index_pos", "chunk_count", "scan_count"):
            row[key] = int(row[key])
        rows.append(row)
    names = [row["bag"] for row in rows]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate bag in sources.tsv")
    return rows


def bag_path(data_root: Path, row: dict) -> Path:
    return data_root / "downloads" / DATASET_ID / "bags" / f"{row['bag']}.bag"


def sample_rel(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['bag']}.f32"


# --------------------------------------------------------------------------
# build path: sequential chunk walk
# --------------------------------------------------------------------------

def decode_scan_first_echo(data: bytes, start: int, end: int, stats: dict) -> bytes:
    """Decode one MultiEchoLaserScan payload; return 1079 first-echo float32 LE bytes."""
    unpack = U32.unpack_from
    pos = start
    if pos + 16 > end:
        raise BagError("truncated scan header")
    frame_len = unpack(data, pos + 12)[0]
    pos += 16 + frame_len
    if pos + 32 > end:
        raise BagError("truncated scan parameters")
    params = data[pos : pos + 28]
    bits = struct.unpack("<7I", params)
    for name, value in zip(
        ("angle_min", "angle_max", "angle_increment", "time_increment", "scan_time", "range_min", "range_max"), bits
    ):
        if name in GEOMETRY_BITS and GEOMETRY_BITS[name] != value:
            raise BagError(f"scan geometry {name} changed: 0x{value:08x}")
    stats["time_increment"].add(bits[3])
    pos += 28
    beams = unpack(data, pos)[0]
    pos += 4
    if beams != BEAMS:
        raise BagError(f"scan has {beams} range beams, expected {BEAMS}")
    out = bytearray(4 * BEAMS)
    echo_total = 0
    multi = 0
    zero = 0
    for beam in range(BEAMS):
        echoes = unpack(data, pos)[0]
        if echoes:
            out[4 * beam : 4 * beam + 4] = data[pos + 4 : pos + 8]
            if echoes > 1:
                multi += 1
        else:
            out[4 * beam : 4 * beam + 4] = NAN_BYTES
            zero += 1
        echo_total += echoes
        pos += 4 + 4 * echoes
        if pos > end:
            raise BagError("ranges overrun the message")
    # intensities: one LaserEcho per beam; validate the remaining length only.
    if pos + 4 > end:
        raise BagError("missing intensities array")
    intensity_beams = unpack(data, pos)[0]
    pos += 4
    remaining = end - pos
    if intensity_beams not in (0, BEAMS):
        raise BagError(f"unexpected intensity beam count {intensity_beams}")
    if intensity_beams == BEAMS and remaining != 4 * BEAMS + 4 * echo_total:
        # fall back to a full walk when intensity echo counts differ from range counts
        for _ in range(intensity_beams):
            echoes = unpack(data, pos)[0]
            pos += 4 + 4 * echoes
        if pos != end:
            raise BagError("intensities do not end at the message boundary")
    elif intensity_beams == 0 and remaining != 0:
        raise BagError("trailing bytes after empty intensities")
    stats["multi_echo_beams"] += multi
    stats["zero_echo_beams"] += zero
    return bytes(out)


def walk_bag(path: Path, expected: dict) -> tuple[bytes, dict]:
    """Sequentially walk every top-level record; return (sample bytes, stats)."""
    size = path.stat().st_size
    if size != expected["size_bytes"]:
        raise BagError(f"{path.name}: size {size} != pinned {expected['size_bytes']}")
    stats = {
        "time_increment": set(),
        "multi_echo_beams": 0,
        "zero_echo_beams": 0,
        "chunks": 0,
        "compression": set(),
        "record_time_regressions": 0,
        "stamp_regressions": 0,
        "max_scan_gap_ns": 0,
    }
    scans: list[bytes] = []
    connections: dict[int, dict[str, str]] = {}
    last_time = (0, 0)
    last_stamp = (0, 0)
    with path.open("rb") as handle:
        head = handle.read(HEAD_BYTES)
        header = parse_bag_header(head)
        if header["index_pos"] != expected["index_pos"] or header["chunk_count"] != expected["chunk_count"]:
            raise BagError(f"{path.name}: bag header changed {header}")
        offset = header["header_end"]
        index_pos = header["index_pos"]
        while offset < index_pos:
            fields, data, offset = read_file_record(handle, offset, size)
            op = op_of(fields)
            if op == 4:
                continue
            if op != 5:
                raise BagError(f"{path.name}: unexpected op {op} before index section")
            stats["chunks"] += 1
            compression = fields.get("compression", b"").decode("ascii")
            stats["compression"].add(compression)
            raw_size = u32(fields, "size")
            if compression == "bz2":
                raw = bz2.decompress(data)
            elif compression == "none":
                raw = data
            else:
                raise BagError(f"{path.name}: unsupported chunk compression {compression!r}")
            if len(raw) != raw_size:
                raise BagError(f"{path.name}: chunk size {len(raw)} != declared {raw_size}")
            for _, inner, data_start, data_end in iter_buffer_records(raw, 0):
                inner_op = op_of(inner)
                if inner_op == 7:
                    conn = u32(inner, "conn")
                    info = parse_connection_data(raw[data_start:data_end])
                    previous = connections.get(conn)
                    if previous is not None and previous != info:
                        raise BagError(f"{path.name}: connection {conn} redefined")
                    connections[conn] = info
                elif inner_op == 2:
                    conn = u32(inner, "conn")
                    info = connections.get(conn)
                    if info is None:
                        raise BagError(f"{path.name}: message before its connection record")
                    if info["topic"] != TOPIC:
                        continue
                    if info["type"] != MSG_TYPE or info["md5sum"] != MSG_MD5:
                        raise BagError(f"{path.name}: {TOPIC} type changed: {info}")
                    record_time = struct.unpack("<II", inner["time"])
                    if record_time < last_time:
                        stats["record_time_regressions"] += 1
                    if last_time != (0, 0):
                        gap = (record_time[0] - last_time[0]) * 1_000_000_000 + record_time[1] - last_time[1]
                        stats["max_scan_gap_ns"] = max(stats["max_scan_gap_ns"], gap)
                    last_time = record_time
                    stamp = struct.unpack_from("<II", raw, data_start + 4)
                    if stamp < last_stamp:
                        stats["stamp_regressions"] += 1
                    last_stamp = stamp
                    scans.append(decode_scan_first_echo(raw, data_start, data_end, stats))
                else:
                    raise BagError(f"{path.name}: unexpected op {inner_op} inside chunk")
        if offset != index_pos:
            raise BagError(f"{path.name}: chunk section does not end at index_pos")
        if stats["chunks"] != header["chunk_count"]:
            raise BagError(f"{path.name}: walked {stats['chunks']} chunks, header says {header['chunk_count']}")
        tail_records = 0
        while offset < size:
            fields, data, offset = read_file_record(handle, offset, size)
            if op_of(fields) not in (6, 7):
                raise BagError(f"{path.name}: unexpected op in index section")
            tail_records += 1
        if tail_records != header["chunk_count"] + header["conn_count"]:
            raise BagError(f"{path.name}: index section record count mismatch")
    if len(scans) != expected["scan_count"]:
        raise BagError(f"{path.name}: decoded {len(scans)} scans, pinned {expected['scan_count']}")
    if stats["record_time_regressions"]:
        raise BagError(f"{path.name}: {stats['record_time_regressions']} record-time regressions")
    if stats["max_scan_gap_ns"] > MAX_SCAN_GAP_NS:
        raise BagError(f"{path.name}: horizontal scan gap of {stats['max_scan_gap_ns'] / 1e9:.3f} s")
    stats["time_increment"] = sorted(F32.unpack(U32.pack(v))[0] for v in stats["time_increment"])
    stats["compression"] = sorted(stats["compression"])
    return b"".join(scans), stats


def value_stats(payload: bytes) -> dict:
    count = len(payload) // 4
    sentinel = 0
    nan = 0
    off_lattice = 0
    distinct: set[float] = set()
    minimum = math.inf
    maximum = -math.inf
    pack = F32.pack
    for (value,) in F32.iter_unpack(payload):
        if value != value:
            nan += 1
            continue
        if value == RANGE_MAX:
            sentinel += 1
        distinct.add(value)
        if value < minimum:
            minimum = value
        if value > maximum:
            maximum = value
        # every source range is float32(integer millimetres / 1000)
        if pack(round(value * 1000.0) / 1000.0) != pack(value):
            off_lattice += 1
    finite = count - nan
    return {
        "value_count": count,
        "range_max_sentinel_count": sentinel,
        "zero_echo_nan_count": nan,
        "off_mm_lattice_count": off_lattice,
        "distinct_values": len(distinct),
        "min": minimum if finite else None,
        "max": maximum if finite else None,
        "sentinel_fraction": round(sentinel / count, 6) if count else 0.0,
    }


def check_values(name: str, payload: bytes, vstats: dict) -> None:
    count = vstats["value_count"]
    if count == 0 or count % BEAMS:
        raise BagError(f"{name}: value count {count} is not a positive multiple of {BEAMS}")
    finite = count - vstats["zero_echo_nan_count"]
    if finite == 0:
        raise BagError(f"{name}: no finite values")
    if vstats["min"] < RANGE_MIN or vstats["max"] > RANGE_MAX:
        raise BagError(f"{name}: values outside [range_min, range_max]: {vstats['min']}..{vstats['max']}")
    if vstats["sentinel_fraction"] > MAX_SENTINEL_FRACTION:
        raise BagError(f"{name}: range_max sentinel fraction {vstats['sentinel_fraction']} too high")
    if vstats["distinct_values"] < MIN_DISTINCT_VALUES:
        raise BagError(f"{name}: only {vstats['distinct_values']} distinct values")
    if (finite - vstats["off_mm_lattice_count"]) / finite < MIN_LATTICE_FRACTION:
        raise BagError(f"{name}: values are not on the 1 mm float32 lattice")
    first_scan = payload[: 4 * BEAMS]
    if payload == first_scan * (count // BEAMS):
        raise BagError(f"{name}: every scan is identical")


def build_one(args: tuple) -> dict:
    data_root, row = args
    data_root = Path(data_root)
    path = bag_path(data_root, row)
    payload, stats = walk_bag(path, row)
    vstats = value_stats(payload)
    check_values(row["bag"], payload, vstats)
    if vstats["zero_echo_nan_count"] != stats["zero_echo_beams"]:
        raise BagError(f"{row['bag']}: NaN count does not match zero-echo beams")
    out_path = data_root / sample_rel(row)
    tmp_path = out_path.with_suffix(".f32.part")
    tmp_path.write_bytes(payload)
    tmp_path.replace(out_path)
    return {
        "bag": row["bag"],
        "scan_count": len(payload) // (4 * BEAMS),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "stats": stats,
        "values": vstats,
    }


def cmd_build(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root)
    data_root = (repo_root / args.data_dir).resolve()
    rows = load_sources(Path(args.sources))
    for row in rows:
        path = bag_path(data_root, row)
        if not path.is_file():
            raise SystemExit(f"missing local bag {path}; run download.sh first")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for directory in (sample_dir, index_dir, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    expected_names = {Path(sample_rel(row)).name for row in rows}
    for stale in sample_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
    workers = max(1, min(len(rows), args.workers, os.cpu_count() or 1))
    with multiprocessing.Pool(workers) as pool:
        results = pool.map(build_one, [(str(data_root), row) for row in rows], chunksize=1)
    by_bag = {result["bag"]: result for result in results}
    index_rows = []
    totals = {"samples": 0, "scans": 0, "values": 0, "bytes": 0, "sentinel": 0, "nan": 0, "multi_echo_beams": 0}
    for row in rows:
        result = by_bag[row["bag"]]
        values = result["values"]
        size = values["value_count"] * 4
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": sample_rel(row),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": size,
                "value_count": values["value_count"],
                "shape": [result["scan_count"], BEAMS],
                "axes": ["scan", "beam"],
                "source_bag": f"{row['bag']}.bag",
                "backpack_unit": row["unit"],
                "floor": row["floor"],
                "range_max_sentinel_count": values["range_max_sentinel_count"],
                "zero_echo_nan_count": values["zero_echo_nan_count"],
                "min": values["min"],
                "max": values["max"],
                "sha256": result["sha256"],
            }
        )
        totals["samples"] += 1
        totals["scans"] += result["scan_count"]
        totals["values"] += values["value_count"]
        totals["bytes"] += size
        totals["sentinel"] += values["range_max_sentinel_count"]
        totals["nan"] += values["zero_echo_nan_count"]
        totals["multi_echo_beams"] += result["stats"]["multi_echo_beams"]
        print(
            f"sample bag={row['bag']} unit={row['unit']} floor={row['floor']} scans={result['scan_count']} "
            f"bytes={size} sentinel={values['range_max_sentinel_count']} ({values['sentinel_fraction']:.4f}) "
            f"zero_echo_nan={values['zero_echo_nan_count']} multi_echo={result['stats']['multi_echo_beams']} "
            f"min={values['min']} max={values['max']} distinct={values['distinct_values']} "
            f"time_increment={result['stats']['time_increment']} compression={result['stats']['compression']} "
            f"max_scan_gap_s={result['stats']['max_scan_gap_ns'] / 1e9:.3f} stamp_regressions={result['stats']['stamp_regressions']}"
        )
    index_path = index_dir / "samples.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    stats_path = filtered_dir / "ingest_stats.json"
    stats_path.write_text(
        json.dumps({"totals": totals, "bags": results}, indent=2, sort_keys=True, default=list) + "\n",
        encoding="utf-8",
    )
    print(
        f"build_totals samples={totals['samples']} scans={totals['scans']} values={totals['values']} "
        f"bytes={totals['bytes']} sentinel={totals['sentinel']} zero_echo_nan={totals['nan']} "
        f"multi_echo_beams={totals['multi_echo_beams']}"
    )


# --------------------------------------------------------------------------
# verify path: index-driven random access, separate decoder
# --------------------------------------------------------------------------

def first_echoes_via_floats(data: bytes, start: int, end: int) -> tuple[list[float], int]:
    """Separate decoder: walk the ranges array as Python floats."""
    (frame_len,) = struct.unpack_from("<I", data, start + 12)
    pos = start + 16 + frame_len
    params = struct.unpack_from("<7f", data, pos)
    if params[5] != RANGE_MIN or params[6] != RANGE_MAX:
        raise BagError("verify: range_min/range_max changed")
    expected = [struct.unpack("<f", struct.pack("<I", GEOMETRY_BITS[key]))[0] for key in ("angle_min", "angle_max", "angle_increment")]
    if list(params[:3]) != expected:
        raise BagError("verify: angle geometry changed")
    pos += 28
    (beams,) = struct.unpack_from("<I", data, pos)
    pos += 4
    if beams != BEAMS:
        raise BagError("verify: beam count changed")
    values: list[float] = []
    zero = 0
    for _ in range(beams):
        (echoes,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if echoes == 0:
            values.append(math.nan)
            zero += 1
        else:
            echo_values = struct.unpack_from(f"<{echoes}f", data, pos)
            values.append(echo_values[0])
        pos += 4 * echoes
    (intensity_beams,) = struct.unpack_from("<I", data, pos)
    pos += 4
    for _ in range(intensity_beams):
        (echoes,) = struct.unpack_from("<I", data, pos)
        pos += 4 + 4 * echoes
    if pos != end:
        raise BagError("verify: message length mismatch")
    return values, zero


def iter_index_messages(path: Path, row: dict):
    """Yield ((sec, nsec), first-echo values, zero-echo count) for every laser
    message, located through chunk-info -> chunk -> index-data offsets."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = parse_bag_header(handle.read(HEAD_BYTES))
        handle.seek(header["index_pos"])
        tail = handle.read(size - header["index_pos"])
        index = parse_index_section(tail, header["conn_count"], header["chunk_count"])
        summary = summarize_index(header, index)
        if summary["scan_count"] != row["scan_count"] or summary["index_pos"] != row["index_pos"]:
            raise BagError(f"{path.name}: index section disagrees with sources.tsv")
        conn = summary["laser_conn"]
        for info in index["chunk_infos"]:
            fields, data, next_offset = read_file_record(handle, info["chunk_pos"], size)
            if op_of(fields) != 5:
                raise BagError("verify: chunk_pos does not point at a chunk")
            compression = fields["compression"].decode("ascii")
            if compression == "bz2":
                raw = bz2.decompress(data)
            elif compression == "none":
                raw = data
            else:
                raise BagError(f"verify: unsupported compression {compression!r}")
            offsets = None
            # one index-data record per connection directly follows its chunk
            position = next_offset
            for _ in range(len(info["counts"])):
                ifields, idata, position = read_file_record(handle, position, size)
                if op_of(ifields) != 4 or u32(ifields, "ver") != 1:
                    raise BagError("verify: expected index-data record after chunk")
                if u32(ifields, "conn") == conn:
                    count = u32(ifields, "count")
                    if len(idata) != 12 * count:
                        raise BagError("verify: index-data length mismatch")
                    offsets = [struct.unpack_from("<III", idata, 12 * i) for i in range(count)]
            expected_count = info["counts"].get(conn, 0)
            if expected_count == 0:
                continue
            if offsets is None or len(offsets) != expected_count:
                raise BagError("verify: index-data count disagrees with chunk info")
            for sec, nsec, offset in offsets:
                _, mfields, data_start, data_end = next(iter_buffer_records(raw, offset))
                if op_of(mfields) != 2 or u32(mfields, "conn") != conn:
                    raise BagError("verify: index offset does not point at a laser message")
                if struct.unpack("<II", mfields["time"]) != (sec, nsec):
                    raise BagError("verify: index time disagrees with message record time")
                values, zero = first_echoes_via_floats(raw, data_start, data_end)
                yield (sec, nsec), values, zero


def verify_one(args: tuple) -> dict:
    data_root, row, index_row = args
    data_root = Path(data_root)
    path = bag_path(data_root, row)
    sample_path = data_root / index_row["sample_path"]
    payload = sample_path.read_bytes()
    scan_bytes = 4 * BEAMS
    pack = F32.pack
    scans = 0
    zero_total = 0
    mismatched_scans = 0
    last_time = (0, 0)
    max_gap = 0
    for record_time, values, zero in iter_index_messages(path, row):
        if record_time < last_time:
            raise BagError(f"{row['bag']}: laser messages are not in record-time order")
        if last_time != (0, 0):
            max_gap = max(max_gap, (record_time[0] - last_time[0]) * 1_000_000_000 + record_time[1] - last_time[1])
        last_time = record_time
        expected = b"".join(NAN_BYTES if value != value else pack(value) for value in values)
        start = scans * scan_bytes
        if payload[start : start + scan_bytes] != expected:
            mismatched_scans += 1
        scans += 1
        zero_total += zero
    if len(payload) != scans * scan_bytes:
        raise BagError(f"{row['bag']}: sample size disagrees with re-derived scan count {scans}")
    if max_gap > MAX_SCAN_GAP_NS:
        raise BagError(f"{row['bag']}: horizontal scan gap of {max_gap / 1e9:.3f} s")
    if mismatched_scans:
        raise BagError(f"{row['bag']}: {mismatched_scans} scans differ from the index-driven re-derivation")
    vstats = value_stats(payload)
    check_values(row["bag"], payload, vstats)
    if vstats["zero_echo_nan_count"] != zero_total:
        raise BagError(f"{row['bag']}: NaN count {vstats['zero_echo_nan_count']} != zero-echo beams {zero_total}")
    return {
        "bag": row["bag"],
        "scans": scans,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "values": vstats,
        "zero_echo": zero_total,
        "max_gap_s": max_gap / 1e9,
    }


def cmd_verify(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root)
    recipe_dir = Path(args.sources).resolve().parent
    data_root = (repo_root / args.data_dir).resolve()
    rows = load_sources(Path(args.sources))
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != len(rows):
        raise SystemExit(f"index has {len(index_rows)} rows, sources.tsv has {len(rows)} bags")
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                "element_size_bytes", "sample_size_bytes", "value_count"]
    by_path = {}
    for item in index_rows:
        missing = [key for key in required if key not in item]
        if missing:
            raise SystemExit(f"index row missing {missing}")
        if (item["dataset_id"], item["series_id"], item["numeric_kind"], item["bit_width"], item["endianness"],
                item["element_size_bytes"]) != (DATASET_ID, SERIES_ID, "float", 32, "little", 4):
            raise SystemExit(f"index row has wrong type metadata: {item}")
        if item["sample_size_bytes"] != 4 * item["value_count"]:
            raise SystemExit("index row size/value_count mismatch")
        sample = data_root / item["sample_path"]
        if not sample.is_file() or sample.stat().st_size != item["sample_size_bytes"]:
            raise SystemExit(f"sample missing or wrong size: {sample}")
        by_path[item["sample_path"]] = item
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(Path(sample_rel(row)).name for row in rows):
        raise SystemExit("sample directory contents disagree with sources.tsv")
    tasks = []
    for row in rows:
        item = by_path.get(sample_rel(row))
        if item is None:
            raise SystemExit(f"index has no row for {row['bag']}")
        tasks.append((str(data_root), row, item))
    workers = max(1, min(len(rows), args.workers, os.cpu_count() or 1))
    with multiprocessing.Pool(workers) as pool:
        results = pool.map(verify_one, tasks, chunksize=1)
    total_bytes = 0
    digests = set()
    for (data_root_s, row, item), result in zip(tasks, results):
        values = result["values"]
        if result["sha256"] != item.get("sha256"):
            raise SystemExit(f"{row['bag']}: sample hash differs from index")
        if values["value_count"] != item["value_count"] or item["value_count"] != result["scans"] * BEAMS:
            raise SystemExit(f"{row['bag']}: value count mismatch")
        if item.get("shape") != [result["scans"], BEAMS]:
            raise SystemExit(f"{row['bag']}: shape mismatch")
        if values["range_max_sentinel_count"] != item.get("range_max_sentinel_count"):
            raise SystemExit(f"{row['bag']}: sentinel count mismatch")
        if values["zero_echo_nan_count"] != item.get("zero_echo_nan_count"):
            raise SystemExit(f"{row['bag']}: zero-echo NaN count mismatch")
        if values["min"] != item.get("min") or values["max"] != item.get("max"):
            raise SystemExit(f"{row['bag']}: min/max mismatch")
        if result["sha256"] in digests:
            raise SystemExit(f"{row['bag']}: duplicate sample content")
        digests.add(result["sha256"])
        total_bytes += item["sample_size_bytes"]
        print(
            f"verified bag={row['bag']} scans={result['scans']} sentinel={values['range_max_sentinel_count']} "
            f"({values['sentinel_fraction']:.4f}) zero_echo_nan={values['zero_echo_nan_count']} "
            f"off_lattice={values['off_mm_lattice_count']} min={values['min']} max={values['max']} "
            f"max_scan_gap_s={result['max_gap_s']:.3f}"
        )
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    primaries = [series for series in manifest["series"] if series.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0]["id"] != SERIES_ID:
        raise SystemExit("manifest must declare exactly one primary series")
    series = primaries[0]
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        raise SystemExit(
            f"manifest scope mismatch: manifest {series['sample_count']} samples/{series['total_size_bytes']} bytes, "
            f"realized {len(rows)}/{total_bytes}"
        )
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1,000,000,000 bytes")
    counts = sorted(item["value_count"] for item in index_rows)
    median = counts[len(counts) // 2] if len(counts) % 2 else (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2
    if median < 1000 or (sum(counts) < 10_000 and total_bytes < 100_000):
        raise SystemExit("primary floors not met")
    print(f"verify_totals samples={len(rows)} bytes={total_bytes} values={sum(counts)} median_values={median}")


# --------------------------------------------------------------------------
# discovery / download helpers
# --------------------------------------------------------------------------

def cmd_index_summary(args: argparse.Namespace) -> None:
    head = Path(args.head).read_bytes()
    header = parse_bag_header(head)
    tail = Path(args.tail).read_bytes()
    if header["index_pos"] + len(tail) != args.size:
        raise SystemExit(f"tail length {len(tail)} does not reach the end of a {args.size}-byte bag")
    index = parse_index_section(tail, header["conn_count"], header["chunk_count"])
    summary = summarize_index(header, index)
    print(json.dumps(summary, sort_keys=True))


def cmd_validate_bag(args: argparse.Namespace) -> None:
    rows = {row["bag"]: row for row in load_sources(Path(args.sources))}
    row = rows[args.bag]
    path = Path(args.path)
    size = path.stat().st_size
    if size != row["size_bytes"]:
        raise SystemExit(f"{args.bag}: size {size} != pinned {row['size_bytes']}")
    with path.open("rb") as handle:
        header = parse_bag_header(handle.read(HEAD_BYTES))
        handle.seek(header["index_pos"])
        tail = handle.read(size - header["index_pos"])
    index = parse_index_section(tail, header["conn_count"], header["chunk_count"])
    summary = summarize_index(header, index)
    for key in ("index_pos", "chunk_count", "scan_count"):
        if summary[key] != row[key]:
            raise SystemExit(f"{args.bag}: {key} {summary[key]} != pinned {row[key]}")
    print(
        f"bag_validation=ok bag={args.bag} index_pos={summary['index_pos']} chunks={summary['chunk_count']} "
        f"scans={summary['scan_count']} topics={summary['messages_per_topic']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("index-summary")
    p.add_argument("--head", required=True)
    p.add_argument("--tail", required=True)
    p.add_argument("--size", type=int, required=True)
    p.set_defaults(func=cmd_index_summary)
    p = sub.add_parser("validate-bag")
    p.add_argument("--sources", required=True)
    p.add_argument("--bag", required=True)
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_validate_bag)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", required=True)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--sources", required=True)
        p.add_argument("--workers", type=int, default=16)
        p.set_defaults(func=func)
    args = parser.parse_args()
    try:
        args.func(args)
    except BagError as exc:
        raise SystemExit(f"FATAL: {exc}")


if __name__ == "__main__":
    main()
