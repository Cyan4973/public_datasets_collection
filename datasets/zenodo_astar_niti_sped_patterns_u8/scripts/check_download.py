#!/usr/bin/env python3
"""Semantic validators used by download.sh (pure standard library, no network).

Subcommands:
  record  <record.json> <record_id> <title_needle> <spec>...
      Zenodo record id, title, license (cc-by-4.0), open access, and the size
      and MD5 of every pinned blockfile. <spec> is "url_key:size:md5".
  header  <payload> <headers|-> <size> <sha256> <dp_offset> <nx> <ny> <name>
      206 + exact Content-Range 0-4095/<size>, exact length, pinned SHA-256,
      and the parsed IMGBLO header tuple (magic 258, VBF offset 4096, pinned
      DP offset, DP_SZ 144, NX, NY, VBF fills the gap to the DP offset, and
      DP offset + NX*NY*(6 + 144*144) == file size).
  row     <payload> <headers|-> <start> <end> <size> <nx> <row> <pins|-> <name>
      206 + exact Content-Range, exact length NX*(6+144*144), every frame
      prefix is u16 0x55AA followed by u32 frame index row*NX+col, no constant
      pattern, and the pinned per-row SHA-256 when a pin file is given.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import sys
import urllib.parse

DP_SZ = 144
NPIX = DP_SZ * DP_SZ
FRAME = 6 + NPIX
HEADER_BYTES = 4096
HEADER_FMT = "<6sHIIIHHHHHddIHId"


def die(message: str) -> None:
    raise SystemExit(f"VALIDATION FAIL: {message}")


def check_http(headers: str, start: int, end: int, total: int, name: str) -> None:
    if headers in ("", "-"):
        return
    text = open(headers, encoding="iso-8859-1").read()
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    final = blocks[-1] if blocks else ""
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    crange = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not status or status.group(1) != "206" or not crange:
        die(f"{name}: server did not answer with 206 + Content-Range")
    got = tuple(int(v) for v in crange.groups())
    if got != (start, end, total):
        die(f"{name}: Content-Range {got} != {(start, end, total)}")


def cmd_record(args: list[str]) -> None:
    path, record_id, needle, specs = args[0], int(args[1]), args[2], args[3:]
    record = json.loads(open(path, encoding="utf-8").read())
    if int(record.get("id") or 0) != record_id:
        die(f"unexpected Zenodo record id {record.get('id')!r} != {record_id}")
    meta = record.get("metadata") or {}
    title = str(meta.get("title") or "")
    if needle.lower() not in title.lower():
        die(f"record {record_id} title changed: {title!r}")
    lic = meta.get("license")
    lic_id = str((lic.get("id") if isinstance(lic, dict) else lic) or "").lower()
    if lic_id != "cc-by-4.0":
        die(f"record {record_id} license changed: {lic!r}")
    access = meta.get("access_right") or (record.get("access") or {}).get("record")
    if access not in ("open", "public"):
        die(f"record {record_id} access changed: {access!r}")
    files = {f.get("key"): f for f in record.get("files") or [] if isinstance(f, dict)}
    for spec in specs:
        url_key, size, md5 = spec.rsplit(":", 2)
        key = urllib.parse.unquote(url_key)
        item = files.get(key)
        if item is None:
            die(f"record {record_id} no longer lists {key!r}")
        if int(item.get("size") or -1) != int(size):
            die(f"{key}: size {item.get('size')!r} != pinned {size}")
        if str(item.get("checksum") or "").lower() != f"md5:{md5}":
            die(f"{key}: checksum {item.get('checksum')!r} != pinned md5:{md5}")
    print(f"record_validation=ok record={record_id} license=cc-by-4.0 access={access} files={len(specs)} title={title[:70]!r}")


def parse_header(blob: bytes) -> dict:
    fields = struct.unpack_from(HEADER_FMT, blob, 0)
    keys = ["id", "magic", "vbf_offset", "dp_offset", "flags", "dp_sz", "dp_rotation", "nx", "ny",
            "scan_rotation", "sx_nm", "sy_nm", "beam_energy_v", "sdp", "camera_length_0p1mm", "acquisition_serial_date"]
    return dict(zip(keys, fields))


def cmd_header(args: list[str]) -> None:
    payload, headers, size, sha, dp_offset, nx, ny, name = args
    size, dp_offset, nx, ny = int(size), int(dp_offset), int(nx), int(ny)
    check_http(headers, 0, HEADER_BYTES - 1, size, name)
    blob = open(payload, "rb").read()
    if len(blob) != HEADER_BYTES:
        die(f"{name}: header length {len(blob)} != {HEADER_BYTES}")
    digest = hashlib.sha256(blob).hexdigest()
    if digest != sha:
        die(f"{name}: header sha256 {digest} != pinned {sha}")
    h = parse_header(blob)
    expect = {"id": b"IMGBLO", "magic": 258, "vbf_offset": HEADER_BYTES, "dp_offset": dp_offset, "dp_sz": DP_SZ, "nx": nx, "ny": ny}
    for key, value in expect.items():
        if h[key] != value:
            die(f"{name}: header {key}={h[key]!r} != {value!r}")
    if h["vbf_offset"] + nx * ny != dp_offset:
        die(f"{name}: VBF image does not end at the DP offset")
    if dp_offset + nx * ny * FRAME != size:
        die(f"{name}: DP offset + NX*NY*{FRAME} != file size {size}")
    print(f"header_validation=ok {name} nx={nx} ny={ny} dp_offset={dp_offset} cl_0p1mm={h['camera_length_0p1mm']} sx_nm={h['sx_nm']}")


def load_pins(path: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in open(path, encoding="utf-8"):
        fields = line.split()
        if fields and not fields[0].startswith("#"):
            pins[fields[0]] = fields[-1]
    return pins


def cmd_row(args: list[str]) -> None:
    payload, headers, start, end, size, nx, row, pins_file, name = args
    start, end, size, nx, row = int(start), int(end), int(size), int(nx), int(row)
    check_http(headers, start, end, size, name)
    actual = os.path.getsize(payload)
    if actual != end - start + 1 or actual != nx * FRAME:
        die(f"{name}: payload size {actual} != {nx} * {FRAME}")
    data = open(payload, "rb").read()
    for col in range(nx):
        base = col * FRAME
        marker, index = struct.unpack_from("<HI", data, base)
        if marker != 0x55AA:
            die(f"{name}: column {col} frame marker 0x{marker:04x} != 0x55aa")
        if index != row * nx + col:
            die(f"{name}: column {col} frame index {index} != {row * nx + col}")
        pattern = data[base + 6:base + FRAME]
        if pattern.count(pattern[:1]) == NPIX:
            die(f"{name}: column {col} pattern is constant")
    digest = hashlib.sha256(data).hexdigest()
    if pins_file not in ("", "-") and os.path.isfile(pins_file):
        pins = load_pins(pins_file)
        if name not in pins:
            die(f"{name}: no pinned sha256 in {pins_file}")
        if pins[name] != digest:
            die(f"{name}: sha256 {digest} != pinned {pins[name]}")
    print(f"row_validation=ok {name} frames={nx} bytes={actual} sha256={digest}")


def main() -> int:
    if len(sys.argv) < 2:
        die("usage: check_download.py record|header|row ...")
    command, args = sys.argv[1], sys.argv[2:]
    if command == "record":
        cmd_record(args)
    elif command == "header":
        if len(args) != 8:
            die("header needs 8 arguments")
        cmd_header(args)
    elif command == "row":
        if len(args) != 9:
            die("row needs 9 arguments")
        cmd_row(args)
    else:
        die(f"unknown subcommand {command!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
