#!/usr/bin/env python3
"""TartanAir V1 dense optical-flow recipe helpers (standard library only).

The upstream flow archives are 4-63 GB ZIP64 files on the Hugging Face hub,
so download.sh never fetches a whole archive.  It range-fetches each archive
tail, the exact central directory, and the exact local-header-plus-data byte
span of a few deterministically selected `*_flow.npy` members.  This module
parses what curl fetched; it never performs network I/O itself.

Subcommands
  sources-from-tree  turn a pinned HF tree listing into sources.tsv rows
  check-repo         validate HF revision metadata + tree against sources.tsv
  check-license-page soft check of the CC BY 4.0 notice on theairlab.org
  check-headers      validate curl --dump-header output of one range request
  tail-info          locate the ZIP64 central directory from an archive tail
  select             parse a central directory and print the selected members
  check-member       validate one fetched member span (CRC32 + npy header)
  build              decode selected members into raw float32 samples + index
  verify             independently re-derive every sample and check the index
"""
from __future__ import annotations

import argparse
import ast
import array
import hashlib
import html
import json
import math
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

DATASET_ID = "tartanair_optical_flow_f32"
SERIES_ID = "tartanair_left_optical_flow_uv_f32"
REPO_ID = "theairlabcmu/tartanair"
REVISION = "65e00180ea952475878a748543e11e9ec20beaac"
HF_LICENSE = "bsd-3-clause"
TAIL_BYTES = 65536
SLOTS_PER_ARCHIVE = 3
FLOW_SHAPE = (480, 640, 2)
FLOW_VALUES = FLOW_SHAPE[0] * FLOW_SHAPE[1] * FLOW_SHAPE[2]
FLOW_PAYLOAD_BYTES = FLOW_VALUES * 4
NPY_MEMBER_BYTES = 128 + FLOW_PAYLOAD_BYTES
MEMBER_RE_TEMPLATE = r"^{env}/{difficulty}/(P\d{{3}})/flow/(\d{{6}})_(\d{{6}})_flow\.npy$"

SIG_EOCD = 0x06054B50
SIG_Z64_LOCATOR = 0x07064B50
SIG_Z64_EOCD = 0x06064B50
SIG_CENTRAL = 0x02014B50
SIG_LOCAL = 0x04034B50


class RecipeError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise RecipeError(message)


# --------------------------------------------------------------------------
# sources.tsv
# --------------------------------------------------------------------------

SOURCE_COLUMNS = ["zip_path", "environment", "difficulty", "size_bytes", "lfs_sha256", "xet_hash"]


@dataclass(frozen=True)
class Source:
    zip_path: str
    environment: str
    difficulty: str
    size_bytes: int
    lfs_sha256: str
    xet_hash: str

    @property
    def key(self) -> str:
        return f"{self.environment}/{self.difficulty}"

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{REPO_ID}/resolve/{REVISION}/{self.zip_path}"


def load_sources(path: Path) -> list[Source]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != SOURCE_COLUMNS:
        fail(f"{path}: unexpected header {lines[:1]!r}")
    sources: list[Source] = []
    for number, line in enumerate(lines[1:], 2):
        parts = line.split("\t")
        if len(parts) != len(SOURCE_COLUMNS):
            fail(f"{path}:{number}: expected {len(SOURCE_COLUMNS)} columns")
        zip_path, env, difficulty, size, sha, xet = parts
        if zip_path != f"{env}/{difficulty}/flow_flow.zip" or difficulty not in {"Easy", "Hard"}:
            fail(f"{path}:{number}: inconsistent source row {parts!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(r"[0-9a-f]{64}", xet):
            fail(f"{path}:{number}: malformed hashes")
        sources.append(Source(zip_path, env, difficulty, int(size), sha, xet))
    if len({s.zip_path for s in sources}) != len(sources):
        fail(f"{path}: duplicate archives")
    return sources


def cmd_sources_from_tree(args: argparse.Namespace) -> None:
    tree = json.loads(Path(args.tree).read_text(encoding="utf-8"))
    rows = []
    for item in tree:
        path = str(item.get("path", ""))
        if item.get("type") != "file" or not path.endswith("/flow_flow.zip"):
            continue
        env, difficulty, _ = path.split("/")
        lfs = item.get("lfs") or {}
        if int(lfs.get("size", -1)) != int(item["size"]):
            fail(f"{path}: LFS size disagrees with listing size")
        rows.append((path, env, difficulty, str(item["size"]), str(lfs["oid"]), str(item["xetHash"])))
    rows.sort()
    print("\t".join(SOURCE_COLUMNS))
    for row in rows:
        print("\t".join(row))


def cmd_check_repo(args: argparse.Namespace) -> None:
    info = json.loads(Path(args.repo_json).read_text(encoding="utf-8"))
    tree = json.loads(Path(args.tree_json).read_text(encoding="utf-8"))
    sources = load_sources(Path(args.sources))
    if info.get("id") != REPO_ID or info.get("sha") != REVISION:
        fail(f"unexpected repo identity {info.get('id')!r}@{info.get('sha')!r}")
    if info.get("private") or info.get("gated") not in (False, None) or info.get("disabled"):
        fail(f"repo is not public/ungated: private={info.get('private')} gated={info.get('gated')}")
    card_license = (info.get("cardData") or {}).get("license")
    if card_license != HF_LICENSE:
        fail(f"HF dataset card license changed: {card_license!r}")
    listing = {str(item.get("path")): item for item in tree if isinstance(item, dict)}
    for source in sources:
        item = listing.get(source.zip_path)
        if item is None:
            fail(f"{source.zip_path} missing from the pinned tree listing")
        lfs = item.get("lfs") or {}
        if (
            int(item.get("size", -1)) != source.size_bytes
            or lfs.get("oid") != source.lfs_sha256
            or item.get("xetHash") != source.xet_hash
        ):
            fail(f"{source.zip_path}: size/LFS sha256/xet hash differ from sources.tsv")
    listed = sorted(p for p in listing if p.endswith("/flow_flow.zip"))
    if listed != sorted(s.zip_path for s in sources):
        fail(f"sources.tsv does not cover exactly the {len(listed)} flow_flow.zip archives at {REVISION}")
    total = sum(s.size_bytes for s in sources)
    print(
        f"repo_validation=ok repo={REPO_ID} revision={REVISION} license={card_license} "
        f"archives={len(sources)} archive_bytes_total={total}"
    )


def cmd_check_license_page(args: argparse.Namespace) -> None:
    page = Path(args.page).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    needle = "licensed under a Creative Commons Attribution 4.0 International License"
    if needle in text and "creativecommons.org/licenses/by/4.0" in page:
        print("license_page=ok notice='This work is licensed under a Creative Commons Attribution 4.0 International License.'")
    else:
        print("WARNING license_page: CC BY 4.0 notice not found on theairlab.org/tartanair-dataset; re-check rights before acceptance")


# --------------------------------------------------------------------------
# HTTP range response validation
# --------------------------------------------------------------------------

def parse_header_blocks(text: str) -> list[tuple[int, dict[str, list[str]]]]:
    blocks: list[tuple[int, dict[str, list[str]]]] = []
    for chunk in re.split(r"(?=^HTTP/)", text, flags=re.M):
        lines = [line.rstrip("\r") for line in chunk.splitlines()]
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        match = re.match(r"HTTP/\S+\s+(\d{3})", lines[0])
        status = int(match.group(1)) if match else 0
        headers: dict[str, list[str]] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers.setdefault(name.strip().lower(), []).append(value.strip())
        blocks.append((status, headers))
    return blocks


def check_headers(text: str, size: int, etag: str, start: int, end: int) -> str:
    blocks = parse_header_blocks(text)
    # Proxy CONNECT replies ("HTTP/1.1 200 Connection established") carry no
    # content headers; ignore them when looking for the final response.
    real = [(s, h) for s, h in blocks if not (s == 200 and "content-length" not in h and "content-range" not in h)]
    if not real:
        fail("no HTTP response headers captured")
    status, final = real[-1]
    if status != 206:
        fail(f"final response status {status}, expected 206 Partial Content")
    content_range = (final.get("content-range") or [""])[-1]
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
    if not match or tuple(map(int, match.groups())) != (start, end, size):
        fail(f"unexpected Content-Range {content_range!r}; wanted bytes {start}-{end}/{size}")
    commits = [v for _, h in blocks for v in h.get("x-repo-commit", [])]
    etags = [v.strip('"') for _, h in blocks for v in h.get("x-linked-etag", [])]
    sizes = [v for _, h in blocks for v in h.get("x-linked-size", [])]
    if not commits or any(c != REVISION for c in commits):
        fail(f"resolver did not confirm revision {REVISION}: {commits!r}")
    if not etags or any(e != etag for e in etags):
        fail(f"resolver x-linked-etag {etags!r} != pinned LFS sha256 {etag}")
    if sizes and any(int(s) != size for s in sizes):
        fail(f"resolver x-linked-size {sizes!r} != pinned size {size}")
    return f"range_headers=ok status=206 range={start}-{end}/{size} commit={REVISION[:12]} etag={etag[:12]}"


def cmd_check_headers(args: argparse.Namespace) -> None:
    text = Path(args.headers).read_text(encoding="iso-8859-1")
    print(check_headers(text, args.size, args.etag, args.start, args.end))
    body = Path(args.body)
    if body.stat().st_size != args.end - args.start + 1:
        fail(f"{body}: {body.stat().st_size} bytes, expected {args.end - args.start + 1}")


# --------------------------------------------------------------------------
# ZIP64 structures
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Directory:
    cd_offset: int
    cd_size: int
    entries: int


@dataclass(frozen=True)
class Entry:
    name: str
    local_offset: int
    compressed_size: int
    uncompressed_size: int
    crc32: int
    method: int
    flags: int


def parse_tail(tail: bytes, zip_size: int) -> Directory:
    base = zip_size - len(tail)
    if base < 0:
        fail("tail longer than archive")
    eocd = tail.rfind(struct.pack("<I", SIG_EOCD))
    if eocd < 0 or eocd + 22 > len(tail):
        fail("end-of-central-directory record not found in tail")
    _, disk, cd_disk, n_disk, n_total, cd_size32, cd_off32, comment_len = struct.unpack_from("<IHHHHIIH", tail, eocd)
    if eocd + 22 + comment_len != len(tail):
        fail("EOCD comment does not end at the archive end")
    if disk != 0 or cd_disk != 0 or n_disk != n_total:
        fail("multi-disk archives are not supported")
    locator = eocd - 20
    if locator < 0 or struct.unpack_from("<I", tail, locator)[0] != SIG_Z64_LOCATOR:
        fail("ZIP64 end-of-central-directory locator missing")
    _, z64_disk, z64_offset, total_disks = struct.unpack_from("<IIQI", tail, locator)
    if z64_disk != 0 or total_disks != 1:
        fail("unexpected ZIP64 locator disk fields")
    rel = z64_offset - base
    if rel < 0 or rel + 56 > locator:
        fail("ZIP64 EOCD record is outside the fetched tail")
    (sig, record_size, _made, _need, disk64, cd_disk64, n_disk64, n_total64, cd_size, cd_offset) = struct.unpack_from(
        "<IQHHIIQQQQ", tail, rel
    )
    if sig != SIG_Z64_EOCD or disk64 != 0 or cd_disk64 != 0 or n_disk64 != n_total64:
        fail("malformed ZIP64 EOCD record")
    if rel + 12 + record_size != locator:
        fail("ZIP64 EOCD record size does not reach the locator")
    if cd_offset + cd_size != z64_offset:
        fail("central directory does not end at the ZIP64 EOCD record")
    for small, big, sentinel in ((n_total, n_total64, 0xFFFF), (cd_size32, cd_size, 0xFFFFFFFF), (cd_off32, cd_offset, 0xFFFFFFFF)):
        if small != sentinel and small != big:
            fail("classic EOCD fields disagree with ZIP64 EOCD fields")
    if n_total64 <= 0 or cd_size <= 0:
        fail("empty central directory")
    return Directory(cd_offset, cd_size, n_total64)


def parse_central_directory(cd: bytes, directory: Directory) -> list[Entry]:
    if len(cd) != directory.cd_size:
        fail(f"central directory is {len(cd)} bytes, expected {directory.cd_size}")
    entries: list[Entry] = []
    pos = 0
    while pos < len(cd):
        if pos + 46 > len(cd):
            fail("truncated central directory header")
        (sig, _made, _need, flags, method, _t, _d, crc, csize, usize, nlen, xlen, clen, disk, _ia, _ea, offset) = (
            struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, pos)
        )
        if sig != SIG_CENTRAL:
            fail(f"bad central directory signature at +{pos}")
        name_raw = cd[pos + 46 : pos + 46 + nlen]
        name = name_raw.decode("utf-8" if flags & 0x800 else "cp437")
        extra = cd[pos + 46 + nlen : pos + 46 + nlen + xlen]
        q = 0
        while q + 4 <= len(extra):
            header_id, size = struct.unpack_from("<HH", extra, q)
            body = extra[q + 4 : q + 4 + size]
            if header_id == 0x0001:
                r = 0
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack_from("<Q", body, r)[0]
                    r += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack_from("<Q", body, r)[0]
                    r += 8
                if offset == 0xFFFFFFFF:
                    offset = struct.unpack_from("<Q", body, r)[0]
                    r += 8
                if disk == 0xFFFF:
                    r += 4
                if r > len(body):
                    fail(f"{name}: ZIP64 extra field too short")
            q += 4 + size
        if q != len(extra):
            fail(f"{name}: malformed extra field block")
        if 0xFFFFFFFF in (usize, csize, offset):
            fail(f"{name}: ZIP64 sentinel without a ZIP64 extra field")
        entries.append(Entry(name, offset, csize, usize, crc, method, flags))
        pos += 46 + nlen + xlen + clen
    if pos != len(cd) or len(entries) != directory.entries:
        fail(f"central directory parsed {len(entries)} entries, EOCD declares {directory.entries}")
    return entries


def select_members(entries: list[Entry], directory: Directory, env: str, difficulty: str) -> list[tuple[Entry, int]]:
    """Return [(entry, span_end_exclusive)] for the deterministic selection.

    Rule: group `<env>/<difficulty>/Pxxx/flow/NNNNNN_MMMMMM_flow.npy` members
    (MMMMMM = NNNNNN + 1) by trajectory, sort trajectory names, and give slot
    k (k = 0..2) to trajectory index floor((2k+1) n / 6).  Within a
    trajectory that receives c slots, sort its frames and take positions
    floor((2j+1) m / (2c)), j = 0..c-1.  With n >= 3 trajectories this is the
    temporal middle frame of three evenly spread trajectories, so no two
    samples share a trajectory.
    """
    ordered = sorted(entries, key=lambda e: e.local_offset)
    offsets = [e.local_offset for e in ordered]
    if len(set(offsets)) != len(offsets):
        fail("duplicate local header offsets")
    span_end = {}
    for index, entry in enumerate(ordered):
        span_end[entry.name] = offsets[index + 1] if index + 1 < len(ordered) else directory.cd_offset
    pattern = re.compile(MEMBER_RE_TEMPLATE.format(env=re.escape(env), difficulty=re.escape(difficulty)))
    by_traj: dict[str, list[tuple[int, Entry]]] = {}
    for entry in entries:
        match = pattern.match(entry.name)
        if not match:
            continue
        traj, first, second = match.group(1), int(match.group(2)), int(match.group(3))
        if second != first + 1:
            fail(f"{entry.name}: flow pair is not consecutive")
        if entry.uncompressed_size != NPY_MEMBER_BYTES or entry.method != 8:
            fail(f"{entry.name}: unexpected size {entry.uncompressed_size} or method {entry.method}")
        by_traj.setdefault(traj, []).append((first, entry))
    trajectories = sorted(by_traj)
    n = len(trajectories)
    if n == 0:
        fail(f"{env}/{difficulty}: no flow members found")
    slots: dict[str, int] = {}
    for k in range(SLOTS_PER_ARCHIVE):
        traj = trajectories[(2 * k + 1) * n // (2 * SLOTS_PER_ARCHIVE)]
        slots[traj] = slots.get(traj, 0) + 1
    picked: list[tuple[Entry, int]] = []
    for traj in sorted(slots):
        frames = sorted(by_traj[traj], key=lambda item: item[0])
        if len({f for f, _ in frames}) != len(frames):
            fail(f"{env}/{difficulty}/{traj}: duplicate frame indices")
        c, m = slots[traj], len(frames)
        if m < c:
            fail(f"{env}/{difficulty}/{traj}: only {m} frames for {c} slots")
        for j in range(c):
            entry = frames[(2 * j + 1) * m // (2 * c)][1]
            picked.append((entry, span_end[entry.name]))
    if len(picked) != SLOTS_PER_ARCHIVE:
        fail(f"{env}/{difficulty}: selected {len(picked)} members")
    return picked


def cmd_tail_info(args: argparse.Namespace) -> None:
    tail = Path(args.tail).read_bytes()
    if len(tail) != min(TAIL_BYTES, args.zip_size):
        fail(f"tail is {len(tail)} bytes")
    directory = parse_tail(tail, args.zip_size)
    print(directory.cd_offset, directory.cd_size, directory.entries)


SELECTION_COLUMNS = ["zip_path", "member", "trajectory", "span_start", "span_end", "compressed_size", "uncompressed_size", "crc32"]


def selection_rows(source: Source, tail: bytes, cd: bytes) -> list[list[str]]:
    directory = parse_tail(tail, source.size_bytes)
    entries = parse_central_directory(cd, directory)
    rows = []
    for entry, end in select_members(entries, directory, source.environment, source.difficulty):
        traj = entry.name.split("/")[2]
        rows.append(
            [
                source.zip_path,
                entry.name,
                traj,
                str(entry.local_offset),
                str(end - 1),
                str(entry.compressed_size),
                str(entry.uncompressed_size),
                f"{entry.crc32:08x}",
            ]
        )
    return rows


def cmd_select(args: argparse.Namespace) -> None:
    source = next((s for s in load_sources(Path(args.sources)) if s.zip_path == args.zip_path), None)
    if source is None:
        fail(f"{args.zip_path} not in sources.tsv")
    rows = selection_rows(source, Path(args.tail).read_bytes(), Path(args.cd).read_bytes())
    for row in rows:
        print("\t".join(row))


def member_file(download_root: Path, zip_path: str, member: str) -> Path:
    env, difficulty, _ = zip_path.split("/")
    parts = member.split("/")
    return download_root / "zips" / env / difficulty / "members" / f"{parts[2]}__{parts[4]}.zipentry"


# --------------------------------------------------------------------------
# member span -> npy -> float32 payload
# --------------------------------------------------------------------------

def parse_npy_header(raw: bytes) -> tuple[int, dict]:
    if raw[:6] != b"\x93NUMPY":
        fail("member is not an .npy file")
    major, minor = raw[6], raw[7]
    if (major, minor) != (1, 0):
        fail(f"unexpected .npy version {major}.{minor}")
    header_len = struct.unpack_from("<H", raw, 8)[0]
    prefix = 10 + header_len
    header_text = raw[10:prefix].decode("latin1")
    if not header_text.endswith("\n"):
        fail(".npy header is not newline-terminated")
    header = ast.literal_eval(header_text)
    if not isinstance(header, dict) or set(header) != {"descr", "fortran_order", "shape"}:
        fail(f"unexpected .npy header {header_text!r}")
    if header["descr"] != "<f4" or header["fortran_order"] is not False or tuple(header["shape"]) != FLOW_SHAPE:
        fail(f"unexpected .npy dtype/order/shape {header!r}")
    if len(raw) - prefix != FLOW_PAYLOAD_BYTES:
        fail(f".npy payload is {len(raw) - prefix} bytes, expected {FLOW_PAYLOAD_BYTES}")
    return prefix, header


def decode_member_span(span: bytes, name: str, csize: int, usize: int, crc: int, *, streaming: bool = True) -> bytes:
    """Validate a local header + data span and return the inflated member."""
    if len(span) < 30:
        fail(f"{name}: span too short")
    (sig, _need, flags, method, _t, _d, lcrc, lcsize, lusize, nlen, xlen) = struct.unpack_from("<IHHHHHIIIHH", span, 0)
    if sig != SIG_LOCAL:
        fail(f"{name}: missing local file header signature")
    lname = span[30 : 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    if lname != name:
        fail(f"local header names {lname!r}, expected {name!r}")
    if method != 8 or flags & 0x1:
        fail(f"{name}: unexpected method {method} / flags {flags:#x}")
    if not flags & 0x8:
        if lcrc != crc or (lcsize != 0xFFFFFFFF and lcsize != csize) or (lusize != 0xFFFFFFFF and lusize != usize):
            fail(f"{name}: local header CRC/sizes disagree with the central directory")
    data_start = 30 + nlen + xlen
    trailing = len(span) - data_start - csize
    allowed = {0} if not flags & 0x8 else {12, 16, 20, 24}
    if trailing not in allowed:
        fail(f"{name}: span has {trailing} bytes after the compressed data (allowed {sorted(allowed)})")
    compressed = memoryview(span)[data_start : data_start + csize]
    if streaming:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        pieces = []
        for offset in range(0, len(compressed), 1 << 20):
            pieces.append(inflater.decompress(compressed[offset : offset + (1 << 20)]))
        pieces.append(inflater.flush())
        if not inflater.eof or inflater.unused_data:
            fail(f"{name}: DEFLATE stream does not end exactly at the compressed size")
        raw = b"".join(pieces)
    else:
        raw = zlib.decompress(bytes(compressed), -zlib.MAX_WBITS)
    if len(raw) != usize or zlib.crc32(raw) & 0xFFFFFFFF != crc:
        fail(f"{name}: inflated size/CRC32 mismatch")
    return raw


def flow_stats(payload: bytes) -> dict:
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    finite = sum(map(math.isfinite, values))
    nonfinite = len(values) - finite
    u = values[0::2]
    v = values[1::2]
    stats = {"nonfinite_count": nonfinite}
    if nonfinite == 0:
        stats.update(
            {
                "min": min(values),
                "max": max(values),
                "u_min": min(u),
                "u_max": max(u),
                "v_min": min(v),
                "v_max": max(v),
                "mean_abs": math.fsum(map(abs, values)) / len(values),
            }
        )
    return stats


def cmd_check_member(args: argparse.Namespace) -> None:
    span = Path(args.entry).read_bytes()
    raw = decode_member_span(span, args.name, args.csize, args.usize, int(args.crc32, 16))
    prefix, header = parse_npy_header(raw)
    stats = flow_stats(raw[prefix:])
    if stats["nonfinite_count"]:
        fail(f"{args.name}: {stats['nonfinite_count']} non-finite float32 values")
    if stats["u_min"] == stats["u_max"] or stats["v_min"] == stats["v_max"]:
        fail(f"{args.name}: constant flow component")
    print(
        f"member_validation=ok name={args.name} crc32={args.crc32} npy_prefix={prefix} "
        f"descr={header['descr']} shape={tuple(header['shape'])} u=[{stats['u_min']:.3f},{stats['u_max']:.3f}] "
        f"v=[{stats['v_min']:.3f},{stats['v_max']:.3f}]"
    )


# --------------------------------------------------------------------------
# build / verify
# --------------------------------------------------------------------------

def paths(repo_root: Path, data_dir: str) -> dict[str, Path]:
    root = (repo_root / data_dir).resolve()
    return {
        "data": root,
        "downloads": root / "downloads" / DATASET_ID,
        "samples": root / "samples" / DATASET_ID / SERIES_ID,
        "index": root / "index" / DATASET_ID / "samples.jsonl",
        "filtered": root / "filtered" / DATASET_ID,
    }


def load_local_archive(download_root: Path, source: Source) -> tuple[bytes, bytes]:
    zdir = download_root / "zips" / source.environment / source.difficulty
    tail = (zdir / "tail.bin").read_bytes()
    cd = (zdir / "cd.bin").read_bytes()
    return tail, cd


def read_selection_file(path: Path) -> list[list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != SELECTION_COLUMNS:
        fail(f"{path}: unexpected header")
    return [line.split("\t") for line in lines[1:] if line]


def sample_name(row: list[str]) -> str:
    zip_path, member = row[0], row[1]
    env, difficulty, _ = zip_path.split("/")
    parts = member.split("/")
    frames = parts[4].removesuffix("_flow.npy")
    return f"{env}__{difficulty}__{parts[2]}__{frames}.f32"


def cmd_build(args: argparse.Namespace) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    derived: list[list[str]] = []
    for source in sources:
        tail, cd = load_local_archive(p["downloads"], source)
        derived.extend(selection_rows(source, tail, cd))
    recorded = read_selection_file(p["downloads"] / "selection.tsv")
    if recorded != derived:
        fail("downloads/selection.tsv differs from the selection re-derived from the local central directories")
    p["samples"].mkdir(parents=True, exist_ok=True)
    for stale in p["samples"].iterdir():
        if stale.is_file():
            stale.unlink()
    p["index"].parent.mkdir(parents=True, exist_ok=True)
    p["filtered"].mkdir(parents=True, exist_ok=True)
    rows_out = []
    trajectories = set()
    archives = set()
    for row in derived:
        zip_path, member, traj, start, end, csize, usize, crc = row
        span_path = member_file(p["downloads"], zip_path, member)
        span = span_path.read_bytes()
        if len(span) != int(end) - int(start) + 1:
            fail(f"{span_path}: wrong span size")
        raw = decode_member_span(span, member, int(csize), int(usize), int(crc, 16))
        prefix, _ = parse_npy_header(raw)
        payload = raw[prefix:]
        stats = flow_stats(payload)
        if stats["nonfinite_count"]:
            fail(f"{member}: {stats['nonfinite_count']} non-finite values (missing-value policy: fatal)")
        if stats["u_min"] == stats["u_max"] or stats["v_min"] == stats["v_max"]:
            fail(f"{member}: constant flow component")
        name = sample_name(row)
        out = p["samples"] / name
        tmp = out.with_suffix(".part")
        tmp.write_bytes(payload)
        os.replace(tmp, out)
        env, difficulty, _ = zip_path.split("/")
        first, second = member.split("/")[4].removesuffix("_flow.npy").split("_")
        trajectories.add((env, difficulty, traj))
        archives.add(zip_path)
        rows_out.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(p["data"])),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": len(payload) // 4,
                "shape": list(FLOW_SHAPE),
                "axes": ["image_row", "image_column", "flow_component"],
                "environment": env,
                "difficulty": difficulty,
                "trajectory": traj,
                "frame_from": int(first),
                "frame_to": int(second),
                "source_archive": zip_path,
                "source_member": member,
                "member_crc32": crc,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "nonfinite_count": 0,
                "min": stats["min"],
                "max": stats["max"],
                "u_min": stats["u_min"],
                "u_max": stats["u_max"],
                "v_min": stats["v_min"],
                "v_max": stats["v_max"],
                "mean_abs_px": round(stats["mean_abs"], 6),
            }
        )
        print(f"sample {name} u=[{stats['u_min']:.3f},{stats['u_max']:.3f}] v=[{stats['v_min']:.3f},{stats['v_max']:.3f}] mean_abs={stats['mean_abs']:.3f}")
    tmp_index = p["index"].with_suffix(".part")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for item in rows_out:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    os.replace(tmp_index, p["index"])
    summary = {
        "dataset_id": DATASET_ID,
        "revision": REVISION,
        "archives": len(archives),
        "trajectories": len(trajectories),
        "samples": len(rows_out),
        "values": sum(r["value_count"] for r in rows_out),
        "bytes": sum(r["sample_size_bytes"] for r in rows_out),
        "global_min": min(r["min"] for r in rows_out),
        "global_max": max(r["max"] for r in rows_out),
        "median_mean_abs_px": sorted(r["mean_abs_px"] for r in rows_out)[len(rows_out) // 2],
    }
    (p["filtered"] / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("build_summary " + json.dumps(summary, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    import tomllib

    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]
    if (series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != ("float", 32, "little"):
        fail("manifest series type is not little-endian float32")

    # Re-derive the selection from the cached archive tails and central
    # directories, independently of downloads/selection.tsv.
    expected: dict[str, list[str]] = {}
    for source in sources:
        tail, cd = load_local_archive(p["downloads"], source)
        for row in selection_rows(source, tail, cd):
            expected[sample_name(row)] = row
    if len(expected) != SLOTS_PER_ARCHIVE * len(sources):
        fail(f"re-derived {len(expected)} selections for {len(sources)} archives")

    rows = [json.loads(line) for line in p["index"].read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(expected):
        fail(f"index has {len(rows)} rows, expected {len(expected)}")
    on_disk = sorted(f.name for f in p["samples"].iterdir() if f.is_file())
    if on_disk != sorted(expected):
        fail("sample directory contents differ from the re-derived selection")
    seen_hashes: set[str] = set()
    seen_traj: set[tuple[str, str, str]] = set()
    total_bytes = 0
    for row in rows:
        name = Path(row["sample_path"]).name
        if name not in expected:
            fail(f"index row for unexpected sample {name}")
        zip_path, member, traj, start, end, csize, usize, crc = expected.pop(name)
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": FLOW_PAYLOAD_BYTES,
            "value_count": FLOW_VALUES,
            "source_archive": zip_path,
            "source_member": member,
            "trajectory": traj,
            "member_crc32": crc,
            "nonfinite_count": 0,
        }
        for key, value in fixed.items():
            if row.get(key) != value:
                fail(f"{name}: index field {key}={row.get(key)!r}, expected {value!r}")
        sample_path = p["data"] / row["sample_path"]
        sample = sample_path.read_bytes()
        if len(sample) != FLOW_PAYLOAD_BYTES:
            fail(f"{name}: sample is {len(sample)} bytes")
        # Independent decode: one-shot inflate of the cached span.
        span = member_file(p["downloads"], zip_path, member).read_bytes()
        raw = decode_member_span(span, member, int(csize), int(usize), int(crc, 16), streaming=False)
        if raw[:6] != b"\x93NUMPY":
            fail(f"{name}: not npy")
        header_len = struct.unpack_from("<H", raw, 8)[0]
        header = ast.literal_eval(raw[10 : 10 + header_len].decode("latin1"))
        if header != {"descr": "<f4", "fortran_order": False, "shape": FLOW_SHAPE}:
            fail(f"{name}: npy header {header!r}")
        if raw[10 + header_len :] != sample:
            fail(f"{name}: sample bytes differ from the decoded upstream float32 tensor")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != row.get("payload_sha256") or digest in seen_hashes:
            fail(f"{name}: payload hash mismatch or duplicate sample")
        seen_hashes.add(digest)
        # Missing-value policy (same as build): any non-finite value is fatal.
        words = array.array("I")
        words.frombytes(sample)
        if sys.byteorder != "little":
            words.byteswap()
        exponent_all_ones = sum(1 for w in words if (w & 0x7F800000) == 0x7F800000)
        if exponent_all_ones:
            fail(f"{name}: {exponent_all_ones} non-finite values")
        values = array.array("f")
        values.frombytes(sample)
        if sys.byteorder != "little":
            values.byteswap()
        u, v = values[0::2], values[1::2]
        checks = {"min": min(values), "max": max(values), "u_min": min(u), "u_max": max(u), "v_min": min(v), "v_max": max(v)}
        for key, value in checks.items():
            if row.get(key) != value:
                fail(f"{name}: index {key}={row.get(key)!r} but stored float32 gives {value!r}")
        if checks["u_min"] == checks["u_max"] or checks["v_min"] == checks["v_max"]:
            fail(f"{name}: constant flow component")
        if len(set(values[: 1 << 16])) < 1000:
            fail(f"{name}: degenerate sample (fewer than 1000 distinct values in the first 65,536)")
        seen_traj.add((row["environment"], row["difficulty"], traj))
        total_bytes += len(sample)
    if expected:
        fail(f"{len(expected)} selected members missing from the index")
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    print(
        f"verify_summary samples={len(rows)} archives={len(sources)} trajectories={len(seen_traj)} "
        f"values={len(rows) * FLOW_VALUES} bytes={total_bytes}"
    )


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sources-from-tree")
    s.add_argument("--tree", required=True)
    s.set_defaults(func=cmd_sources_from_tree)

    s = sub.add_parser("check-repo")
    s.add_argument("--repo-json", required=True)
    s.add_argument("--tree-json", required=True)
    s.add_argument("--sources", required=True)
    s.set_defaults(func=cmd_check_repo)

    s = sub.add_parser("check-license-page")
    s.add_argument("--page", required=True)
    s.set_defaults(func=cmd_check_license_page)

    s = sub.add_parser("check-headers")
    s.add_argument("--headers", required=True)
    s.add_argument("--body", required=True)
    s.add_argument("--size", type=int, required=True)
    s.add_argument("--etag", required=True)
    s.add_argument("--start", type=int, required=True)
    s.add_argument("--end", type=int, required=True)
    s.set_defaults(func=cmd_check_headers)

    s = sub.add_parser("tail-info")
    s.add_argument("--tail", required=True)
    s.add_argument("--zip-size", type=int, required=True)
    s.set_defaults(func=cmd_tail_info)

    s = sub.add_parser("select")
    s.add_argument("--sources", required=True)
    s.add_argument("--zip-path", required=True)
    s.add_argument("--tail", required=True)
    s.add_argument("--cd", required=True)
    s.set_defaults(func=cmd_select)

    s = sub.add_parser("check-member")
    s.add_argument("--entry", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--csize", type=int, required=True)
    s.add_argument("--usize", type=int, required=True)
    s.add_argument("--crc32", required=True)
    s.set_defaults(func=cmd_check_member)

    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        s = sub.add_parser(name)
        s.add_argument("--repo-root", required=True)
        s.add_argument("--data-dir", required=True)
        s.add_argument("--sources", required=True)
        if name == "verify":
            s.add_argument("--manifest", required=True)
        s.set_defaults(func=func)

    args = parser.parse_args()
    try:
        args.func(args)
    except (RecipeError, OSError, ValueError, struct.error, zlib.error, SyntaxError) as exc:
        print(f"FATAL {args.command}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
