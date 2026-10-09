#!/usr/bin/env python3
"""Independently re-derive and check every Livox MID-360 reflectivity sample.

Does not import the build helpers: it re-checks the zip MD5, re-extracts the
db3 member to extracted/<id>/verify/ (deleted afterwards), resolves the
/livox/lidar topic id, walks its messages by timestamp, parses each CDR
PointCloud2 with its own offset arithmetic, decodes every point with
struct.iter_unpack('<3ffBBd'), re-applies the policy (intensity finite,
integral, 0..255, not -0.0; any violation fatal) and compares the result
byte-for-byte with the built sample. Also checks the index, inventory,
degeneracy (constant samples, most common value > 80%) and manifest totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import struct
import sys
import tomllib
import zipfile
from pathlib import Path

DATASET_ID = "zenodo_livox_mid360_driving_reflectivity_u8"
SERIES_ID = "mid360_frame_reflectivity_u8"
ZIP_NAME = "rosbag2_2024_04_16-14_17_01.zip"
ZIP_SIZE = 517_088_133
ZIP_MD5 = "0836c50859bb1af591966b69da166186"
DB_MEMBER = "rosbag2_2024_04_16-14_17_01/rosbag2_2024_04_16-14_17_01_0.db3"
EXPECTED_FRAMES = 2772
EXPECTED_FIELDS = [("x", 0, 7), ("y", 4, 7), ("z", 8, 7), ("intensity", 12, 7), ("tag", 16, 2), ("line", 17, 2), ("timestamp", 18, 8)]
MAX_MODE_FRACTION = 0.80
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL {msg}")


def pad4(off: int) -> int:
    return off + (-off % 4)


def decode_frame(blob: bytes) -> tuple[bytes, int]:
    """Return (reflectivity bytes, header stamp ns) for one CDR PointCloud2 message."""
    if blob[:4] != b"\x00\x01\x00\x00":
        fail("message is not CDR-LE")
    b = blob[4:]
    sec, nsec, slen = struct.unpack_from("<iII", b, 0)
    off = 12
    frame_id = b[off:off + slen]
    off = pad4(off + slen)
    if frame_id != b"livox_frame\0":
        fail(f"frame_id {frame_id!r}")
    height, width, nfields = struct.unpack_from("<III", b, off)
    off += 12
    fields = []
    for _ in range(nfields):
        (nlen,) = struct.unpack_from("<I", b, off)
        name = b[off + 4:off + 4 + nlen].rstrip(b"\0").decode()
        off = pad4(off + 4 + nlen)
        (foff,) = struct.unpack_from("<I", b, off)
        dtype = b[off + 4]
        off = pad4(off + 5)
        (count,) = struct.unpack_from("<I", b, off)
        off += 4
        if count != 1:
            fail(f"field {name} count {count}")
        fields.append((name, foff, dtype))
    if fields != EXPECTED_FIELDS:
        fail(f"fields {fields}")
    is_be = b[off]
    off = pad4(off + 1)
    point_step, row_step, dlen = struct.unpack_from("<III", b, off)
    off += 12
    if is_be or height != 1 or point_step != 26 or row_step != 26 * width or dlen != 26 * width:
        fail(f"layout be={is_be} h={height} w={width} step={point_step} row={row_step} len={dlen}")
    if off + dlen + 1 != len(b):
        fail(f"message length {len(b)} != {off + dlen + 1}")
    data = b[off:off + dlen]
    out = bytearray(width)
    i = 0
    for _x, _y, _z, inten, _tag, _line, _t in struct.iter_unpack("<3ffBBd", data):
        if not (0.0 <= inten <= 255.0) or inten != int(inten) or math.copysign(1.0, inten) < 0:
            fail(f"intensity {inten!r} not an exact integer in 0..255")
        out[i] = int(inten)
        i += 1
    return bytes(out), sec * 1_000_000_000 + nsec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    root = args.data_root.resolve()
    zip_path = root / "downloads" / DATASET_ID / ZIP_NAME
    series_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    work = root / "extracted" / DATASET_ID / "verify"

    # Source integrity.
    if not zip_path.is_file() or zip_path.stat().st_size != ZIP_SIZE:
        fail(f"missing or wrong-size {zip_path}")
    h = hashlib.md5()
    with zip_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    if h.hexdigest() != ZIP_MD5:
        fail(f"zip md5 {h.hexdigest()}")
    print(f"zip md5 ok {ZIP_MD5}")

    # Index.
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != EXPECTED_FRAMES:
        fail(f"index has {len(rows)} rows, expected {EXPECTED_FRAMES}")
    for r in rows:
        missing = [k for k in INDEX_KEYS if k not in r]
        if missing:
            fail(f"index row missing {missing}")
        if (r["dataset_id"], r["series_id"], r["numeric_kind"], r["bit_width"], r["endianness"], r["element_size_bytes"]) != (
                DATASET_ID, SERIES_ID, "uint", 8, "little", 1):
            fail(f"index row metadata {r}")
        if r["sample_size_bytes"] != r["value_count"]:
            fail(f"size/value mismatch {r['sample_path']}")
    on_disk = sorted(p.name for p in series_dir.iterdir())
    indexed = sorted(Path(r["sample_path"]).name for r in rows)
    if on_disk != indexed:
        fail(f"sample directory and index disagree ({len(on_disk)} files vs {len(indexed)} rows)")

    # Re-extract the db3 and re-derive every frame.
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    db = work / "verify.db3"
    total_hist = [0] * 256
    try:
        with zipfile.ZipFile(zip_path) as zf, zf.open(DB_MEMBER) as src, db.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 22)
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        topic = con.execute("SELECT id, type FROM topics WHERE name = '/livox/lidar'").fetchall()
        if len(topic) != 1 or topic[0][1] != "sensor_msgs/msg/PointCloud2":
            fail(f"topic lookup {topic}")
        (n_msgs,) = con.execute("SELECT COUNT(*) FROM messages WHERE topic_id = ?", (topic[0][0],)).fetchone()
        if n_msgs != EXPECTED_FRAMES:
            fail(f"db has {n_msgs} lidar messages")
        cur = con.execute("SELECT id, timestamp, data FROM messages WHERE topic_id = ? ORDER BY timestamp ASC, id ASC", (topic[0][0],))
        prev = -1
        for k, (row, (msg_id, ts, blob)) in enumerate(zip(rows, cur)):
            if ts <= prev:
                fail(f"timestamps not increasing at {msg_id}")
            prev = ts
            expect, stamp = decode_frame(bytes(blob))
            name = Path(row["sample_path"]).name
            if name != f"{k:04d}_{ts}.u8" or row.get("message_id") != msg_id or row.get("header_stamp_ns") != stamp:
                fail(f"frame {k}: index row {name} / {row.get('message_id')} does not match message {msg_id} ts {ts}")
            got = (root / row["sample_path"]).read_bytes()
            if got != expect:
                fail(f"frame {k} ({name}): sample bytes differ from re-derived reflectivity")
            if len(got) != row["value_count"] or hashlib.sha256(got).hexdigest() != row.get("sha256"):
                fail(f"frame {k}: size or sha256 mismatch")
            hist = [0] * 256
            for v in got:
                hist[v] += 1
            present = [v for v in range(256) if hist[v]]
            if len(present) < 2:
                fail(f"frame {k}: constant sample")
            mode = max(hist)
            if mode / len(got) > MAX_MODE_FRACTION:
                fail(f"frame {k}: most common value covers {mode / len(got):.3f}")
            if row.get("min") != present[0] or row.get("max") != present[-1]:
                fail(f"frame {k}: index min/max {row.get('min')}/{row.get('max')} != {present[0]}/{present[-1]}")
            for v in present:
                total_hist[v] += hist[v]
            if k % 500 == 0:
                print(f"verified frame {k} {name} points={len(got)}")
        con.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    counts = sorted(r["value_count"] for r in rows)
    total = sum(counts)
    m = len(counts)
    median = counts[m // 2] if m % 2 else (counts[m // 2 - 1] + counts[m // 2]) / 2
    if sum(total_hist) != total:
        fail("not every indexed frame was re-derived")
    if total < 10_000 or median < 1_000:
        fail(f"below floor total={total} median={median}")
    if total > 1_000_000_000:
        fail(f"primary bytes {total} exceed 1 GB")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest series entry missing")
    if series[0]["sample_count"] != m or series[0]["total_size_bytes"] != total:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} != realized {m}/{total}")
    print(f"verify ok samples={m} total_bytes={total} median={median} min={counts[0]} max={counts[-1]} "
          f"zero_fraction={total_hist[0] / total:.6f} distinct={sum(1 for c in total_hist if c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
