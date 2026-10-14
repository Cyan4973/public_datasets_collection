#!/usr/bin/env python3
"""Validate SNODAS SWE tar members fetched by download.sh (local files only).

Subcommands:
  header BLOCK NAME SIZE
      BLOCK is the 512-byte ustar header preceding a member. Checks the header
      checksum and that the member name and size equal the pinned values.
  txt PATH DATE
      PATH is the .txt.gz SWE header member. Checks the documented raster
      geometry, type, units and no-data value (see EXPECTED below).
  dat PATH CRC32HEX ISIZE
      PATH is the .dat.gz SWE raster member. Fully decompresses it, checks the
      gzip trailer CRC32/ISIZE equal the pinned values and the decompressed
      length equals 6935*3351*2. Prints md5 and sha256 of the member.
"""
from __future__ import annotations

import gzip
import hashlib
import struct
import sys
import zlib

COLS = 6935
ROWS = 3351
RAW_BYTES = COLS * ROWS * 2

EXPECTED = {
    "Format version": "NOHRSC GIS/RS raster file v1.1",
    "Description": "Modeled snow water equivalent, total of snow layers",
    "Data units": "Meters / 1000.000000",
    "Data type": "integer",
    "Data bytes per pixel": "2",
    "Data intercept": "0.00000000000000",
    "Data slope": "1.00000000000000",
    "No data value": "-9999.00000000000",
    "Number of columns": str(COLS),
    "Number of rows": str(ROWS),
    "Horizontal datum": "WGS84",
    "X-axis resolution": "0.00833333333333300",
    "Y-axis resolution": "0.00833333333333300",
    "Benchmark x-axis coordinate": "-124.729166666662",
    "Benchmark y-axis coordinate": "52.8708333333312",
    "Minimum y-axis coordinate": "24.9499999999990",
    "Compressed": "no",
}
# Bounding-box values drift in the 12th decimal between processing years.
APPROX = {
    "Minimum x-axis coordinate": -124.7333333333,
    "Maximum x-axis coordinate": -66.9416666667,
    "Maximum y-axis coordinate": 52.8750000000,
}


def die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def parse_txt_header(raw: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw.decode("ascii").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def check_txt_fields(fields: dict[str, str], date: str) -> None:
    for key, want in EXPECTED.items():
        if fields.get(key) != want:
            die(f"txt header {key!r}={fields.get(key)!r} expected {want!r}")
    for key, want in APPROX.items():
        if abs(float(fields.get(key, "nan")) - want) > 1e-6:
            die(f"txt header {key!r}={fields.get(key)!r} expected ~{want}")
    want_path = f"us_ssmv11034tS__T0001TTNATS{date}05HP001.dat"
    if fields.get("Data file pathname") != want_path:
        die(f"txt header data file {fields.get('Data file pathname')!r} expected {want_path!r}")
    ymd = (int(date[:4]), int(date[4:6]), int(date[6:8]))
    got = tuple(int(fields.get(k, "-1")) for k in ("Start year", "Start month", "Start day"))
    if got != ymd:
        die(f"txt header start date {got} expected {ymd}")


def cmd_header(block_path: str, name: str, size: str) -> None:
    block = open(block_path, "rb").read()
    if len(block) != 512:
        die(f"header block length {len(block)}")
    chk = int(block[148:156].split(b"\0", 1)[0].strip(), 8)
    if chk != sum(block[:148]) + 32 * 8 + sum(block[156:]):
        die("ustar header checksum mismatch")
    got_name = block[0:100].split(b"\0", 1)[0].decode("ascii")
    got_size = int(block[124:136].split(b"\0", 1)[0].strip(), 8)
    if got_name != name or got_size != int(size):
        die(f"ustar header name/size {got_name!r}/{got_size} expected {name!r}/{size}")


def cmd_txt(path: str, date: str) -> None:
    with gzip.open(path, "rb") as fh:
        raw = fh.read()
    check_txt_fields(parse_txt_header(raw), date)


def cmd_dat(path: str, crc_hex: str, isize: str) -> None:
    data = open(path, "rb").read()
    crc, size = struct.unpack("<II", data[-8:])
    if crc != int(crc_hex, 16) or size != int(isize):
        die(f"gzip trailer crc/isize {crc:08x}/{size} expected {crc_hex}/{isize}")
    raw = gzip.decompress(data)
    if len(raw) != RAW_BYTES:
        die(f"decompressed length {len(raw)} expected {RAW_BYTES}")
    if zlib.crc32(raw) != int(crc_hex, 16):
        die("decompressed CRC32 mismatch")
    print(f"md5={hashlib.md5(data).hexdigest()} sha256={hashlib.sha256(data).hexdigest()}")


def main() -> None:
    if len(sys.argv) < 2:
        die(__doc__ or "usage")
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "header" and len(args) == 3:
        cmd_header(*args)
    elif cmd == "txt" and len(args) == 2:
        cmd_txt(*args)
    elif cmd == "dat" and len(args) == 3:
        cmd_dat(*args)
    else:
        die(f"bad arguments: {sys.argv[1:]}")


if __name__ == "__main__":
    main()
