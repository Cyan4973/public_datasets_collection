#!/usr/bin/env python3
"""AhmedML boundary-VTP `pMean` recipe helper (pure standard library).

Network I/O is always done by curl in the shell scripts; this helper only
plans, parses and validates local files.

Subcommands:

  plan          print the deterministic run selection (run, repo path)
  check-meta    validate the HF revision API record, README front matter and LICENSE.txt
  pin-paths     combine paths-info JSON responses into the discovery draft TSV
  check-paths   validate paths-info responses against selection.tsv
  check-http    validate one curl --dump-header file for an exact pinned range
  parse-head    parse the VTK XML header prefix; print NumberOfPoints NumberOfPolys
  tail-end      locate the end of the last CellData base64 block from the file tail
  walk-step     confirm one CellData tag + UInt64 prefix; print the previous block end
  check-download  validate every fetched head prefix and pMean window (HTTP + content + values)
  build         emit one little-endian float32 sample per run and the sample index
  verify        independently re-derive and check the emitted output
  selftest      exercise the parser on synthetic VTP files (positive and negative cases)

VTK XML layout handled (verified on the pinned revision): byte_order
LittleEndian, header_type UInt64, format='binary' (inline base64), no
compressor; each binary DataArray body is ONE base64 stream encoding an 8-byte
little-endian UInt64 byte count followed by the raw array bytes, written on a
single line. The base64 length of an array of B payload bytes is therefore
ceil((8 + B) / 3) * 4 characters. CellData is the last section of the Piece and
holds, in order, pMean, static(p)_coeffMean, yPlusMean (1 component each) and
wallShearStressMean (3 components), one tuple per polygon.
"""
from __future__ import annotations

import argparse
import array
import base64
import binascii
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "ahmedml_cfd_surface_mean_pressure_f32"
SERIES_ID = "ahmedml_boundary_pmean_f32"
REPO = "neashton/ahmedml"
REVISION = "02688c727cdb8dc8678e28abc6bbbb7e93c5fa15"
LICENSE_SHA256 = "28a9529c7d0bb4dc51f4bf5c116a3d16ef247a052f7591466768ddf563fd1cf5"

RUN_FIRST, RUN_LAST, RUN_STRIDE = 1, 500, 10  # runs 1, 11, 21, ..., 491
HEAD_BYTES = 2048
TAIL_BYTES = 1024
STEP_PRE = 256  # bytes before a base64 start fetched to read its opening tag
STEP_POST = 16  # first 16 base64 chars decode to the UInt64 prefix + 1 value
WINDOW_PRE = 256  # pMean window: bytes kept before the pMean base64 start
WINDOW_POST = 128  # pMean window: bytes kept after the pMean base64 end
CELLDATA_ORDER = [("pMean", 1), ("static(p)_coeffMean", 1), ("yPlusMean", 1), ("wallShearStressMean", 3)]
TARGET = "pMean"
NEXT_AFTER_TARGET = "static(p)_coeffMean"
# Decode-garbage guard, not a physics filter: kinematic pressure p/rho in
# m^2/s^2 for a ~1 m/s reference flow (Cp = 2 * pMean) stays within a few
# units; byte garbage read as float32 has wild exponents.
VALUE_GUARD = 10.0
MIN_POLYS, MAX_POLYS = 100_000, 10_000_000

SELECTION_COLUMNS = [
    "run",
    "path",
    "size_bytes",
    "lfs_sha256",
    "xet_hash",
    "number_of_points",
    "number_of_polys",
    "pmean_b64_start",
    "pmean_b64_end",
]
DRAFT_COLUMNS = SELECTION_COLUMNS[:5]
B64_RE = re.compile(rb"[A-Za-z0-9+/]*={0,2}")


class RecipeError(Exception):
    pass


def fail(message: str) -> None:
    raise RecipeError(message)


# ---------------------------------------------------------------------------
# Selection


def planned_runs() -> list[int]:
    return list(range(RUN_FIRST, RUN_LAST + 1, RUN_STRIDE))


def repo_path(run: int) -> str:
    return f"run_{run}/boundary_{run}.vtp"


def read_tsv(path: Path, columns: list[str]) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != columns:
        fail(f"{path}: bad header (want {columns})")
    rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(columns):
            fail(f"{path}: malformed row {line!r}")
        row = dict(zip(columns, parts))
        for key in columns:
            if key not in ("path", "lfs_sha256", "xet_hash"):
                row[key] = int(row[key])
        rows.append(row)
    if [r["run"] for r in rows] != planned_runs() or any(r["path"] != repo_path(r["run"]) for r in rows):
        fail(f"{path} does not match the deterministic run rule range({RUN_FIRST}, {RUN_LAST + 1}, {RUN_STRIDE})")
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{64}", row["lfs_sha256"]) or not re.fullmatch(r"[0-9a-f]{64}", row["xet_hash"]):
            fail(f"{row['path']}: malformed pinned hashes")
    return rows


def read_selection(path: Path) -> list[dict]:
    rows = read_tsv(path, SELECTION_COLUMNS)
    for row in rows:
        n = row["number_of_polys"]
        if not MIN_POLYS <= n <= MAX_POLYS:
            fail(f"{row['path']}: implausible NumberOfPolys {n}")
        if row["pmean_b64_end"] - row["pmean_b64_start"] != b64_len(4 * n):
            fail(f"{row['path']}: pinned pMean range length disagrees with NumberOfPolys")
        if row["pmean_b64_start"] < HEAD_BYTES or row["pmean_b64_end"] + WINDOW_POST > row["size_bytes"]:
            fail(f"{row['path']}: pinned pMean range outside the file")
    return rows


def window_bounds(row: dict) -> tuple[int, int]:
    """Inclusive byte range of the stored pMean window."""
    return row["pmean_b64_start"] - WINDOW_PRE, row["pmean_b64_end"] + WINDOW_POST - 1


def load_paths_info(files: list[Path]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            fail(f"{file}: paths-info response is not a list")
        for item in data:
            if isinstance(item, dict) and item.get("type") == "file":
                entries[str(item.get("path"))] = item
    return entries


# ---------------------------------------------------------------------------
# VTK XML pieces


def b64_len(payload_bytes: int) -> int:
    return (8 + payload_bytes + 2) // 3 * 4


def text(data: bytes) -> str:
    return data.decode("latin-1")


def parse_head(data: bytes) -> dict:
    t = text(data)
    if not t.startswith("<?xml"):
        fail("head prefix is not an XML document")
    vtk = re.search(r"<VTKFile\b([^>]*)>", t)
    if not vtk:
        fail("no <VTKFile> tag in head prefix")
    attrs = dict(re.findall(r"(\w+)='([^']*)'", vtk.group(1)))
    want = {"type": "PolyData", "byte_order": "LittleEndian", "header_type": "UInt64"}
    for key, value in want.items():
        if attrs.get(key) != value:
            fail(f"VTKFile {key}={attrs.get(key)!r}, expected {value!r}")
    if "compressor" in attrs:
        fail(f"VTKFile declares compressor {attrs['compressor']!r}; only uncompressed inline base64 is handled")
    if "<AppendedData" in t or "format='appended'" in t or "format='raw'" in t:
        fail("head prefix declares appended/raw data; only inline base64 is handled")
    piece = re.search(r"<Piece NumberOfPoints='(\d+)' NumberOfPolys='(\d+)'>", t)
    if not piece:
        fail("no <Piece NumberOfPoints=.. NumberOfPolys=..> tag in head prefix")
    if not re.search(r"<DataArray type='Float32' Name='Points' NumberOfComponents='3' format='binary'>", t):
        fail("Points array is not inline-base64 Float32 x3")
    comment = re.search(r"<!--\s*patch='([^']*)' time='([^']*)' index='(\d+)'\s*-->", t)
    return {
        "number_of_points": int(piece.group(1)),
        "number_of_polys": int(piece.group(2)),
        "patch": comment.group(1) if comment else None,
        "time": comment.group(2) if comment else None,
    }


TAIL_SUFFIX_RE = re.compile(r"\s*</DataArray>\s*</CellData>\s*</Piece>\s*</PolyData>\s*</VTKFile>\s*\Z")


def tail_end(tail: bytes, tail_start: int, size: int) -> int:
    if tail_start + len(tail) != size:
        fail(f"tail does not reach end of file: start={tail_start} len={len(tail)} size={size}")
    t = text(tail)
    match = TAIL_SUFFIX_RE.search(t)
    if not match:
        fail("file tail is not '</DataArray></CellData></Piece></PolyData></VTKFile>'")
    if not re.fullmatch(r"[A-Za-z0-9+/=]{16}", t[match.start() - 16 : match.start()]):
        fail("last CellData block does not end in base64 on a single line")
    return tail_start + match.start()


def open_tag_re(name: str, ncomp: int) -> re.Pattern:
    comps = f" NumberOfComponents='{ncomp}'" if ncomp > 1 else "(?: NumberOfComponents='1')?"
    return re.compile(r"<DataArray type='Float32' Name='" + re.escape(name) + "'" + comps + r" format='binary'>[ \t]*\r?\n[ \t]*\Z")


def decode_prefix(chars: bytes) -> tuple[int, float]:
    try:
        raw = base64.b64decode(chars[:16], validate=True)
    except (binascii.Error, ValueError) as exc:
        fail(f"base64 prefix does not decode: {exc}")
    return struct.unpack_from("<Q", raw, 0)[0], struct.unpack_from("<f", raw, 8)[0]


def walk_step(window: bytes, window_start: int, b64_start: int, name: str, ncomp: int, n_polys: int) -> int:
    """Confirm that the base64 block of array `name` starts at absolute offset
    b64_start; return the absolute end offset of the preceding base64 block
    (or of the Polys section's last block when `name` is the first CellData
    array)."""
    rel = b64_start - window_start
    if rel <= 0 or rel + STEP_POST > len(window):
        fail(f"{name}: window [{window_start}, +{len(window)}) does not straddle {b64_start}")
    before = text(window[:rel])
    tag = open_tag_re(name, ncomp).search(before)
    if not tag:
        fail(f"{name}: opening tag not found right before offset {b64_start}: {before[-160:]!r}")
    prefix, first = decode_prefix(window[rel : rel + STEP_POST])
    if prefix != 4 * ncomp * n_polys:
        fail(f"{name}: UInt64 prefix {prefix} != 4*{ncomp}*{n_polys}")
    if not math.isfinite(first):
        fail(f"{name}: first value is not finite")
    head = before[: tag.start()]
    if name == CELLDATA_ORDER[0][0]:
        if not re.search(r"</DataArray>\s*</Polys>\s*<CellData>\s*\Z", head):
            fail(f"{name}: not the first CellData array after </Polys>: {head[-120:]!r}")
    else:
        if not re.search(r"</DataArray>\s*\Z", head):
            fail(f"{name}: previous CellData array does not close right before the tag")
    close = head.rfind("</DataArray>")
    k = close
    while k > 0 and head[k - 1] in " \t\r\n":
        k -= 1
    if k < 16 or not re.fullmatch(r"[A-Za-z0-9+/=]{16}", head[k - 16 : k]):
        fail(f"{name}: preceding block does not end in base64 within the window")
    return window_start + k


def check_window(window: bytes, n_polys: int, label: str) -> bytes:
    """Validate one stored pMean window (offset-based path used by build) and
    return the raw little-endian float32 payload."""
    length = b64_len(4 * n_polys)
    if len(window) != WINDOW_PRE + length + WINDOW_POST:
        fail(f"{label}: window is {len(window)} bytes, expected {WINDOW_PRE + length + WINDOW_POST}")
    pre = text(window[:WINDOW_PRE])
    chars = window[WINDOW_PRE : WINDOW_PRE + length]
    post = text(window[WINDOW_PRE + length :])
    if not re.search(r"</Polys>\s*<CellData>\s*<DataArray type='Float32' Name='pMean' format='binary'>[ \t]*\r?\n[ \t]*\Z", pre):
        fail(f"{label}: pMean opening tag (first CellData array) not found right before the pinned start")
    if not re.match(r"[ \t]*\r?\n[ \t]*</DataArray>\s*<DataArray type='Float32' Name='static\(p\)_coeffMean' format='binary'>", post):
        fail(f"{label}: pMean block is not closed and followed by static(p)_coeffMean at the pinned end")
    if not B64_RE.fullmatch(chars):
        fail(f"{label}: pinned pMean block is not one unbroken base64 run")
    try:
        raw = base64.b64decode(chars, validate=True)
    except (binascii.Error, ValueError) as exc:
        fail(f"{label}: base64 decode failed: {exc}")
    if len(raw) != 8 + 4 * n_polys:
        fail(f"{label}: decoded {len(raw)} bytes, expected {8 + 4 * n_polys}")
    prefix = struct.unpack_from("<Q", raw, 0)[0]
    if prefix != 4 * n_polys:
        fail(f"{label}: UInt64 byte-count prefix {prefix} != 4*NumberOfPolys {4 * n_polys}")
    return raw[8:]


def locate_by_tag(window: bytes, n_polys: int, label: str) -> bytes:
    """Second, offset-free decoder used by verify: find the pMean tag by text
    search, take everything up to the next '<', strip whitespace, decode."""
    t = text(window)
    tags = list(re.finditer(r"<DataArray\b([^>]*)>", t))
    pm = [m for m in tags if "Name='pMean'" in m.group(1)]
    if len(pm) != 1:
        fail(f"{label}: expected one pMean tag in window, found {len(pm)}")
    attrs = dict(re.findall(r"(\w+)='([^']*)'", pm[0].group(1)))
    if attrs.get("type") != "Float32" or attrs.get("format") != "binary" or attrs.get("NumberOfComponents", "1") != "1":
        fail(f"{label}: pMean tag attributes {attrs}")
    body_end = t.index("<", pm[0].end())
    body = "".join(t[pm[0].end() : body_end].split())
    raw = base64.b64decode(body, validate=True)
    (count,) = struct.unpack_from("<Q", raw, 0)
    if count != 4 * n_polys or len(raw) != 8 + count:
        fail(f"{label}: tag-located block holds {len(raw) - 8} bytes with prefix {count}, expected {4 * n_polys}")
    return raw[8:]


def value_stats(payload: bytes, label: str) -> dict:
    n = len(payload) // 4
    values = struct.unpack(f"<{n}f", payload)
    bad = sum(1 for v in values if not math.isfinite(v))
    if bad:
        fail(f"{label}: {bad} non-finite pMean values")
    lo, hi = min(values), max(values)
    if lo == hi:
        fail(f"{label}: constant pMean field ({lo})")
    if lo < -VALUE_GUARD or hi > VALUE_GUARD:
        fail(f"{label}: pMean range {lo}..{hi} outside the +/-{VALUE_GUARD} decode-garbage guard")
    if not (lo < 0.0 < hi):
        fail(f"{label}: pMean range {lo}..{hi} lacks both suction and stagnation regions")
    return {"min": lo, "max": hi, "mean": math.fsum(values) / n, "distinct": len(set(values)), "count": n}


# ---------------------------------------------------------------------------
# HTTP


def parse_http(path: Path) -> tuple[dict, list[dict]]:
    raw = path.read_text(encoding="iso-8859-1")
    blocks = []
    for chunk in re.split(r"(?=^HTTP/)", raw, flags=re.M):
        if not chunk.strip():
            continue
        first, *rest = chunk.strip().splitlines()
        match = re.match(r"HTTP/\S+\s+(\d+)", first)
        if not match:
            continue
        headers = {}
        for line in rest:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        blocks.append({"status": int(match.group(1)), "reason": first, "headers": headers})
    blocks = [b for b in blocks if "connection established" not in b["reason"].lower()]
    if not blocks or blocks[-1]["status"] != 206:
        fail(f"{path.name}: final response is not 206 Partial Content")
    return blocks[-1], blocks


def strip_etag(value: str) -> str:
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"')


def check_http(http_path: Path, start: int, end: int, size: int, lfs: str, xet: str) -> None:
    final, blocks = parse_http(http_path)
    expected = f"bytes {start}-{end}/{size}"
    if final["headers"].get("content-range", "") != expected:
        fail(f"{http_path.name}: Content-Range {final['headers'].get('content-range')!r} != {expected!r}")
    length = final["headers"].get("content-length")
    if length is not None and int(length) != end - start + 1:
        fail(f"{http_path.name}: Content-Length {length} != {end - start + 1}")
    etag = strip_etag(final["headers"].get("etag", ""))
    if etag not in (xet, lfs):
        fail(f"{http_path.name}: CDN ETag {etag!r} matches neither the pinned xet hash nor the LFS sha256")
    linked = [strip_etag(b["headers"]["x-linked-etag"]) for b in blocks if "x-linked-etag" in b["headers"]]
    if lfs not in linked and etag != lfs:
        fail(f"{http_path.name}: no X-Linked-Etag equal to the pinned LFS sha256 {lfs}")
    for block in blocks:
        h = block["headers"]
        if "x-linked-size" in h and int(h["x-linked-size"]) != size:
            fail(f"{http_path.name}: X-Linked-Size {h['x-linked-size']} != {size}")
        if "x-repo-commit" in h and h["x-repo-commit"] != REVISION:
            fail(f"{http_path.name}: X-Repo-Commit {h['x-repo-commit']} != pinned revision")


# ---------------------------------------------------------------------------
# Commands: discovery and download validation


def cmd_plan(args) -> int:
    for run in planned_runs():
        print(f"{run}\t{repo_path(run)}")
    return 0


def cmd_check_meta(args) -> int:
    info = json.loads(Path(args.api_info).read_text(encoding="utf-8"))
    if info.get("id") != REPO or info.get("sha") != REVISION:
        fail(f"API record identity changed: id={info.get('id')!r} sha={info.get('sha')!r}")
    if info.get("gated") not in (False, None) or info.get("private") or info.get("disabled"):
        fail(f"repository access changed: gated={info.get('gated')!r} private={info.get('private')!r} disabled={info.get('disabled')!r}")
    license_id = str((info.get("cardData") or {}).get("license") or "")
    if license_id.lower() != "cc-by-sa-4.0":
        fail(f"cardData.license changed: {license_id!r}")
    readme = Path(args.readme).read_text(encoding="utf-8")
    front = re.match(r"^---\s*\n(.*?)\n---", readme, flags=re.S)
    if not front or not re.search(r"^license:\s*cc-by-sa-4\.0\s*$", front.group(1), flags=re.M):
        fail("README.md front matter no longer declares license: cc-by-sa-4.0")
    if "AhmedML" not in readme or "OpenFOAM" not in readme:
        fail("README.md no longer identifies the AhmedML OpenFOAM dataset")
    lic = Path(args.license).read_bytes()
    if hashlib.sha256(lic).hexdigest() != LICENSE_SHA256 or not lic.startswith(b"Attribution-ShareAlike 4.0 International"):
        fail("LICENSE.txt changed or is not the CC BY-SA 4.0 legal code")
    print(f"meta_validation=ok repo={REPO} sha={REVISION} license=cc-by-sa-4.0 gated=false")
    return 0


def cmd_pin_paths(args) -> int:
    entries = load_paths_info([Path(p) for p in args.paths_info])
    lines = ["\t".join(DRAFT_COLUMNS)]
    for run in planned_runs():
        item = entries.get(repo_path(run))
        if item is None:
            fail(f"{repo_path(run)} absent at revision {REVISION}")
        lfs = item.get("lfs") or {}
        if not lfs.get("oid") or not item.get("xetHash") or int(lfs.get("size") or -1) != int(item.get("size") or -2):
            fail(f"{repo_path(run)}: paths-info lacks LFS/xet identity")
        lines.append(f"{run}\t{repo_path(run)}\t{item['size']}\t{lfs['oid']}\t{item['xetHash']}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pinned {len(lines) - 1} paths")
    return 0


def cmd_check_paths(args) -> int:
    rows = read_selection(Path(args.selection))
    entries = load_paths_info([Path(p) for p in args.paths_info])
    for row in rows:
        item = entries.get(row["path"])
        if item is None:
            fail(f"{row['path']}: absent from paths-info at revision {REVISION}")
        lfs = item.get("lfs") or {}
        if int(item.get("size") or 0) != row["size_bytes"] or lfs.get("oid") != row["lfs_sha256"] or item.get("xetHash") != row["xet_hash"]:
            fail(f"{row['path']}: upstream metadata differs from pinned selection")
    print(f"paths_validation=ok files={len(rows)}")
    return 0


def cmd_check_http(args) -> int:
    check_http(Path(args.http), args.start, args.end, args.size, args.lfs, args.xet)
    return 0


def cmd_parse_head(args) -> int:
    info = parse_head(Path(args.head).read_bytes())
    print(f"{info['number_of_points']} {info['number_of_polys']}")
    return 0


def cmd_tail_end(args) -> int:
    print(tail_end(Path(args.tail).read_bytes(), args.tail_start, args.size))
    return 0


def cmd_walk_step(args) -> int:
    print(walk_step(Path(args.window).read_bytes(), args.window_start, args.b64_start, args.name, args.ncomp, args.polys))
    return 0


def run_paths(download_dir: Path, run: int) -> dict[str, Path]:
    stem = f"run_{run:03d}"
    return {
        "head": download_dir / "heads" / f"{stem}.head.bin",
        "head_http": download_dir / "heads" / f"{stem}.head.bin.http",
        "window": download_dir / "pmean" / f"{stem}.pmean_window.bin",
        "window_http": download_dir / "pmean" / f"{stem}.pmean_window.bin.http",
    }


def check_local_head(paths: dict, row: dict) -> dict:
    head = paths["head"].read_bytes()
    if len(head) != HEAD_BYTES:
        fail(f"{paths['head'].name}: {len(head)} bytes, expected {HEAD_BYTES}")
    info = parse_head(head)
    if info["number_of_polys"] != row["number_of_polys"] or info["number_of_points"] != row["number_of_points"]:
        fail(f"{row['path']}: header counts {info['number_of_points']}/{info['number_of_polys']} != pinned {row['number_of_points']}/{row['number_of_polys']}")
    return info


def cmd_check_download(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    digests = {}
    for row in rows:
        paths = run_paths(download_dir, row["run"])
        start, end = window_bounds(row)
        check_http(paths["head_http"], 0, HEAD_BYTES - 1, row["size_bytes"], row["lfs_sha256"], row["xet_hash"])
        check_http(paths["window_http"], start, end, row["size_bytes"], row["lfs_sha256"], row["xet_hash"])
        check_local_head(paths, row)
        payload = check_window(paths["window"].read_bytes(), row["number_of_polys"], row["path"])
        stats = value_stats(payload, row["path"])
        digest = hashlib.sha256(payload).hexdigest()
        if digest in digests:
            fail(f"{row['path']}: pMean payload identical to {digests[digest]}")
        digests[digest] = row["path"]
        print(f"ok {row['path']} polys={row['number_of_polys']} range={stats['min']:.6g}..{stats['max']:.6g} distinct={stats['distinct']}")
    print(f"download_validation=ok runs={len(rows)}")
    return 0


# ---------------------------------------------------------------------------
# Commands: build and verify


def sample_relpath(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/run_{row['run']:03d}.pMean.f32le.bin"


def index_row(row: dict, payload: bytes, stats: dict, info: dict) -> dict:
    start, end = window_bounds(row)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_relpath(row),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": len(payload),
        "value_count": len(payload) // 4,
        "shape": [len(payload) // 4],
        "axes": ["boundary_polygon"],
        "run": row["run"],
        "number_of_polys": row["number_of_polys"],
        "number_of_points": row["number_of_points"],
        "averaging_end_time": info["time"],
        "source_repo": f"https://huggingface.co/datasets/{REPO}",
        "source_revision": REVISION,
        "source_path": row["path"],
        "source_lfs_sha256": row["lfs_sha256"],
        "source_field": "CellData/DataArray[Name='pMean']",
        "source_b64_byte_range": [row["pmean_b64_start"], row["pmean_b64_end"] - 1],
        "source_window_byte_range": [start, end],
        "min": stats["min"],
        "max": stats["max"],
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def derive(download_dir: Path, row: dict) -> tuple[bytes, dict, dict]:
    paths = run_paths(download_dir, row["run"])
    info = check_local_head(paths, row)
    payload = check_window(paths["window"].read_bytes(), row["number_of_polys"], row["path"])
    return payload, value_stats(payload, row["path"]), info


def cmd_build(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*"):
        stale.unlink()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    out_rows = []
    for row in rows:
        payload, stats, info = derive(download_dir, row)
        target = data_root / sample_relpath(row)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        out_rows.append(index_row(row, payload, stats, info))
        print(f"sample {target.name} values={stats['count']} range={stats['min']:.6g}..{stats['max']:.6g} distinct={stats['distinct']}")
    index_tmp = index_path.with_suffix(".jsonl.part")
    index_tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out_rows), encoding="utf-8")
    index_tmp.replace(index_path)
    stats_all = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(out_rows),
        "values": sum(r["value_count"] for r in out_rows),
        "bytes": sum(r["sample_size_bytes"] for r in out_rows),
        "min_value_count": min(r["value_count"] for r in out_rows),
        "max_value_count": max(r["value_count"] for r in out_rows),
        "min": min(r["min"] for r in out_rows),
        "max": max(r["max"] for r in out_rows),
        "runs": [r["run"] for r in out_rows],
    }
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats_all, indent=1) + "\n", encoding="utf-8")
    print(f"build ok samples={stats_all['samples']} values={stats_all['values']} bytes={stats_all['bytes']} range={stats_all['min']}..{stats_all['max']}")
    return 0


def cmd_verify(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary" or len(manifest.get("series", [])) != 1:
        fail("manifest must declare exactly one series, the primary " + SERIES_ID)
    series = series[0]
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != len(rows):
        fail(f"index has {len(index_rows)} rows, selection has {len(rows)}")
    digests: set[str] = set()
    expected_files: set[str] = set()
    total_bytes = 0
    for row, entry in zip(rows, index_rows):
        paths = run_paths(download_dir, row["run"])
        info = check_local_head(paths, row)
        window = paths["window"].read_bytes()
        # Independent decoder: tag search + whitespace strip, no pinned offsets.
        payload = locate_by_tag(window, row["number_of_polys"], row["path"])
        if payload != check_window(window, row["number_of_polys"], row["path"]):
            fail(f"{row['path']}: offset-based and tag-based decoders disagree")
        sample = data_root / entry.get("sample_path", "")
        if entry.get("sample_path") != sample_relpath(row) or not sample.is_file():
            fail(f"{row['path']}: index sample_path {entry.get('sample_path')!r} missing or unexpected")
        on_disk = sample.read_bytes()
        if on_disk != payload:
            fail(f"{entry['sample_path']}: bytes differ from independent re-derivation")
        # Stats from the stored little-endian float32 bytes, with array-based
        # unpacking as a second conversion path.
        stored = array.array("f")
        stored.frombytes(on_disk)
        if sys.byteorder != "little":
            stored.byteswap()
        if any(not math.isfinite(v) for v in stored):
            fail(f"{entry['sample_path']}: non-finite stored values")
        lo, hi = min(stored), max(stored)
        if lo == hi:
            fail(f"{entry['sample_path']}: constant sample")
        distinct = len(set(stored))
        if distinct < len(stored) // 20:
            fail(f"{entry['sample_path']}: degenerate field ({distinct} distinct of {len(stored)})")
        expected = index_row(row, payload, {"min": lo, "max": hi}, info)
        if entry != expected:
            diff = sorted(k for k in set(entry) | set(expected) if entry.get(k) != expected.get(k))
            fail(f"index row for {row['path']} differs from re-derivation in {diff}")
        if entry["sha256"] in digests:
            fail(f"{entry['sample_path']}: duplicate sample payload")
        digests.add(entry["sha256"])
        expected_files.add(sample.name)
        total_bytes += len(on_disk)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    present = {p.name for p in series_dir.iterdir()}
    if present != expected_files:
        fail(f"sample directory mismatch: extra {sorted(present - expected_files)[:5]} missing {sorted(expected_files - present)[:5]}")
    other = [p.name for p in (data_root / "samples" / DATASET_ID).iterdir() if p.name != SERIES_ID]
    if other:
        fail(f"unexpected entries under samples/{DATASET_ID}: {other}")
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} != realized {len(rows)}/{total_bytes}")
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed the 1 GB cap")
    print(f"verify ok samples={len(rows)} bytes={total_bytes} distinct_payloads={len(digests)}")
    return 0


# ---------------------------------------------------------------------------
# Self-test on synthetic VTP files


def _b64_block(payload: bytes) -> bytes:
    return base64.b64encode(struct.pack("<Q", len(payload)) + payload)


def _synthetic_vtp(n_points: int, n_polys: int, arrays: list[tuple[str, int, bytes]], *, wrap: bool = False, compressor: bool = False) -> bytes:
    def block(payload: bytes) -> bytes:
        enc = _b64_block(payload)
        if wrap:
            enc = b"\n".join(enc[i : i + 76] for i in range(0, len(enc), 76))
        return enc

    comp = " compressor='vtkZLibDataCompressor'" if compressor else ""
    pts = struct.pack(f"<{3 * n_points}f", *[0.001 * i for i in range(3 * n_points)])
    conn = struct.pack(f"<{4 * n_polys}i", *[i % n_points for i in range(4 * n_polys)])
    offs = struct.pack(f"<{n_polys}i", *[4 * (i + 1) for i in range(n_polys)])
    out = [
        b"<?xml version='1.0'?>\n<!-- patch='ahmed' time='79.9998' index='133333' -->\n",
        f"<VTKFile type='PolyData' version='0.1' byte_order='LittleEndian' header_type='UInt64'{comp}>\n".encode(),
        b"  <PolyData>\n    <FieldData>\n      <DataArray type='Float32' Name='TimeValue' NumberOfTuples='1' format='binary'>\n",
        block(struct.pack("<f", 79.9998)), b"\n      </DataArray>\n    </FieldData>\n",
        f"    <Piece NumberOfPoints='{n_points}' NumberOfPolys='{n_polys}'>\n".encode(),
        b"      <Points>\n        <DataArray type='Float32' Name='Points' NumberOfComponents='3' format='binary'>\n",
        block(pts), b"\n        </DataArray>\n      </Points>\n      <Polys>\n",
        b"        <DataArray type='Int32' Name='connectivity' format='binary'>\n", block(conn), b"\n        </DataArray>\n",
        b"        <DataArray type='Int32' Name='offsets' format='binary'>\n", block(offs), b"\n        </DataArray>\n",
        b"      </Polys>\n      <CellData>\n",
    ]
    for name, ncomp, payload in arrays:
        comps = f" NumberOfComponents='{ncomp}'" if ncomp > 1 else ""
        out += [f"        <DataArray type='Float32' Name='{name}'{comps} format='binary'>\n".encode(), block(payload), b"\n        </DataArray>\n"]
    out.append(b"      </CellData>\n    </Piece>\n  </PolyData>\n</VTKFile>\n")
    return b"".join(out)


def _fields(n_polys: int, seed: int) -> list[tuple[str, int, bytes]]:
    p = [math.sin(0.37 * i + seed) * 0.4 - 0.1 for i in range(n_polys)]
    return [
        ("pMean", 1, struct.pack(f"<{n_polys}f", *p)),
        ("static(p)_coeffMean", 1, struct.pack(f"<{n_polys}f", *[2.0 * v for v in p])),
        ("yPlusMean", 1, struct.pack(f"<{n_polys}f", *[30.0 + (i % 17) for i in range(n_polys)])),
        ("wallShearStressMean", 3, struct.pack(f"<{3 * n_polys}f", *[1e-3 * math.cos(i) for i in range(3 * n_polys)])),
    ]


def _discover(vtp: bytes) -> tuple[dict, int, int]:
    """Replay discover.sh's request sequence against an in-memory file."""
    size = len(vtp)
    info = parse_head(vtp[:HEAD_BYTES])
    n = info["number_of_polys"]
    tail_start = max(0, size - TAIL_BYTES)
    end = tail_end(vtp[tail_start:], tail_start, size)
    start = end
    for name, ncomp in reversed(CELLDATA_ORDER):
        start = end - b64_len(4 * ncomp * n)
        w0 = start - STEP_PRE
        prev_end = walk_step(vtp[w0 : start + STEP_POST], w0, start, name, ncomp, n)
        if name == TARGET:
            return info, start, end
        end = prev_end
    fail("target not reached")
    raise AssertionError


def _expect_failure(label: str, func) -> None:
    try:
        func()
    except RecipeError:
        return
    raise AssertionError(f"selftest: {label} was accepted but must fail")


def cmd_selftest(args) -> int:
    checked = 0
    for n_polys in (3001, 3002, 3003, 4000, 5555):  # covers all three base64 padding residues
        n_points = n_polys + 7
        fields = _fields(n_polys, n_polys)
        vtp = _synthetic_vtp(n_points, n_polys, fields)
        info, start, end = _discover(vtp)
        assert info["number_of_polys"] == n_polys and info["number_of_points"] == n_points
        assert end - start == b64_len(4 * n_polys)
        window = vtp[start - WINDOW_PRE : end + WINDOW_POST]
        payload = check_window(window, n_polys, "synthetic")
        assert payload == fields[0][2], "offset decoder returned wrong bytes"
        assert locate_by_tag(window, n_polys, "synthetic") == payload, "tag decoder disagrees"
        stats = value_stats(payload, "synthetic")
        assert stats["count"] == n_polys and stats["min"] < 0 < stats["max"]
        checked += 1
        # Negative cases.
        bad = bytearray(window)
        bad[WINDOW_PRE : WINDOW_PRE + 12] = base64.b64encode(struct.pack("<Q", 4 * n_polys + 4) + b"\0")[:12]
        _expect_failure("wrong UInt64 prefix", lambda: check_window(bytes(bad), n_polys, "bad"))
        _expect_failure("off-by-4 window", lambda: check_window(vtp[start - WINDOW_PRE + 4 : end + WINDOW_POST + 4], n_polys, "bad"))
        _expect_failure("truncated window", lambda: check_window(window[:-1], n_polys, "bad"))
        _expect_failure("wrong polygon count", lambda: check_window(window, n_polys + 1, "bad"))
        reordered = _synthetic_vtp(n_points, n_polys, [fields[2], fields[0], fields[1], fields[3]])
        _expect_failure("reordered CellData", lambda: _discover(reordered))
        wrapped = _synthetic_vtp(n_points, n_polys, fields, wrap=True)
        _expect_failure("line-wrapped base64", lambda: _discover(wrapped))
        _expect_failure("compressed VTK", lambda: parse_head(_synthetic_vtp(n_points, n_polys, fields, compressor=True)[:HEAD_BYTES]))
        nan_fields = list(fields)
        nan_payload = bytearray(fields[0][2])
        nan_payload[40:44] = struct.pack("<f", float("nan"))
        nan_fields[0] = ("pMean", 1, bytes(nan_payload))
        nan_vtp = _synthetic_vtp(n_points, n_polys, nan_fields)
        _, s2, e2 = _discover(nan_vtp)
        _expect_failure("NaN value", lambda: value_stats(check_window(nan_vtp[s2 - WINDOW_PRE : e2 + WINDOW_POST], n_polys, "nan"), "nan"))
        const = [("pMean", 1, struct.pack("<f", -0.25) * n_polys)] + fields[1:]
        const_vtp = _synthetic_vtp(n_points, n_polys, const)
        _, s3, e3 = _discover(const_vtp)
        _expect_failure("constant field", lambda: value_stats(check_window(const_vtp[s3 - WINDOW_PRE : e3 + WINDOW_POST], n_polys, "const"), "const"))
        huge = [("pMean", 1, struct.pack(f"<{n_polys}f", *[1e20 * (i % 3 - 1) for i in range(n_polys)]))] + fields[1:]
        huge_vtp = _synthetic_vtp(n_points, n_polys, huge)
        _, s4, e4 = _discover(huge_vtp)
        _expect_failure("garbage-range field", lambda: value_stats(check_window(huge_vtp[s4 - WINDOW_PRE : e4 + WINDOW_POST], n_polys, "huge"), "huge"))
    print(f"selftest ok synthetic_files={checked} (offset decoder, tag decoder, walk, 10 negative cases each)")
    return 0


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    p = sub.add_parser("check-meta")
    p.add_argument("--api-info", required=True)
    p.add_argument("--readme", required=True)
    p.add_argument("--license", required=True)
    p.set_defaults(func=cmd_check_meta)
    p = sub.add_parser("pin-paths")
    p.add_argument("--out", required=True)
    p.add_argument("paths_info", nargs="+")
    p.set_defaults(func=cmd_pin_paths)
    p = sub.add_parser("check-paths")
    p.add_argument("--selection", required=True)
    p.add_argument("paths_info", nargs="+")
    p.set_defaults(func=cmd_check_paths)
    p = sub.add_parser("check-http")
    p.add_argument("--http", required=True)
    for key in ("start", "end", "size"):
        p.add_argument(f"--{key}", type=int, required=True)
    p.add_argument("--lfs", required=True)
    p.add_argument("--xet", required=True)
    p.set_defaults(func=cmd_check_http)
    p = sub.add_parser("parse-head")
    p.add_argument("--head", required=True)
    p.set_defaults(func=cmd_parse_head)
    p = sub.add_parser("tail-end")
    p.add_argument("--tail", required=True)
    p.add_argument("--tail-start", type=int, required=True)
    p.add_argument("--size", type=int, required=True)
    p.set_defaults(func=cmd_tail_end)
    p = sub.add_parser("walk-step")
    p.add_argument("--window", required=True)
    p.add_argument("--window-start", type=int, required=True)
    p.add_argument("--b64-start", type=int, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--ncomp", type=int, required=True)
    p.add_argument("--polys", type=int, required=True)
    p.set_defaults(func=cmd_walk_step)
    for name, func in (("check-download", cmd_check_download), ("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--selection", required=True)
        p.add_argument("--download-dir", required=True)
        if name != "check-download":
            p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
        p.set_defaults(func=func)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    args = parser.parse_args()
    try:
        return args.func(args)
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
