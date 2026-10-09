#!/usr/bin/env python3
"""Shared helpers for the Livox MID-360 rosbag2 reflectivity recipe (pure stdlib).

Upstream: Zenodo record 14841855 (K. Koide, AIST), one zip holding
  rosbag2_2024_04_16-14_17_01/metadata.yaml
  rosbag2_2024_04_16-14_17_01/rosbag2_2024_04_16-14_17_01_0.db3   (rosbag2 SQLite storage)

The db3 is extracted to disk with zipfile (CRC-checked) and queried with the
stdlib sqlite3 module: messages JOIN topics WHERE name='/livox/lidar' ORDER BY
timestamp. Each message is a CDR (little-endian, encapsulation 00 01 00 00)
sensor_msgs/msg/PointCloud2. The fields array is parsed, not assumed; the
recipe requires point_step 26 and an 'intensity' FLOAT32 field at offset 12
(livox_ros_driver2 xfer_format 0 layout: x,y,z,intensity f32, tag u8, line u8,
timestamp f64).

Commands
  self-test                       synthetic CDR + sqlite + zip round trip
  check-zip --zip Z --api-json J  semantic validation of the downloaded zip
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import tempfile
import zipfile
from array import array
from pathlib import Path

DATASET_ID = "zenodo_livox_mid360_driving_reflectivity_u8"
SERIES_ID = "mid360_frame_reflectivity_u8"
ZIP_NAME = "rosbag2_2024_04_16-14_17_01.zip"
ZIP_SIZE = 517_088_133
ZIP_MD5 = "0836c50859bb1af591966b69da166186"
BAG_DIR = "rosbag2_2024_04_16-14_17_01"
META_MEMBER = f"{BAG_DIR}/metadata.yaml"
DB_MEMBER = f"{BAG_DIR}/{BAG_DIR}_0.db3"
DB_SIZE = 1_468_932_096
LIDAR_TOPIC = "/livox/lidar"
LIDAR_TYPE = "sensor_msgs/msg/PointCloud2"
LIDAR_MESSAGES = 2772
POINT_STEP = 26
INTENSITY_OFFSET = 12
FLOAT32 = 7
FRAME_ID = "livox_frame"
LIDAR_QUERY = (
    "SELECT m.id, m.timestamp, m.data FROM messages m JOIN topics t ON m.topic_id = t.id "
    "WHERE t.name = ? ORDER BY m.timestamp, m.id"
)

# The 256 float32 bit patterns of the integers 0..255 (+0.0 only), mapped to the byte value.
VALID_PATTERNS = {struct.unpack("<I", struct.pack("<f", float(v)))[0]: v for v in range(256)}


class CdrError(ValueError):
    pass


def parse_pointcloud2(msg: bytes) -> dict:
    """Parse a CDR-LE sensor_msgs/msg/PointCloud2; alignment is relative to the byte after the 4-byte encapsulation header."""
    if len(msg) < 8 or msg[:4] != b"\x00\x01\x00\x00":
        raise CdrError(f"not CDR little-endian encapsulation: {msg[:4].hex()}")
    body = memoryview(msg)[4:]
    n_body = len(body)
    pos = 0

    def align(n: int) -> None:
        nonlocal pos
        pos = (pos + n - 1) // n * n

    def need(n: int) -> None:
        if pos + n > n_body:
            raise CdrError(f"truncated message at body offset {pos} (+{n})")

    def u32() -> int:
        nonlocal pos
        align(4)
        need(4)
        (v,) = struct.unpack_from("<I", body, pos)
        pos += 4
        return v

    def i32() -> int:
        nonlocal pos
        align(4)
        need(4)
        (v,) = struct.unpack_from("<i", body, pos)
        pos += 4
        return v

    def u8() -> int:
        nonlocal pos
        need(1)
        v = body[pos]
        pos += 1
        return v

    def string() -> str:
        nonlocal pos
        n = u32()
        if n == 0:
            raise CdrError("CDR string with zero length (missing NUL)")
        need(n)
        raw = bytes(body[pos:pos + n])
        pos += n
        if raw[-1:] != b"\0":
            raise CdrError("CDR string not NUL terminated")
        return raw[:-1].decode("utf-8")

    stamp_sec = i32()
    stamp_nsec = u32()
    frame_id = string()
    height = u32()
    width = u32()
    n_fields = u32()
    if n_fields > 64:
        raise CdrError(f"implausible field count {n_fields}")
    fields = []
    for _ in range(n_fields):
        name = string()
        offset = u32()
        datatype = u8()
        count = u32()
        fields.append({"name": name, "offset": offset, "datatype": datatype, "count": count})
    is_bigendian = u8()
    point_step = u32()
    row_step = u32()
    n_data = u32()
    need(n_data)
    data = bytes(body[pos:pos + n_data])
    pos += n_data
    is_dense = u8()
    if pos != n_body:
        raise CdrError(f"{n_body - pos} trailing bytes after PointCloud2")
    return {
        "stamp_sec": stamp_sec,
        "stamp_nsec": stamp_nsec,
        "frame_id": frame_id,
        "height": height,
        "width": width,
        "fields": fields,
        "is_bigendian": is_bigendian,
        "point_step": point_step,
        "row_step": row_step,
        "data": data,
        "is_dense": is_dense,
    }


def frame_reflectivity(msg: bytes) -> dict:
    """Validate one PointCloud2 frame and return its reflectivity bytes (one per point, native order).

    Any structural deviation, or any intensity that is not exactly one of the
    float32 patterns of the integers 0..255, raises CdrError (fatal: frames
    are never dropped or clamped)."""
    pc = parse_pointcloud2(msg)
    if pc["is_bigendian"]:
        raise CdrError("big-endian point data")
    if pc["frame_id"] != FRAME_ID:
        raise CdrError(f"unexpected frame_id {pc['frame_id']!r}")
    if pc["point_step"] != POINT_STEP:
        raise CdrError(f"point_step {pc['point_step']} != {POINT_STEP}")
    by_name = {f["name"]: f for f in pc["fields"]}
    inten = by_name.get("intensity")
    if inten is None or inten["offset"] != INTENSITY_OFFSET or inten["datatype"] != FLOAT32 or inten["count"] != 1:
        raise CdrError(f"intensity field is not FLOAT32 at offset {INTENSITY_OFFSET}: {inten}")
    if pc["height"] != 1:
        raise CdrError(f"height {pc['height']} != 1")
    n = pc["width"] * pc["height"]
    data = pc["data"]
    if n <= 0 or len(data) != n * POINT_STEP or pc["row_step"] != pc["width"] * POINT_STEP:
        raise CdrError(f"size mismatch width={pc['width']} row_step={pc['row_step']} data={len(data)}")
    gathered = bytearray(4 * n)
    for k in range(4):
        gathered[k::4] = data[INTENSITY_OFFSET + k::POINT_STEP]
    words = array("I")
    words.frombytes(bytes(gathered))
    if sys.byteorder != "little":
        words.byteswap()
    distinct_words = set(words)
    bad = [w for w in distinct_words if w not in VALID_PATTERNS]
    if bad:
        vals = [struct.unpack("<f", struct.pack("<I", w))[0] for w in bad[:5]]
        raise CdrError(f"intensity not an exact integer in 0..255 (e.g. {vals})")
    table = VALID_PATTERNS
    out = bytes(table[w] for w in words)
    # No-return slots: the driver emits x=y=z=0 for them.
    zero_xyz = 0
    zero12 = b"\0" * 12
    for i in range(0, len(data), POINT_STEP):
        if data[i:i + 12] == zero12:
            zero_xyz += 1
    return {
        "reflectivity": out,
        "points": n,
        "width": pc["width"],
        "stamp_ns": pc["stamp_sec"] * 1_000_000_000 + pc["stamp_nsec"],
        "no_return_points": zero_xyz,
        "field_names": [f["name"] for f in pc["fields"]],
    }


def parse_metadata_counts(text: str) -> dict:
    """Minimal rosbag2 metadata.yaml reader: storage id and per-topic message counts."""
    storage = re.search(r"^\s*storage_identifier:\s*(\S+)\s*$", text, re.M)
    counts = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^\s*name:\s*(\S+)\s*$", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"^\s*type:\s*(\S+)\s*$", line)
        if m and current is not None:
            counts.setdefault(current, {})["type"] = m.group(1)
            continue
        m = re.match(r"^      message_count:\s*(\d+)\s*$", line)
        if m and current is not None:
            counts.setdefault(current, {})["count"] = int(m.group(1))
            current = None
    comp = re.search(r"^\s*compression_format:\s*\"?([^\"\n]*)\"?\s*$", text, re.M)
    return {
        "storage": storage.group(1) if storage else None,
        "compression_format": comp.group(1).strip() if comp else None,
        "topics": counts,
    }


def check_metadata(text: str) -> None:
    meta = parse_metadata_counts(text)
    if meta["storage"] != "sqlite3":
        raise ValueError(f"storage_identifier {meta['storage']!r} != sqlite3")
    if meta["compression_format"]:
        raise ValueError(f"bag compression {meta['compression_format']!r} not supported")
    lidar = meta["topics"].get(LIDAR_TOPIC, {})
    if lidar.get("type") != LIDAR_TYPE or lidar.get("count") != LIDAR_MESSAGES:
        raise ValueError(f"metadata.yaml {LIDAR_TOPIC}: {lidar} (expected {LIDAR_TYPE} x {LIDAR_MESSAGES})")


def check_zip(zip_path: Path, api_json: Path | None, full_crc: bool = True) -> str:
    size = zip_path.stat().st_size
    if size != ZIP_SIZE:
        raise ValueError(f"zip size {size} != {ZIP_SIZE}")
    if api_json is not None:
        rec = json.loads(api_json.read_text(encoding="utf-8"))
        lic = (rec.get("metadata", {}).get("license") or {}).get("id")
        if lic != "cc-by-4.0":
            raise ValueError(f"Zenodo license is {lic!r}, expected cc-by-4.0")
        files = {f["key"]: f for f in rec.get("files", [])}
        f = files.get(ZIP_NAME)
        if not f or f.get("size") != ZIP_SIZE or f.get("checksum") != f"md5:{ZIP_MD5}":
            raise ValueError(f"Zenodo file entry changed: {f}")
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        if names != sorted([META_MEMBER, DB_MEMBER]):
            raise ValueError(f"unexpected zip members {names}")
        info = zf.getinfo(DB_MEMBER)
        if info.file_size != DB_SIZE:
            raise ValueError(f"db3 uncompressed size {info.file_size} != {DB_SIZE}")
        meta_text = zf.read(META_MEMBER).decode("utf-8")
        check_metadata(meta_text)
        if full_crc:
            # Streaming read verifies the CRC-32 of the 1.47 GB member without writing it.
            with zf.open(DB_MEMBER) as fh:
                head = fh.read(16)
                if head != b"SQLite format 3\x00":
                    raise ValueError("db3 member is not an SQLite database")
                while fh.read(1 << 22):
                    pass
    return meta_text


def extract_db(zip_path: Path, dest_dir: Path) -> Path:
    """Extract the db3 member (CRC-checked by zipfile) to dest_dir; returns its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / Path(DB_MEMBER).name
    tmp = target.with_suffix(".db3.part")
    with zipfile.ZipFile(zip_path) as zf, zf.open(DB_MEMBER) as src, tmp.open("wb") as dst:
        while True:
            chunk = src.read(1 << 22)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(tmp, target)
    if target.stat().st_size != DB_SIZE:
        raise ValueError(f"extracted db3 size {target.stat().st_size} != {DB_SIZE}")
    return target


def open_db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def iter_lidar_messages(con: sqlite3.Connection):
    yield from con.execute(LIDAR_QUERY, (LIDAR_TOPIC,))


# ---------------------------------------------------------------- self-test


def _cdr_string(buf: bytearray, s: str) -> None:
    while len(buf) % 4:
        buf.append(0)
    raw = s.encode() + b"\0"
    buf += struct.pack("<I", len(raw)) + raw


def _cdr_u32(buf: bytearray, v: int) -> None:
    while len(buf) % 4:
        buf.append(0)
    buf += struct.pack("<I", v)


def encode_pointcloud2(points, frame_id=FRAME_ID, fields=None, point_step=POINT_STEP, sec=1, nsec=2) -> bytes:
    """Independent CDR encoder for the self-test (points: (x,y,z,intensity,tag,line,t))."""
    if fields is None:
        fields = [("x", 0, 7), ("y", 4, 7), ("z", 8, 7), ("intensity", 12, 7), ("tag", 16, 2), ("line", 17, 2), ("timestamp", 18, 8)]
    body = bytearray()
    _cdr_u32(body, sec)
    _cdr_u32(body, nsec)
    _cdr_string(body, frame_id)
    _cdr_u32(body, 1)
    _cdr_u32(body, len(points))
    _cdr_u32(body, len(fields))
    for name, off, dt in fields:
        _cdr_string(body, name)
        _cdr_u32(body, off)
        body.append(dt)
        _cdr_u32(body, 1)
    body.append(0)
    _cdr_u32(body, point_step)
    _cdr_u32(body, point_step * len(points))
    data = b"".join(struct.pack("<3ffBBd", *p) for p in points)
    _cdr_u32(body, len(data))
    body += data
    body.append(1)
    return b"\x00\x01\x00\x00" + bytes(body)


def self_test() -> None:
    import random

    rng = random.Random(7)
    assert struct.calcsize("<3ffBBd") == POINT_STEP
    frames = []
    for k in range(3):
        n = 96 * (5 + k)
        pts = []
        for i in range(n):
            if i % 7 == 0:
                pts.append((0.0, 0.0, 0.0, 0.0, 0, i % 4, 0.0))
            else:
                pts.append((rng.uniform(-50, 50), rng.uniform(-50, 50), rng.uniform(-5, 5), float(rng.randrange(256)), rng.randrange(256), i % 4, 1e9 + i))
        frames.append(pts)
    # Parser round trip, including the field array and alignment.
    msg = encode_pointcloud2(frames[0])
    pc = parse_pointcloud2(msg)
    assert pc["width"] == len(frames[0]) and pc["point_step"] == 26 and pc["frame_id"] == FRAME_ID
    assert [f["name"] for f in pc["fields"]] == ["x", "y", "z", "intensity", "tag", "line", "timestamp"]
    res = frame_reflectivity(msg)
    assert res["reflectivity"] == bytes(int(p[3]) for p in frames[0])
    assert res["no_return_points"] == sum(1 for i in range(len(frames[0])) if i % 7 == 0)
    # A frame_id whose length forces padding before height must still parse.
    odd = parse_pointcloud2(encode_pointcloud2(frames[1][:5], frame_id="ab"))
    assert odd["width"] == 5 and odd["frame_id"] == "ab"
    # Rejections: non-integral, out of range, negative zero, wrong offset, wrong step, truncation.
    for bad_val in (1.5, 256.0, -1.0, -0.0, float("nan")):
        bad = list(frames[0])
        bad[3] = (1.0, 2.0, 3.0, bad_val, 0, 0, 0.0)
        try:
            frame_reflectivity(encode_pointcloud2(bad))
        except CdrError:
            pass
        else:
            raise AssertionError(f"accepted intensity {bad_val}")
    moved = [("x", 0, 7), ("y", 4, 7), ("z", 8, 7), ("intensity", 16, 7), ("tag", 12, 2), ("line", 13, 2), ("timestamp", 18, 8)]
    for kwargs in ({"fields": moved}, {"point_step": 32}):
        try:
            frame_reflectivity(encode_pointcloud2(frames[0], **kwargs))
        except CdrError:
            pass
        else:
            raise AssertionError(f"accepted {kwargs}")
    try:
        parse_pointcloud2(msg[:-10])
    except CdrError:
        pass
    else:
        raise AssertionError("accepted truncated message")
    # SQLite + zip round trip with the rosbag2 schema.
    meta = (
        "rosbag2_bagfile_information:\n  version: 5\n  storage_identifier: sqlite3\n"
        "  topics_with_message_count:\n    - topic_metadata:\n        name: /livox/imu\n"
        "        type: sensor_msgs/msg/Imu\n        serialization_format: cdr\n      message_count: 9\n"
        "    - topic_metadata:\n        name: /livox/lidar\n        type: sensor_msgs/msg/PointCloud2\n"
        "        serialization_format: cdr\n      message_count: 3\n  compression_format: \"\"\n"
    )
    m = parse_metadata_counts(meta)
    assert m["storage"] == "sqlite3" and m["topics"]["/livox/lidar"] == {"type": LIDAR_TYPE, "count": 3}
    assert m["compression_format"] == ""
    with tempfile.TemporaryDirectory(prefix="livox_selftest_") as td:
        db = Path(td) / "t.db3"
        con = sqlite3.connect(db)
        con.executescript(
            "CREATE TABLE topics(id INTEGER PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL,"
            "serialization_format TEXT NOT NULL,offered_qos_profiles TEXT NOT NULL);"
            "CREATE TABLE messages(id INTEGER PRIMARY KEY,topic_id INTEGER NOT NULL,timestamp INTEGER NOT NULL, data BLOB NOT NULL);"
        )
        con.execute("INSERT INTO topics VALUES (4,'/livox/lidar',?,'cdr','')", (LIDAR_TYPE,))
        con.execute("INSERT INTO topics VALUES (5,'/livox/imu','sensor_msgs/msg/Imu','cdr','')")
        # Insert out of timestamp order, interleaved with IMU rows.
        order = [2, 0, 1]
        rid = 1
        for k in order:
            con.execute("INSERT INTO messages VALUES (?,5,?,?)", (rid, 100 + k, b"imu"))
            rid += 1
            con.execute("INSERT INTO messages VALUES (?,4,?,?)", (rid, 1000 + k, encode_pointcloud2(frames[k], sec=k)))
            rid += 1
        con.commit()
        con.close()
        zpath = Path(td) / "t.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db, "bag/bag_0.db3")
        with zipfile.ZipFile(zpath) as zf, zf.open("bag/bag_0.db3") as src, (Path(td) / "x.db3").open("wb") as dst:
            dst.write(src.read())
        con = open_db(Path(td) / "x.db3")
        got = [(ts, frame_reflectivity(data)["reflectivity"]) for _id, ts, data in iter_lidar_messages(con)]
        con.close()
        assert [ts for ts, _ in got] == [1000, 1001, 1002]
        for k, (_ts, refl) in enumerate(got):
            assert refl == bytes(int(p[3]) for p in frames[k])
    print("self-test ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    c = sub.add_parser("check-zip")
    c.add_argument("--zip", type=Path, required=True)
    c.add_argument("--api-json", type=Path)
    c.add_argument("--metadata-out", type=Path)
    c.add_argument("--quick", action="store_true", help="skip the full CRC pass over the db3 member")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test()
        return 0
    try:
        meta = check_zip(args.zip, args.api_json, full_crc=not args.quick)
    except (ValueError, zipfile.BadZipFile) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    if args.metadata_out:
        args.metadata_out.write_text(meta, encoding="utf-8")
    print(f"zip ok: {ZIP_NAME} members=2 db3={DB_SIZE} bytes {LIDAR_TOPIC}={LIDAR_MESSAGES} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
