#!/usr/bin/env python3
"""comma2k19 global_pose/frame_positions extraction helpers (stdlib only).

Network I/O lives in download.sh (curl). This module only parses what curl
fetched:

  check-readme   validate the pinned dataset card (license + identity)
  check-head     validate a resolve-URL HEAD dump (commit, size, LFS sha256)
  check-tail     validate the ZIP64 end-of-central-directory tail of one chunk
  plan           parse one chunk's central directory into exact member ranges
  pending        list planned members not yet present at the exact length
  validate       validate every fetched member (local header, inflate, CRC32,
                 NPY header, ECEF plausibility); delete transport-corrupt ones
  build          emit one little-endian float64 sample per segment + index
  verify         independently re-derive everything from the downloads
  selftest       exercise the ZIP64/NPY parsers on synthetic inputs
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import math
import re
import statistics
import struct
import sys
import tomllib
import zipfile
import zlib
from pathlib import Path

DATASET_ID = "comma2k19_global_pose_ecef_positions_f64"
SERIES_ID = "comma2k19_frame_positions_ecef_f64"
REVISION = "4bff77c7254c654c28d4c2726186b4e825adccee"
BASE_URL = f"https://huggingface.co/datasets/commaai/comma2k19/resolve/{REVISION}/raw_data"
MEMBER_SUFFIX = "/global_pose/frame_positions"
NATURAL_RECORD_KIND = "comma2k19_one_minute_segment_global_pose_frame_positions"
README_SHA256 = "3835b02a571a0774917f3204941b83d090c41b727347fd37d63e4ae74d6a9bb4"
TAIL_BYTES = 4096
EXPECTED_SEGMENTS = 2035
EXPECTED_VALUES = 7_291_422
EXPECTED_BYTES = 58_331_376
R_MIN_M = 6.3e6
R_MAX_M = 6.4e6
# 4 m per 50 ms frame = 80 m/s (288 km/h). Larger inter-frame jumps are
# physically implausible for a car on I-280 and would indicate a pose gap.
STEP_FLAG_M = 4.0
ROUTE_RE = re.compile(r"^([0-9a-f]{16})\|(\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})$")
SEGMENT_RE = re.compile(r"^\d{1,3}$")
PLAN_FIELDS = [
    "chunk", "route", "segment", "member", "range_start", "range_end",
    "method", "flags", "crc32", "compressed_bytes", "uncompressed_bytes", "relpath",
]

SIG_LOCAL = 0x04034B50
SIG_CENTRAL = 0x02014B50
SIG_EOCD = 0x06054B50
SIG_EOCD64 = 0x06064B50
SIG_LOCATOR64 = 0x07064B50


class TransportError(Exception):
    """Fetched bytes are not the expected member bytes (refetch may help)."""


class SemanticError(Exception):
    """Bytes are the exact published member but violate the content contract."""


# --------------------------------------------------------------------------
# chunk pins
# --------------------------------------------------------------------------

def load_chunks(path: Path) -> dict[int, dict]:
    lines = path.read_text(encoding="ascii").splitlines()
    header = lines[0].split("\t")
    chunks: dict[int, dict] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        k = int(row["chunk"])
        chunks[k] = {key: (value if key.endswith("sha256") else int(value)) for key, value in row.items()}
    if sorted(chunks) != list(range(1, 11)):
        raise SystemExit(f"chunks table must list chunks 1..10, got {sorted(chunks)}")
    return chunks


# --------------------------------------------------------------------------
# ZIP parsing
# --------------------------------------------------------------------------

def parse_zip64_extra(extra: bytes, usize: int, csize: int, offset: int) -> tuple[int, int, int]:
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4 : pos + 4 + size]
        if len(body) != size:
            raise ValueError("truncated extra field")
        if header_id == 0x0001:
            cursor = 0
            if usize == 0xFFFFFFFF:
                (usize,) = struct.unpack_from("<Q", body, cursor)
                cursor += 8
            if csize == 0xFFFFFFFF:
                (csize,) = struct.unpack_from("<Q", body, cursor)
                cursor += 8
            if offset == 0xFFFFFFFF:
                (offset,) = struct.unpack_from("<Q", body, cursor)
                cursor += 8
        pos += 4 + size
    if 0xFFFFFFFF in (usize, csize, offset):
        raise ValueError("ZIP64 sentinel without matching zip64 extra field")
    return usize, csize, offset


def parse_central_directory(buf: bytes) -> list[dict]:
    entries = []
    pos = 0
    while pos < len(buf):
        if len(buf) - pos < 46:
            raise ValueError(f"truncated central directory header at {pos}")
        (sig, _made, _need, flags, method, _mtime, _mdate, crc, csize, usize,
         nlen, elen, clen, disk, _iattr, _eattr, offset) = struct.unpack_from("<IHHHHHHIIIHHHHHII", buf, pos)
        if sig != SIG_CENTRAL:
            raise ValueError(f"bad central directory signature at {pos}: {sig:#x}")
        if disk not in (0, 0xFFFF):
            raise ValueError("multi-disk archives are not supported")
        raw_name = buf[pos + 46 : pos + 46 + nlen]
        extra = buf[pos + 46 + nlen : pos + 46 + nlen + elen]
        if len(raw_name) != nlen or len(extra) != elen:
            raise ValueError(f"truncated central directory entry at {pos}")
        usize, csize, offset = parse_zip64_extra(extra, usize, csize, offset)
        name = raw_name.decode("utf-8" if flags & 0x800 else "cp437")
        entries.append({
            "name": name, "flags": flags, "method": method, "crc32": crc,
            "compressed_bytes": csize, "uncompressed_bytes": usize, "offset": offset,
        })
        pos += 46 + nlen + elen + clen
    if pos != len(buf):
        raise ValueError("central directory overran its declared size")
    return entries


def parse_tail(tail: bytes, archive_bytes: int) -> dict:
    """Locate the EOCD, ZIP64 locator and ZIP64 EOCD inside the archive tail."""
    base = archive_bytes - len(tail)
    eocd = tail.rfind(struct.pack("<I", SIG_EOCD))
    if eocd < 0 or len(tail) - eocd < 22:
        raise ValueError("end-of-central-directory record not found")
    (_sig, disk, cd_disk, n_disk, n_total, cd_size32, cd_off32, comment_len) = struct.unpack_from("<IHHHHIIH", tail, eocd)
    if eocd + 22 + comment_len != len(tail):
        raise ValueError("EOCD comment does not end at the archive end")
    info = {"eocd_offset": base + eocd, "entries": n_total, "cd_bytes": cd_size32, "cd_offset": cd_off32, "zip64": False}
    locator = eocd - 20
    if locator >= 0 and struct.unpack_from("<I", tail, locator)[0] == SIG_LOCATOR64:
        _sig, _disk, eocd64_abs, total_disks = struct.unpack_from("<IIQI", tail, locator)
        rel = eocd64_abs - base
        if rel < 0 or rel + 56 > locator:
            raise ValueError("ZIP64 EOCD record lies outside the fetched tail")
        (sig64, rec_size, _made, _need, disk64, cd_disk64, n_disk64, n_total64,
         cd_size64, cd_off64) = struct.unpack_from("<IQHHIIQQQQ", tail, rel)
        if sig64 != SIG_EOCD64 or total_disks != 1 or disk64 != 0 or cd_disk64 != 0:
            raise ValueError("invalid ZIP64 EOCD record")
        if rel + 12 + rec_size != locator:
            raise ValueError("ZIP64 EOCD record is not followed by its locator")
        info.update({"zip64": True, "eocd64_offset": eocd64_abs, "entries": n_total64,
                     "cd_bytes": cd_size64, "cd_offset": cd_off64})
        if n_disk64 != n_total64:
            raise ValueError("multi-disk ZIP64 archive")
    elif 0xFFFFFFFF in (cd_size32, cd_off32) or 0xFFFF in (n_disk, n_total):
        raise ValueError("ZIP64 sentinels without ZIP64 locator")
    if disk or cd_disk:
        raise ValueError("multi-disk archive")
    if info["cd_offset"] + info["cd_bytes"] != info.get("eocd64_offset", info["eocd_offset"]):
        raise ValueError("central directory does not end where the EOCD begins")
    return info


def decode_local_entry(blob: bytes, plan: dict) -> bytes:
    """Validate one fetched local-header+data range and return the inflated member."""
    expected_len = plan["range_end"] - plan["range_start"] + 1
    if len(blob) != expected_len:
        raise TransportError(f"length {len(blob)} != planned {expected_len}")
    if len(blob) < 30:
        raise TransportError("shorter than a local file header")
    (sig, _need, flags, method, _mtime, _mdate, crc, csize, usize, nlen, elen) = struct.unpack_from("<IHHHHHIIIHH", blob, 0)
    if sig != SIG_LOCAL:
        raise TransportError(f"bad local header signature {sig:#x}")
    name_raw = blob[30 : 30 + nlen]
    name = name_raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")
    if name != plan["member"]:
        raise TransportError(f"local header names {name!r}, planned {plan['member']!r}")
    if flags != plan["flags"] or method != plan["method"]:
        raise TransportError("local header flags/method disagree with central directory")
    if flags & 0x1:
        raise SemanticError("encrypted member")
    extra = blob[30 + nlen : 30 + nlen + elen]
    if flags & 0x8:
        # Sizes live in a trailing data descriptor; trust the central directory.
        csize, usize = plan["compressed_bytes"], plan["uncompressed_bytes"]
        crc = plan["crc32"]
    else:
        usize, csize, _ = parse_zip64_extra(extra, usize, csize, 0)
    if (crc, csize, usize) != (plan["crc32"], plan["compressed_bytes"], plan["uncompressed_bytes"]):
        raise TransportError("local header crc/sizes disagree with central directory")
    data_start = 30 + nlen + elen
    trailer = len(blob) - data_start - csize
    allowed_trailers = {0} if not flags & 0x8 else {12, 16, 20, 24}
    if trailer not in allowed_trailers:
        raise TransportError(f"range has {trailer} unexpected bytes after member data")
    data = blob[data_start : data_start + csize]
    if method == 8:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            raw = inflater.decompress(data) + inflater.flush()
        except zlib.error as exc:
            raise TransportError(f"inflate failed: {exc}") from exc
        if not inflater.eof or inflater.unused_data:
            raise TransportError("deflate stream does not end at the member boundary")
    elif method == 0:
        raw = data
    else:
        raise SemanticError(f"unsupported compression method {method}")
    if len(raw) != usize or (zlib.crc32(raw) & 0xFFFFFFFF) != crc:
        raise TransportError("inflated size/CRC32 mismatch")
    return raw


def parse_npy_positions(raw: bytes) -> tuple[int, bytes]:
    """Return (frames, little-endian row-major float64 body) for an (N,3) '<f8' NPY."""
    if raw[:6] != b"\x93NUMPY":
        raise SemanticError("member lacks the NPY magic")
    major = raw[6]
    if major == 1:
        (header_len,) = struct.unpack_from("<H", raw, 8)
        start = 10
    elif major in (2, 3):
        (header_len,) = struct.unpack_from("<I", raw, 8)
        start = 12
    else:
        raise SemanticError(f"unsupported NPY version {major}.{raw[7]}")
    header_bytes = raw[start : start + header_len]
    if len(header_bytes) != header_len:
        raise SemanticError("truncated NPY header")
    header = ast.literal_eval(header_bytes.decode("utf-8" if major == 3 else "latin1"))
    if not isinstance(header, dict):
        raise SemanticError("NPY header is not a dict")
    if header.get("descr") != "<f8" or header.get("fortran_order") is not False:
        raise SemanticError(f"unexpected NPY dtype/order: {header!r}")
    shape = header.get("shape")
    if not (isinstance(shape, tuple) and len(shape) == 2 and shape[1] == 3 and isinstance(shape[0], int) and shape[0] > 0):
        raise SemanticError(f"unexpected NPY shape {shape!r}")
    body = raw[start + header_len :]
    if len(body) != shape[0] * 24:
        raise SemanticError(f"NPY body {len(body)} bytes != {shape[0]}*24")
    return shape[0], body


def position_stats(body: bytes, frames: int) -> dict:
    values = struct.unpack(f"<{frames * 3}d", body)
    for value in values:
        if not math.isfinite(value):
            raise SemanticError("non-finite position value")
    radii = []
    steps = []
    prev = None
    for i in range(frames):
        x, y, z = values[3 * i : 3 * i + 3]
        if x == 0.0 and y == 0.0 and z == 0.0:
            raise SemanticError(f"all-zero position row {i}")
        r = math.sqrt(x * x + y * y + z * z)
        if not R_MIN_M < r < R_MAX_M:
            raise SemanticError(f"row {i} geocentric radius {r} outside ({R_MIN_M}, {R_MAX_M})")
        radii.append(r)
        if prev is not None:
            steps.append(math.sqrt((x - prev[0]) ** 2 + (y - prev[1]) ** 2 + (z - prev[2]) ** 2))
        prev = (x, y, z)
    for axis in range(3):
        column = values[axis::3]
        if min(column) == max(column):
            raise SemanticError(f"constant component {axis}")
    return {
        "min": min(values),
        "max": max(values),
        "radius_min_m": min(radii),
        "radius_max_m": max(radii),
        "max_step_m": max(steps) if steps else 0.0,
        "median_step_m": statistics.median(steps) if steps else 0.0,
        "path_length_m": math.fsum(steps),
        "flagged_step": bool(steps) and max(steps) > STEP_FLAG_M,
    }


# --------------------------------------------------------------------------
# plan files
# --------------------------------------------------------------------------

def member_relpath(chunk: int, route: str, segment: str) -> str:
    match = ROUTE_RE.match(route)
    if not match or not SEGMENT_RE.match(segment):
        raise ValueError(f"unexpected route/segment {route!r}/{segment!r}")
    return f"chunk_{chunk:02d}/{match.group(1)}_{match.group(2)}_seg{int(segment):02d}.zipentry"


def sample_name(route: str, segment: str) -> str:
    match = ROUTE_RE.match(route)
    return f"{match.group(1)}_{match.group(2)}_seg{int(segment):02d}.bin"


def build_plan(chunk: int, cd: bytes, pins: dict) -> list[dict]:
    if hashlib.sha256(cd).hexdigest() != pins["cd_sha256"] or len(cd) != pins["cd_bytes"]:
        raise SystemExit(f"chunk {chunk}: central directory bytes do not match the pin")
    entries = parse_central_directory(cd)
    if len(entries) != pins["cd_entries"]:
        raise SystemExit(f"chunk {chunk}: {len(entries)} central directory entries, pinned {pins['cd_entries']}")
    ordered = sorted(entries, key=lambda e: e["offset"])
    offsets = [e["offset"] for e in ordered]
    if len(set(offsets)) != len(offsets):
        raise SystemExit(f"chunk {chunk}: duplicate local header offsets")
    plan = []
    for i, entry in enumerate(ordered):
        if not entry["name"].endswith(MEMBER_SUFFIX):
            continue
        parts = entry["name"].split("/")
        if len(parts) != 5 or parts[0] != f"Chunk_{chunk}":
            raise SystemExit(f"chunk {chunk}: unexpected member path {entry['name']!r}")
        end = ordered[i + 1]["offset"] if i + 1 < len(ordered) else pins["cd_offset"]
        plan.append({
            "chunk": chunk, "route": parts[1], "segment": parts[2], "member": entry["name"],
            "range_start": entry["offset"], "range_end": end - 1,
            "method": entry["method"], "flags": entry["flags"], "crc32": entry["crc32"],
            "compressed_bytes": entry["compressed_bytes"], "uncompressed_bytes": entry["uncompressed_bytes"],
            "relpath": member_relpath(chunk, parts[1], parts[2]),
        })
    if len(plan) != pins["positions_members"]:
        raise SystemExit(f"chunk {chunk}: {len(plan)} frame_positions members, pinned {pins['positions_members']}")
    range_bytes = sum(p["range_end"] - p["range_start"] + 1 for p in plan)
    npy_bytes = sum(p["uncompressed_bytes"] for p in plan)
    if range_bytes != pins["positions_range_bytes"] or npy_bytes != pins["positions_npy_bytes"]:
        raise SystemExit(f"chunk {chunk}: planned bytes {range_bytes}/{npy_bytes} disagree with pins")
    for p in plan:
        if p["method"] not in (0, 8) or p["flags"] & 0x1:
            raise SystemExit(f"chunk {chunk}: unsupported member encoding {p['member']!r}")
        minimum = 30 + len(p["member"].encode()) + p["compressed_bytes"]
        if p["range_end"] - p["range_start"] + 1 < minimum:
            raise SystemExit(f"chunk {chunk}: range too short for {p['member']!r}")
    return plan


def write_plan(path: Path, plan: list[dict]) -> None:
    lines = ["\t".join(PLAN_FIELDS)]
    for p in plan:
        lines.append("\t".join(str(p[f]) for f in PLAN_FIELDS))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_plans(plan_dir: Path) -> list[dict]:
    rows = []
    files = sorted(plan_dir.glob("chunk_*.plan.tsv"))
    if len(files) != 10:
        raise SystemExit(f"expected 10 plan files in {plan_dir}, found {len(files)}")
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines[0].split("\t") != PLAN_FIELDS:
            raise SystemExit(f"unexpected plan header in {path}")
        for line in lines[1:]:
            row = dict(zip(PLAN_FIELDS, line.split("\t")))
            for key in ("chunk", "range_start", "range_end", "method", "flags", "crc32", "compressed_bytes", "uncompressed_bytes"):
                row[key] = int(row[key])
            rows.append(row)
    rows.sort(key=lambda r: (r["chunk"], r["range_start"]))
    if len(rows) != EXPECTED_SEGMENTS or len({r["relpath"] for r in rows}) != EXPECTED_SEGMENTS:
        raise SystemExit(f"plans list {len(rows)} members; expected {EXPECTED_SEGMENTS} unique")
    return rows


# --------------------------------------------------------------------------
# subcommands: download-side
# --------------------------------------------------------------------------

def cmd_check_readme(args: argparse.Namespace) -> int:
    data = Path(args.readme).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != README_SHA256:
        raise SystemExit(f"dataset card sha256 {digest} != pinned {README_SHA256}")
    text = data.decode("utf-8")
    front = text.split("---", 2)
    if len(front) < 3 or not re.search(r"^license:\s*mit\s*$", front[1], flags=re.MULTILINE):
        raise SystemExit("dataset card front matter does not declare license: mit")
    for needle in ("comma2k19", "2019 segments", "global_pose__frame_positions", "INS/GNSS/Vision optimizer"):
        if needle not in text:
            raise SystemExit(f"dataset card lacks expected text {needle!r}")
    print(f"dataset_card_ok sha256={digest} license=MIT")
    return 0


def cmd_check_head(args: argparse.Namespace) -> int:
    text = Path(args.headers).read_text(encoding="iso-8859-1")
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    hub = None
    for block in blocks:
        if re.search(r"^x-repo-commit:", block, flags=re.IGNORECASE | re.MULTILINE):
            hub = block
    if hub is None:
        raise SystemExit("resolve response carries no x-repo-commit header")
    def header(name: str) -> str:
        match = re.search(rf"^{name}:\s*(.+?)\s*$", hub, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            raise SystemExit(f"resolve response lacks {name}")
        return match.group(1).strip().strip('"')
    status = int(re.match(r"HTTP/\S+\s+(\d+)", hub).group(1))
    commit, size, etag = header("x-repo-commit"), int(header("x-linked-size")), header("x-linked-etag")
    if status not in (200, 301, 302, 303, 307, 308):
        raise SystemExit(f"unexpected resolve status {status}")
    if commit != REVISION or size != args.size or etag != args.sha256:
        raise SystemExit(f"archive identity changed: commit={commit} size={size} etag={etag}")
    print(f"head_ok chunk={args.chunk} commit={commit} bytes={size} lfs_sha256={etag}")
    return 0


def cmd_check_tail(args: argparse.Namespace) -> int:
    pins = load_chunks(Path(args.chunks))[args.chunk]
    tail = Path(args.tail).read_bytes()
    if len(tail) != TAIL_BYTES:
        raise SystemExit(f"chunk {args.chunk}: tail is {len(tail)} bytes, expected {TAIL_BYTES}")
    info = parse_tail(tail, pins["archive_bytes"])
    got = (info["zip64"], info.get("eocd64_offset"), info["cd_offset"], info["cd_bytes"], info["entries"])
    want = (True, pins["eocd64_offset"], pins["cd_offset"], pins["cd_bytes"], pins["cd_entries"])
    if got != want:
        raise SystemExit(f"chunk {args.chunk}: EOCD {got} disagrees with pins {want}")
    print(f"tail_ok chunk={args.chunk} cd_offset={info['cd_offset']} cd_bytes={info['cd_bytes']} entries={info['entries']}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    pins = load_chunks(Path(args.chunks))[args.chunk]
    plan = build_plan(args.chunk, Path(args.cd).read_bytes(), pins)
    write_plan(Path(args.out), plan)
    frames = [(p["uncompressed_bytes"] - 128) // 24 for p in plan]
    print(f"plan_ok chunk={args.chunk} members={len(plan)} range_bytes={pins['positions_range_bytes']} "
          f"approx_frames_min={min(frames)} approx_frames_max={max(frames)}")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    members_dir = Path(args.members_dir)
    count = 0
    for row in read_plans(Path(args.plan_dir)):
        if args.chunk is not None and row["chunk"] != args.chunk:
            continue
        path = members_dir / row["relpath"]
        length = row["range_end"] - row["range_start"] + 1
        if path.is_file() and path.stat().st_size == length:
            continue
        count += 1
        if not args.count:
            print(row["chunk"], row["range_start"], row["range_end"], row["relpath"])
    if args.count:
        print(count)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    members_dir = Path(args.members_dir)
    rows = read_plans(Path(args.plan_dir))
    missing = corrupt = 0
    frames_total = 0
    flagged = []
    for row in rows:
        path = members_dir / row["relpath"]
        if not path.is_file():
            missing += 1
            continue
        try:
            raw = decode_local_entry(path.read_bytes(), row)
        except TransportError as exc:
            corrupt += 1
            print(f"corrupt_member deleted path={row['relpath']} reason={exc}")
            path.unlink()
            continue
        except SemanticError as exc:
            raise SystemExit(f"FATAL semantic error in exact published member {row['member']!r}: {exc}")
        try:
            frames, body = parse_npy_positions(raw)
            stats = position_stats(body, frames)
        except SemanticError as exc:
            raise SystemExit(f"FATAL semantic error in exact published member {row['member']!r}: {exc}")
        frames_total += frames
        if stats["flagged_step"]:
            flagged.append(f"{row['route']}/{row['segment']}:{stats['max_step_m']:.3f}m")
    print(f"validate members={len(rows)} missing={missing} corrupt_deleted={corrupt} frames={frames_total} "
          f"step_flagged={len(flagged)}")
    for item in flagged:
        print(f"step_flagged {item}")
    if missing or corrupt:
        return 3
    if frames_total * 3 != EXPECTED_VALUES:
        raise SystemExit(f"FATAL decoded {frames_total * 3} values, expected {EXPECTED_VALUES}")
    if args.summary:
        Path(args.summary).write_text(json.dumps({
            "dataset_id": DATASET_ID, "revision": REVISION, "members": len(rows),
            "frames": frames_total, "values": frames_total * 3,
            "range_bytes": sum(r["range_end"] - r["range_start"] + 1 for r in rows),
            "step_flagged_segments": flagged,
        }, indent=1) + "\n", encoding="utf-8")
    return 0


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    rows = read_plans(downloads / "plan")
    samples_dir = Path(args.samples_dir) / SERIES_ID
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    for path in (samples_dir, index_path.parent, stats_path.parent):
        path.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*.bin"):
        stale.unlink()
    aggregate = hashlib.sha256()
    index_rows = []
    seen_hashes: dict[str, str] = {}
    flagged = []
    frames_list = []
    for row in rows:
        blob = (downloads / "members" / row["relpath"]).read_bytes()
        raw = decode_local_entry(blob, row)
        frames, body = parse_npy_positions(raw)
        stats = position_stats(body, frames)
        digest = hashlib.sha256(body).hexdigest()
        if digest in seen_hashes:
            raise SystemExit(f"duplicate segment payload {row['member']} == {seen_hashes[digest]}")
        seen_hashes[digest] = row["member"]
        out = samples_dir / sample_name(row["route"], row["segment"])
        if out.exists():
            raise SystemExit(f"sample name collision {out}")
        out.write_bytes(body)
        aggregate.update(body)
        frames_list.append(frames)
        if stats["flagged_step"]:
            flagged.append({"member": row["member"], "max_step_m": stats["max_step_m"]})
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(body),
            "value_count": frames * 3,
            "role": "primary",
            "natural_record_kind": NATURAL_RECORD_KIND,
            "sample_rank": 2,
            "sample_shape": [frames, 3],
            "sample_axes": ["frame_20hz", "ecef_xyz_m"],
            "source_url": f"{BASE_URL}/Chunk_{row['chunk']}.zip",
            "source_member": row["member"],
            "source_member_crc32": f"{row['crc32']:08x}",
            "chunk": row["chunk"],
            "dongle_id": row["route"].split("|")[0],
            "route": row["route"],
            "segment": int(row["segment"]),
            "frame_count": frames,
            "min": stats["min"],
            "max": stats["max"],
            "radius_min_m": stats["radius_min_m"],
            "radius_max_m": stats["radius_max_m"],
            "median_step_m": stats["median_step_m"],
            "max_step_m": stats["max_step_m"],
            "step_flagged": stats["flagged_step"],
            "sample_sha256": digest,
        })
    total_values = sum(r["value_count"] for r in index_rows)
    total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
    if len(index_rows) != EXPECTED_SEGMENTS or total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise SystemExit(f"realized scope {len(index_rows)}/{total_values}/{total_bytes} != pinned "
                         f"{EXPECTED_SEGMENTS}/{EXPECTED_VALUES}/{EXPECTED_BYTES}")
    values_sorted = sorted(r["value_count"] for r in index_rows)
    median_values = statistics.median(values_sorted)
    if total_values < 10_000 or median_values < 1_000 or total_bytes > 1_000_000_000:
        raise SystemExit("acceptance floors/cap not met")
    tmp_index = index_path.with_suffix(".tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    tmp_index.replace(index_path)
    stats_doc = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "revision": REVISION,
        "segments": len(index_rows),
        "routes": len({r["route"] for r in index_rows}),
        "dongles": sorted({r["dongle_id"] for r in index_rows}),
        "segments_per_dongle": {d: sum(1 for r in index_rows if r["dongle_id"] == d) for d in sorted({r["dongle_id"] for r in index_rows})},
        "values": total_values,
        "bytes": total_bytes,
        "frames_min": min(frames_list),
        "frames_median": statistics.median(frames_list),
        "frames_max": max(frames_list),
        "segments_below_1000_values": sum(1 for v in values_sorted if v < 1000),
        "median_values": median_values,
        "global_min": min(r["min"] for r in index_rows),
        "global_max": max(r["max"] for r in index_rows),
        "max_step_m": max(r["max_step_m"] for r in index_rows),
        "step_flag_threshold_m": STEP_FLAG_M,
        "step_flagged_segments": flagged,
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.write_text(json.dumps(stats_doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats_doc.items() if k != "step_flagged_segments"}, sort_keys=True))
    print(f"step_flagged_segments={len(flagged)}")
    return 0


# --------------------------------------------------------------------------
# verify (independent re-derivation from downloaded central directories)
# --------------------------------------------------------------------------

NPY_SHAPE_RE = re.compile(r"'shape':\s*\((\d+),\s*3\)")


def verify_npy(raw: bytes) -> tuple[int, bytes]:
    if not raw.startswith(b"\x93NUMPY\x01\x00") and not raw.startswith(b"\x93NUMPY\x02\x00"):
        raise SystemExit("verify: NPY magic/version")
    if raw[6] == 1:
        hl = int.from_bytes(raw[8:10], "little")
        header = raw[10 : 10 + hl].decode("latin1")
        body = raw[10 + hl :]
    else:
        hl = int.from_bytes(raw[8:12], "little")
        header = raw[12 : 12 + hl].decode("latin1")
        body = raw[12 + hl :]
    if "'descr': '<f8'" not in header or "'fortran_order': False" not in header:
        raise SystemExit(f"verify: NPY header {header!r}")
    match = NPY_SHAPE_RE.search(header)
    if not match:
        raise SystemExit(f"verify: NPY shape {header!r}")
    frames = int(match.group(1))
    if len(body) != frames * 24:
        raise SystemExit("verify: NPY body length")
    return frames, body


def cmd_verify(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    chunks = load_chunks(Path(args.chunks))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    primaries = [s for s in manifest["series"] if s.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0]["id"] != SERIES_ID:
        raise SystemExit("verify: manifest must declare exactly the one primary series")
    series = primaries[0]

    # Re-derive the member list straight from the central directories.
    expected: dict[str, dict] = {}
    for k, pins in chunks.items():
        cd = (downloads / "chunks" / f"Chunk_{k:02d}.central_directory.bin").read_bytes()
        if hashlib.sha256(cd).hexdigest() != pins["cd_sha256"]:
            raise SystemExit(f"verify: chunk {k} central directory hash")
        entries = parse_central_directory(cd)
        offsets = sorted(e["offset"] for e in entries) + [pins["cd_offset"]]
        next_offset = {offsets[i]: offsets[i + 1] for i in range(len(offsets) - 1)}
        for e in entries:
            if e["name"].endswith(MEMBER_SUFFIX):
                _chunk, route, segment, _gp, _leaf = e["name"].split("/")
                e["chunk"] = k
                e["range_bytes"] = next_offset[e["offset"]] - e["offset"]
                e["route"], e["segment"] = route, segment
                expected[f"samples/{DATASET_ID}/{SERIES_ID}/{sample_name(route, segment)}"] = e
    if len(expected) != EXPECTED_SEGMENTS:
        raise SystemExit(f"verify: {len(expected)} segments in central directories")

    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    paths = [r["sample_path"] for r in rows]
    if len(rows) != EXPECTED_SEGMENTS or len(set(paths)) != len(paths) or set(paths) != set(expected):
        raise SystemExit("verify: index rows do not match the central-directory member set")
    on_disk = {p.relative_to(data_root).as_posix() for p in (Path(args.samples_dir) / SERIES_ID).iterdir()}
    if on_disk != set(paths):
        raise SystemExit(f"verify: sample directory has {len(on_disk ^ set(paths))} unexpected/missing files")

    aggregate = hashlib.sha256()
    total_values = total_bytes = 0
    flagged = 0
    hashes = set()
    for row in rows:
        e = expected[row["sample_path"]]
        member_path = downloads / "members" / member_relpath(e["chunk"], e["route"], e["segment"])
        blob = member_path.read_bytes()
        if len(blob) != e["range_bytes"] or blob[:4] != b"PK\x03\x04":
            raise SystemExit(f"verify: member range {member_path}")
        nlen, elen = struct.unpack_from("<HH", blob, 26)
        if blob[30 : 30 + nlen].decode() != e["name"]:
            raise SystemExit(f"verify: member name {member_path}")
        payload = blob[30 + nlen + elen : 30 + nlen + elen + e["compressed_bytes"]]
        raw = zlib.decompress(payload, -15) if e["method"] == 8 else payload
        if zlib.crc32(raw) != e["crc32"] or len(raw) != e["uncompressed_bytes"]:
            raise SystemExit(f"verify: CRC32 mismatch {e['name']}")
        frames, body = verify_npy(raw)
        sample = (data_root / row["sample_path"]).read_bytes()
        if sample != body:
            raise SystemExit(f"verify: sample bytes differ from decoded member {row['sample_path']}")
        values = struct.unpack(f"<{frames * 3}d", sample)
        if any(v != v or v in (math.inf, -math.inf) for v in values):
            raise SystemExit(f"verify: non-finite value in {row['sample_path']}")
        for i in range(0, len(values), 3):
            r2 = values[i] ** 2 + values[i + 1] ** 2 + values[i + 2] ** 2
            if not R_MIN_M ** 2 < r2 < R_MAX_M ** 2:
                raise SystemExit(f"verify: implausible ECEF radius in {row['sample_path']} row {i // 3}")
        if len(set(values[0::3])) < 2 or len(set(values[1::3])) < 2 or len(set(values[2::3])) < 2:
            raise SystemExit(f"verify: degenerate component in {row['sample_path']}")
        digest = hashlib.sha256(sample).hexdigest()
        if digest in hashes:
            raise SystemExit(f"verify: duplicate sample payload {row['sample_path']}")
        hashes.add(digest)
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
            "endianness": "little", "element_size_bytes": 8, "sample_size_bytes": len(sample),
            "value_count": frames * 3, "frame_count": frames, "sample_shape": [frames, 3],
            "min": min(values), "max": max(values), "sample_sha256": digest,
            "source_member": e["name"], "chunk": e["chunk"],
        }
        for key, want in checks.items():
            if row.get(key) != want:
                raise SystemExit(f"verify: index field {key} for {row['sample_path']}: {row.get(key)!r} != {want!r}")
        flagged += bool(row.get("step_flagged"))
        aggregate.update(sample)
        total_values += frames * 3
        total_bytes += len(sample)
    if (total_values, total_bytes) != (EXPECTED_VALUES, EXPECTED_BYTES):
        raise SystemExit(f"verify: totals {total_values}/{total_bytes}")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        raise SystemExit("verify: manifest sample_count/total_size_bytes disagree with output")
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if stats.get("aggregate_sha256") != aggregate.hexdigest():
        raise SystemExit("verify: aggregate sha256 differs from build stats")
    counts = sorted(r["value_count"] for r in rows)
    print(f"verify_ok samples={len(rows)} values={total_values} bytes={total_bytes} "
          f"median_values={statistics.median(counts)} min_values={counts[0]} step_flagged={flagged} "
          f"aggregate_sha256={aggregate.hexdigest()}")
    return 0


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def make_npy(rows: list[tuple[float, float, float]], major: int = 1) -> bytes:
    header = "{'descr': '<f8', 'fortran_order': False, 'shape': (%d, 3), }" % len(rows)
    prefix_len = 10 if major == 1 else 12
    pad = 64 - (prefix_len + len(header) + 1) % 64
    header = header + " " * pad + "\n"
    length = struct.pack("<H", len(header)) if major == 1 else struct.pack("<I", len(header))
    body = b"".join(struct.pack("<3d", *r) for r in rows)
    return b"\x93NUMPY" + bytes([major, 0]) + length + header.encode("latin1") + body


def cmd_selftest(_args: argparse.Namespace) -> int:
    rows = [(-2712361.2837528656 + 1.4 * i, -4262268.190377408 - 0.9 * i, 3880170.6714955037 + 0.3 * i) for i in range(500)]
    npy1 = make_npy(rows, 1)
    npy2 = make_npy(rows, 2)
    for npy in (npy1, npy2):
        frames, body = parse_npy_positions(npy)
        assert frames == 500 and body == b"".join(struct.pack("<3d", *r) for r in rows)
        assert verify_npy(npy) == (frames, body)
        st = position_stats(body, frames)
        assert not st["flagged_step"] and abs(st["max_step_m"] - math.sqrt(1.4**2 + 0.9**2 + 0.3**2)) < 1e-6
    for bad in (npy1.replace(b"'<f8'", b"'>f8'"), npy1.replace(b"False", b"True "), npy1[:-8]):
        try:
            parse_npy_positions(bad)
        except SemanticError:
            pass
        else:
            raise AssertionError("bad NPY accepted")
    gap = rows[:250] + [(r[0] + 50.0, r[1], r[2]) for r in rows[250:]]
    assert position_stats(parse_npy_positions(make_npy(gap))[1], 500)["flagged_step"]
    for bad_rows in ([(0.0, 0.0, 0.0)] + rows[1:], [(1.0, 2.0, 3.0)] + rows[1:], [(float("nan"), 0.0, 0.0)] + rows[1:]):
        try:
            position_stats(b"".join(struct.pack("<3d", *r) for r in bad_rows), 500)
        except SemanticError:
            pass
        else:
            raise AssertionError("bad positions accepted")

    # Real zipfile archive with forced ZIP64 local extras, deflate and stored members.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for seg, method in (("0", zipfile.ZIP_DEFLATED), ("1", zipfile.ZIP_STORED)):
            base = f"Chunk_3/0123456789abcdef|2018-07-30--13-44-30/{seg}"
            zf.writestr(f"{base}/global_pose/frame_times", b"x" * 77, compress_type=method)
            info = zipfile.ZipInfo(f"{base}/global_pose/frame_positions")
            info.compress_type = method
            with zf.open(info, "w", force_zip64=True) as handle:
                handle.write(npy1 if seg == "0" else npy2)
            zf.writestr(f"{base}/global_pose/frame_orientations", b"y" * 99, compress_type=method)
    archive = buf.getvalue()
    tail = archive[-TAIL_BYTES:] if len(archive) > TAIL_BYTES else archive
    info = parse_tail(tail, len(archive))
    cd = archive[info["cd_offset"] : info["cd_offset"] + info["cd_bytes"]]
    entries = parse_central_directory(cd)
    pins = {
        "cd_sha256": hashlib.sha256(cd).hexdigest(), "cd_bytes": len(cd), "cd_entries": len(entries),
        "cd_offset": info["cd_offset"], "positions_members": 2,
    }
    plan_probe = build_plan_unpinned(3, entries, info["cd_offset"])
    pins["positions_range_bytes"] = sum(p["range_end"] - p["range_start"] + 1 for p in plan_probe)
    pins["positions_npy_bytes"] = sum(p["uncompressed_bytes"] for p in plan_probe)
    plan = build_plan(3, cd, pins)
    decoded = []
    for p in plan:
        blob = archive[p["range_start"] : p["range_end"] + 1]
        raw = decode_local_entry(blob, p)
        decoded.append(raw)
        try:
            decode_local_entry(blob[:-1] + bytes([blob[-1] ^ 0xFF]), p)
        except TransportError:
            pass
        else:
            raise AssertionError("corrupted member accepted")
    assert decoded == [npy1, npy2], "zip member round-trip failed"

    # Hand-built ZIP64 central directory entry with all three sentinels.
    name = b"Chunk_9/0123456789abcdef|2018-07-30--13-44-30/5/global_pose/frame_positions"
    extra = struct.pack("<HHQQQ", 1, 24, 28928, 19539, 8_000_000_123)
    entry = struct.pack("<IHHHHHHIIIHHHHHII", SIG_CENTRAL, 45, 45, 0, 8, 0, 0, 0x1E113E18,
                        0xFFFFFFFF, 0xFFFFFFFF, len(name), len(extra), 0, 0, 0, 0, 0xFFFFFFFF) + name + extra
    (parsed,) = parse_central_directory(entry)
    assert (parsed["uncompressed_bytes"], parsed["compressed_bytes"], parsed["offset"]) == (28928, 19539, 8_000_000_123)

    # Hand-built ZIP64 tail: EOCD64 + locator + EOCD with sentinels.
    cd_off, cd_size, n = 9_000_000_000, 1_234_567, 11_209
    eocd64_off = cd_off + cd_size
    rec = struct.pack("<IQHHIIQQQQ", SIG_EOCD64, 44, 45, 45, 0, 0, n, n, cd_size, cd_off)
    loc = struct.pack("<IIQI", SIG_LOCATOR64, 0, eocd64_off, 1)
    eocd = struct.pack("<IHHHHIIH", SIG_EOCD, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    fake_tail = b"\0" * (TAIL_BYTES - 98) + rec + loc + eocd
    t = parse_tail(fake_tail, eocd64_off + 98)
    assert (t["cd_offset"], t["cd_bytes"], t["entries"], t["eocd64_offset"]) == (cd_off, cd_size, n, eocd64_off)
    print("selftest_ok zip64_cd zip64_tail deflate stored crc npy_v1 npy_v2 ecef_checks step_flag")
    return 0


def build_plan_unpinned(chunk: int, entries: list[dict], cd_offset: int) -> list[dict]:
    ordered = sorted(entries, key=lambda e: e["offset"])
    out = []
    for i, e in enumerate(ordered):
        if e["name"].endswith(MEMBER_SUFFIX):
            end = ordered[i + 1]["offset"] if i + 1 < len(ordered) else cd_offset
            out.append({"range_start": e["offset"], "range_end": end - 1, "uncompressed_bytes": e["uncompressed_bytes"]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-readme"); p.add_argument("--readme", required=True)
    p = sub.add_parser("check-head"); p.add_argument("--headers", required=True); p.add_argument("--chunk", type=int, required=True)
    p.add_argument("--size", type=int, required=True); p.add_argument("--sha256", required=True)
    p = sub.add_parser("check-tail"); p.add_argument("--chunks", required=True); p.add_argument("--chunk", type=int, required=True)
    p.add_argument("--tail", required=True)
    p = sub.add_parser("plan"); p.add_argument("--chunks", required=True); p.add_argument("--chunk", type=int, required=True)
    p.add_argument("--cd", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("pending"); p.add_argument("--plan-dir", required=True); p.add_argument("--members-dir", required=True)
    p.add_argument("--count", action="store_true"); p.add_argument("--chunk", type=int)
    p = sub.add_parser("validate"); p.add_argument("--plan-dir", required=True); p.add_argument("--members-dir", required=True)
    p.add_argument("--summary")
    p = sub.add_parser("build")
    for name in ("--downloads", "--samples-dir", "--index", "--stats", "--data-root"):
        p.add_argument(name, required=True)
    p = sub.add_parser("verify")
    for name in ("--downloads", "--samples-dir", "--index", "--stats", "--data-root", "--chunks", "--manifest"):
        p.add_argument(name, required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    handlers = {
        "check-readme": cmd_check_readme, "check-head": cmd_check_head, "check-tail": cmd_check_tail,
        "plan": cmd_plan, "pending": cmd_pending, "validate": cmd_validate, "build": cmd_build,
        "verify": cmd_verify, "selftest": cmd_selftest,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
