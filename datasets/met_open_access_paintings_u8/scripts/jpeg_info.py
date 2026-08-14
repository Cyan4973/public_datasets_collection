#!/usr/bin/env python3
"""Validate a pinned bounded 8-bit RGB JPEG and print stable source facts as TSV."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys


path = Path(sys.argv[1])
raw = path.read_bytes()
if len(raw) < 4 or raw[:2] != b"\xff\xd8" or raw[-2:] != b"\xff\xd9":
    raise SystemExit(f"not a complete JPEG: {path}")
if not 100_000 <= len(raw) <= 200_000_000:
    raise SystemExit(f"JPEG size outside bounds: {len(raw)}")

sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
position = 2
width = height = precision = components = None
while position < len(raw):
    if raw[position] != 0xFF:
        raise SystemExit(f"invalid JPEG marker alignment at byte {position}")
    while position < len(raw) and raw[position] == 0xFF:
        position += 1
    if position >= len(raw):
        break
    marker = raw[position]
    position += 1
    if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
        continue
    if marker == 0xDA:
        break
    if position + 2 > len(raw):
        raise SystemExit("truncated JPEG segment length")
    length = struct.unpack_from(">H", raw, position)[0]
    if length < 2 or position + length > len(raw):
        raise SystemExit("invalid JPEG segment length")
    if marker in sof_markers:
        if length < 8:
            raise SystemExit("short JPEG SOF segment")
        precision = raw[position + 2]
        height, width = struct.unpack_from(">HH", raw, position + 3)
        components = raw[position + 7]
        break
    position += length

if None in (width, height, precision, components):
    raise SystemExit("JPEG has no supported SOF marker")
if precision != 8 or components != 3:
    raise SystemExit(f"expected 8-bit three-component JPEG, got precision={precision} components={components}")
pixel_count = width * height
if not 1_000_000 <= pixel_count <= 100_000_000:
    raise SystemExit(f"JPEG pixel count outside bounds: {width}x{height}={pixel_count}")

sha256 = hashlib.sha256(raw).hexdigest()
print(f"{width}\t{height}\t{precision}\t{components}\t{len(raw)}\t{sha256}")
