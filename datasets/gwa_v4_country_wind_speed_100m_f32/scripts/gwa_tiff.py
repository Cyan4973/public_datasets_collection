#!/usr/bin/env python3
"""Pure-stdlib reader for Global Wind Atlas v4 country GeoTIFFs.

The GWA v4 country rasters (``country_tifs_v4/{ISO3}_wind-speed_100m.tif``)
are GDAL Cloud-Optimized GeoTIFFs in BigTIFF form (little-endian, magic 43):

* IFD0 is the full-resolution grid: float32 (BitsPerSample 32,
  SampleFormat 3), one band, 512x512 tiles, Compression 50000 (Zstandard),
  Predictor 3 (TIFF floating-point predictor), GDAL_NODATA "nan".
* IFD1.. are reduced-resolution overviews (NewSubfileType 1). They are
  validated for presence and type only and never decoded.

Zstandard is decoded with the system ``zstd`` CLI (Python 3.12 has no stdlib
zstd); everything else is the standard library.

Floating-point predictor (libtiff ``fpAcc``), applied per tile row of
``tile_width`` samples:
  1. undo byte-wise horizontal differencing over the 4*tile_width bytes of
     the row (stride 1 because SamplesPerPixel is 1): b[i] = b[i] + b[i-1]
     mod 256;
  2. the row is then four byte planes of tile_width bytes each, most
     significant byte first (plane k at offset k*tile_width); sample i is
     the big-endian float32 (p0[i], p1[i], p2[i], p3[i]).
The decoder writes little-endian float32 and crops right/bottom edge tiles
to the image extent.

Usage:
    gwa_tiff.py header <file.tif>     JSON header summary (works on a prefix)
    gwa_tiff.py validate <file.tif>   recipe-level structure check (download.sh)
    gwa_tiff.py selftest              synthetic predictor-3 / BigTIFF round trip
    gwa_tiff.py overview-ranges <head.bin>           byte ranges of the smallest
                                                     overview's tiles (discover.sh)
    gwa_tiff.py overview-share <head.bin> <tile>...  valid share of that overview
"""
from __future__ import annotations

import itertools
import json
import math
import os
import re
import struct
import subprocess
import sys
from typing import BinaryIO

ZSTD_BIN = os.environ.get("ZSTD_BIN", "zstd")

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
             11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d",
            16: "Q", 17: "q", 18: "Q"}

TAG_NAMES = {
    256: "width",
    257: "height",
    258: "bits_per_sample",
    259: "compression",
    262: "photometric",
    277: "samples_per_pixel",
    284: "planar_configuration",
    317: "predictor",
    322: "tile_width",
    323: "tile_height",
    339: "sample_format",
}
DEFAULTS = {259: 1, 262: 1, 277: 1, 284: 1, 317: 1, 339: 1}

# Exact primary-IFD encoding required for this recipe (width/height vary per
# country and are checked against the pinned plan instead).
EXPECTED_ENCODING = {
    "bits_per_sample": 32,
    "compression": 50000,
    "photometric": 1,
    "samples_per_pixel": 1,
    "planar_configuration": 1,
    "predictor": 3,
    "tile_width": 512,
    "tile_height": 512,
    "sample_format": 3,
}
EXPECTED_PIXEL_SCALE = 0.0025  # degrees, WGS84 geographic grid
EXPECTED_NODATA = "nan"


class TiffError(ValueError):
    pass


# --------------------------------------------------------------------------
# BigTIFF IFD parsing (seek-based, so it also works on a header prefix)
# --------------------------------------------------------------------------

def _read_exact(fh: BinaryIO, offset: int, size: int) -> bytes:
    fh.seek(offset)
    blob = fh.read(size)
    if len(blob) != size:
        raise TiffError(f"short read at offset {offset} ({len(blob)}/{size} bytes)")
    return blob


def read_ifds(fh: BinaryIO, max_ifds: int = 32) -> list[dict[int, object]]:
    head = _read_exact(fh, 0, 16)
    if head[:4] != b"II+\x00":
        raise TiffError(f"not a little-endian BigTIFF (magic={head[:4]!r})")
    bytesize, zero, offset = struct.unpack("<HHQ", head[4:16])
    if bytesize != 8 or zero != 0:
        raise TiffError(f"unexpected BigTIFF offset size {bytesize}/{zero}")
    ifds: list[dict[int, object]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen:
            raise TiffError(f"IFD loop at offset {offset}")
        seen.add(offset)
        (count,) = struct.unpack("<Q", _read_exact(fh, offset, 8))
        if count == 0 or count > 512:
            raise TiffError(f"implausible IFD entry count {count} at {offset}")
        body = _read_exact(fh, offset + 8, 20 * count + 8)
        tags: dict[int, object] = {}
        for i in range(count):
            tag, ftype, n = struct.unpack_from("<HHQ", body, 20 * i)
            raw = body[20 * i + 12:20 * i + 20]
            size = TYPE_SIZE.get(ftype)
            if size is None:
                raise TiffError(f"unsupported field type {ftype} for tag {tag}")
            nbytes = size * n
            if nbytes <= 8:
                blob = raw[:nbytes]
            else:
                (where,) = struct.unpack("<Q", raw)
                blob = _read_exact(fh, where, nbytes)
            if ftype == 2:
                tags[tag] = blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            elif ftype in TYPE_FMT:
                tags[tag] = list(struct.unpack("<" + TYPE_FMT[ftype] * n, blob))
            else:
                tags[tag] = blob
        ifds.append(tags)
        (offset,) = struct.unpack_from("<Q", body, 20 * count)
        if len(ifds) > max_ifds:
            raise TiffError("too many IFDs")
    return ifds


def _scalar(tags: dict[int, object], tag: int) -> int:
    value = tags.get(tag)
    if isinstance(value, list) and value:
        return int(value[0])
    if tag in DEFAULTS:
        return DEFAULTS[tag]
    raise TiffError(f"missing TIFF tag {tag}")


def structure(fh: BinaryIO) -> dict:
    """Parse and validate IFD0 plus the overview chain; no pixel decode."""
    ifds = read_ifds(fh)
    tags = ifds[0]
    if _scalar(tags, 254) if 254 in tags else 0:
        raise TiffError("IFD0 is not the full-resolution image (NewSubfileType != 0)")
    info = {name: _scalar(tags, tag) for tag, name in TAG_NAMES.items()}
    diff = {k: (info[k], v) for k, v in EXPECTED_ENCODING.items() if info[k] != v}
    if diff:
        raise TiffError(f"unexpected IFD0 encoding (actual, expected): {diff}")
    width, height = info["width"], info["height"]
    tw, th = info["tile_width"], info["tile_height"]
    across, down = math.ceil(width / tw), math.ceil(height / th)
    offsets, counts = tags.get(324), tags.get(325)
    if not isinstance(offsets, list) or not isinstance(counts, list):
        raise TiffError("missing TileOffsets/TileByteCounts")
    if len(offsets) != across * down or len(counts) != across * down:
        raise TiffError(f"tile table length {len(offsets)}/{len(counts)} != {across * down}")
    if any(c <= 0 or o <= 0 for o, c in zip(offsets, counts)):
        raise TiffError("empty or sparse tile in IFD0")
    overview_sizes = []
    for level, ifd in enumerate(ifds[1:], 1):
        if (_scalar(ifd, 254) if 254 in ifd else 0) != 1:
            raise TiffError(f"IFD{level} is not a reduced-resolution overview")
        overview_sizes.append([_scalar(ifd, 256), _scalar(ifd, 257)])
    scale = tags.get(33550)
    tie = tags.get(33922)
    if not (isinstance(scale, list) and len(scale) >= 2 and isinstance(tie, list) and len(tie) >= 6):
        raise TiffError("missing ModelPixelScale/ModelTiepoint")
    nodata = tags.get(42113)
    meta = tags.get(42112)
    return {
        **info,
        "tiles_across": across,
        "tiles_down": down,
        "tile_count": across * down,
        "tile_offsets": offsets,
        "tile_byte_counts": counts,
        "ifd_count": len(ifds),
        "overview_sizes": overview_sizes,
        "pixel_scale": [float(scale[0]), float(scale[1])],
        "tiepoint_lon_lat": [float(tie[3]), float(tie[4])],
        "geokeys": tags.get(34735),
        "gdal_nodata": nodata.strip() if isinstance(nodata, str) else None,
        "gdal_metadata": meta if isinstance(meta, str) else None,
    }


def validate_encoding(info: dict) -> None:
    """Recipe-level checks shared by download.sh and build.sh."""
    sx, sy = info["pixel_scale"]
    if abs(sx - EXPECTED_PIXEL_SCALE) > 1e-12 or abs(sy - EXPECTED_PIXEL_SCALE) > 1e-12:
        raise TiffError(f"pixel scale {info['pixel_scale']} != {EXPECTED_PIXEL_SCALE}")
    if (info["gdal_nodata"] or "").lower() != EXPECTED_NODATA:
        raise TiffError(f"GDAL_NODATA {info['gdal_nodata']!r} != {EXPECTED_NODATA!r}")
    geokeys = info.get("geokeys") or []
    # GeoKeyDirectory: GTModelTypeGeoKey (1024) = 2 geographic,
    # GeographicTypeGeoKey (2048) = 4326 WGS 84.
    keys = {geokeys[i]: geokeys[i + 3] for i in range(4, len(geokeys) - 3, 4)}
    if keys.get(1024) != 2 or keys.get(2048) != 4326:
        raise TiffError(f"unexpected GeoKeys model/CRS {keys.get(1024)}/{keys.get(2048)}")


# --------------------------------------------------------------------------
# Pixel decode
# --------------------------------------------------------------------------

def zstd_decompress(blob: bytes) -> bytes:
    proc = subprocess.run([ZSTD_BIN, "-d", "-c", "-q"], input=blob,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise TiffError(f"zstd decode failed rc={proc.returncode}: "
                        f"{proc.stderr.decode('utf-8', 'replace')[:200]}")
    return proc.stdout


_MASK = (255).__and__


def undo_fp_predictor(tile: bytes, tile_width: int, tile_height: int) -> bytes:
    """Undo TIFF Predictor 3 for a 1-band float32 tile; return LE float32 bytes."""
    row_bytes = 4 * tile_width
    if len(tile) != row_bytes * tile_height:
        raise TiffError(f"tile has {len(tile)} bytes, expected {row_bytes * tile_height}")
    out = bytearray(len(tile))
    w = tile_width
    for r in range(tile_height):
        base = r * row_bytes
        row = bytes(map(_MASK, itertools.accumulate(tile[base:base + row_bytes])))
        dst = out[base:base + row_bytes]
        # LE float32: byte 0 = least significant = plane 3 ... byte 3 = plane 0.
        dst[0::4] = row[3 * w:4 * w]
        dst[1::4] = row[2 * w:3 * w]
        dst[2::4] = row[w:2 * w]
        dst[3::4] = row[0:w]
        out[base:base + row_bytes] = dst
    return bytes(out)


def decode_ifd0(fh: BinaryIO, info: dict | None = None) -> bytes:
    """Return the full-resolution grid as row-major little-endian float32."""
    if info is None:
        info = structure(fh)
    width, height = info["width"], info["height"]
    tw, th = info["tile_width"], info["tile_height"]
    across = info["tiles_across"]
    row_out = width * 4
    out = bytearray(width * height * 4)
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        raw = zstd_decompress(_read_exact(fh, off, cnt))
        if len(raw) != tw * th * 4:
            raise TiffError(f"tile {index}: decoded {len(raw)} bytes, expected {tw * th * 4}")
        tile = undo_fp_predictor(raw, tw, th)
        tx, ty = index % across, index // across
        copy_w = min(tw, width - tx * tw) * 4
        copy_h = min(th, height - ty * th)
        for r in range(copy_h):
            src = r * tw * 4
            dst = (ty * th + r) * row_out + tx * tw * 4
            out[dst:dst + copy_w] = tile[src:src + copy_w]
    return bytes(out)


# --------------------------------------------------------------------------
# Synthetic self-test: forward predictor-3 encoder + minimal BigTIFF writer
# --------------------------------------------------------------------------

def _encode_fp_predictor(le_floats: bytes, tile_width: int, tile_height: int) -> bytes:
    """Forward TIFF Predictor 3 (libtiff fpDiff) for a 1-band float32 tile."""
    w = tile_width
    out = bytearray()
    for r in range(tile_height):
        row = le_floats[r * 4 * w:(r + 1) * 4 * w]
        planes = bytearray(4 * w)
        for i in range(w):
            b0, b1, b2, b3 = row[4 * i:4 * i + 4]  # little-endian bytes
            planes[i] = b3
            planes[w + i] = b2
            planes[2 * w + i] = b1
            planes[3 * w + i] = b0
        diff = bytearray(planes)
        for i in range(len(planes) - 1, 0, -1):
            diff[i] = (planes[i] - planes[i - 1]) & 0xFF
        out += diff
    return bytes(out)


def _zstd_compress(blob: bytes) -> bytes:
    proc = subprocess.run([ZSTD_BIN, "-q", "-c", "-3"], input=blob,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout


def _write_bigtiff(path: str, width: int, height: int, tw: int, th: int,
                   tiles: list[bytes], overview: bool = True) -> None:
    """Minimal BigTIFF writer: IFD0 (tiles given) + an optional dummy overview."""
    entries0: list[tuple[int, int, list]] = []
    data = bytearray(b"II+\x00" + struct.pack("<HHQ", 8, 0, 0))
    tile_offsets = []
    for t in tiles:
        tile_offsets.append(len(data))
        data += t
    extra = bytearray()

    def ifd_bytes(entries, base, next_ifd):
        body = struct.pack("<Q", len(entries))
        tail = bytearray()
        tail_base = base + 8 + 20 * len(entries) + 8
        for tag, ftype, values in sorted(entries):
            if ftype == 2:
                blob = values.encode() + b"\x00"
                n = len(blob)
            else:
                blob = struct.pack("<" + TYPE_FMT[ftype] * len(values), *values)
                n = len(values)
            if len(blob) <= 8:
                body += struct.pack("<HHQ", tag, ftype, n) + blob.ljust(8, b"\x00")
            else:
                body += struct.pack("<HHQ", tag, ftype, n) + struct.pack("<Q", tail_base + len(tail))
                tail += blob
        body += struct.pack("<Q", next_ifd)
        return body + tail

    del extra
    entries0 = [
        (256, 4, [width]), (257, 4, [height]), (258, 3, [32]), (259, 3, [50000]),
        (262, 3, [1]), (277, 3, [1]), (284, 3, [1]), (317, 3, [3]),
        (322, 3, [tw]), (323, 3, [th]), (339, 3, [3]),
        (324, 16, tile_offsets), (325, 16, [len(t) for t in tiles]),
        (33550, 12, [0.0025, 0.0025, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, 8.0, 57.75, 0.0]),
        (34735, 3, [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326]),
        (42113, 2, "nan"),
    ]
    ifd0_at = len(data)
    # Two passes: first compute IFD0 length to place the overview after it.
    probe = ifd_bytes(entries0, ifd0_at, 0)
    ov_at = ifd0_at + len(probe) if overview else 0
    data += ifd_bytes(entries0, ifd0_at, ov_at)
    if overview:
        ov_tile = _zstd_compress(_encode_fp_predictor(b"\x00" * (tw * th * 4), tw, th))
        entries1 = [
            (254, 4, [1]), (256, 4, [max(1, width // 2)]), (257, 4, [max(1, height // 2)]),
            (258, 3, [32]), (259, 3, [50000]), (262, 3, [1]), (277, 3, [1]),
            (284, 3, [1]), (317, 3, [3]), (322, 3, [tw]), (323, 3, [th]), (339, 3, [3]),
            (324, 16, [0]), (325, 16, [len(ov_tile)]),
        ]
        first = ifd_bytes(entries1, ov_at, 0)
        tile_at = ov_at + len(first)
        entries1 = [e if e[0] != 324 else (324, 16, [tile_at]) for e in entries1]
        data += ifd_bytes(entries1, ov_at, 0)
        data += ov_tile
    struct.pack_into("<Q", data, 8, ifd0_at)
    with open(path, "wb") as fh:
        fh.write(data)


def selftest() -> None:
    import random
    import tempfile

    rng = random.Random(20261006)
    nan = struct.pack("<f", math.nan)

    # 1) Single tile round trip with NaN runs and edge-case floats.
    tw = th = 64
    vals = bytearray()
    for i in range(tw * th):
        if (i // 7) % 5 == 0:
            vals += nan
        else:
            vals += struct.pack("<f", rng.uniform(0.0, 25.0))
    specials = [0.0, -0.0, 1e-38, 3.4e38, -12.5, math.inf]
    for k, v in enumerate(specials):
        vals[4 * k:4 * k + 4] = struct.pack("<f", v)
    enc = _encode_fp_predictor(bytes(vals), tw, th)
    dec = undo_fp_predictor(zstd_decompress(_zstd_compress(enc)), tw, th)
    if dec != bytes(vals):
        raise SystemExit("selftest FAIL: single-tile predictor round trip")

    # 2) Full synthetic BigTIFF with 2x2 tiles of 512 and cropped edges.
    width, height, T = 700, 600, 512
    grid = bytearray()
    for y in range(height):
        for x in range(width):
            if (x - 350) ** 2 + (y - 300) ** 2 > 280 ** 2:
                grid += nan
            else:
                grid += struct.pack("<f", 4.0 + 0.01 * x + 0.003 * y + rng.random() * 0.2)
    tiles = []
    for ty in range(2):
        for tx in range(2):
            tile = bytearray(struct.pack("<f", 0.0) * (T * T))
            for r in range(T):
                y = ty * T + r
                if y >= height:
                    break
                x0 = tx * T
                n = min(T, width - x0)
                tile[r * T * 4:r * T * 4 + n * 4] = grid[(y * width + x0) * 4:(y * width + x0 + n) * 4]
            # padding beyond the image is arbitrary; use a marker to catch crop bugs
            for r in range(T):
                y = ty * T + r
                for c in range(T):
                    if y >= height or tx * T + c >= width:
                        tile[(r * T + c) * 4:(r * T + c) * 4 + 4] = struct.pack("<f", -999.0)
            tiles.append(_zstd_compress(_encode_fp_predictor(bytes(tile), T, T)))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "synthetic.tif")
        _write_bigtiff(path, width, height, T, T, tiles)
        with open(path, "rb") as fh:
            info = structure(fh)
            validate_encoding(info)
            out = decode_ifd0(fh, info)
    if info["width"] != width or info["height"] != height or info["tile_count"] != 4:
        raise SystemExit(f"selftest FAIL: structure {info['width']}x{info['height']} tiles={info['tile_count']}")
    if info["overview_sizes"] != [[350, 300]]:
        raise SystemExit(f"selftest FAIL: overview chain {info['overview_sizes']}")
    if out != bytes(grid):
        raise SystemExit("selftest FAIL: synthetic BigTIFF decode mismatch")
    print(json.dumps({"selftest": "ok", "single_tile_values": tw * th,
                      "synthetic_grid": [height, width], "tiles": 4}))


def smallest_overview_tiles(fh: BinaryIO) -> tuple[dict, list[tuple[int, int]]]:
    """discover.sh helper: (overview geometry, [(offset, count)]) of the last IFD."""
    ifds = read_ifds(fh)
    ov = ifds[-1]
    geom = {"width": _scalar(ov, 256), "height": _scalar(ov, 257),
            "tile_width": _scalar(ov, 322), "tile_height": _scalar(ov, 323)}
    for tag, want in ((258, 32), (259, 50000), (317, 3), (339, 3)):
        if _scalar(ov, tag) != want:
            raise TiffError(f"overview tag {tag}={_scalar(ov, tag)} expected {want}")
    return geom, list(zip(ov[324], ov[325]))


def overview_valid_share(geom: dict, tiles: list[bytes]) -> dict:
    """discover.sh helper: non-NaN share and value range of the smallest overview."""
    w, h, tw, th = geom["width"], geom["height"], geom["tile_width"], geom["tile_height"]
    across = math.ceil(w / tw)
    total = valid = 0
    lo, hi = math.inf, -math.inf
    for index, blob in enumerate(tiles):
        tile = undo_fp_predictor(zstd_decompress(blob), tw, th)
        tx, ty = index % across, index // across
        cw, ch = min(tw, w - tx * tw), min(th, h - ty * th)
        for r in range(ch):
            for v in struct.unpack_from(f"<{cw}f", tile, r * tw * 4):
                total += 1
                if v == v:
                    valid += 1
                    lo, hi = min(lo, v), max(hi, v)
    return {"overview": [w, h], "overview_valid_share": round(valid / total, 4),
            "overview_min": round(lo, 3), "overview_max": round(hi, 3)}


def header_summary(info: dict) -> dict:
    return {k: v for k, v in info.items() if k not in ("tile_offsets", "tile_byte_counts", "gdal_metadata")} | {
        "tile_bytes_total": sum(info["tile_byte_counts"]),
        "tile_bytes_min": min(info["tile_byte_counts"]),
        "tile_bytes_max": max(info["tile_byte_counts"]),
        "gdal_metadata_items": dict(re.findall(r'<Item name="([^"]+)"[^>]*>([^<]*)</Item>', info["gdal_metadata"] or "")),
    }


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "selftest":
        selftest()
        return 0
    if len(argv) == 3 and argv[1] == "overview-ranges":
        with open(argv[2], "rb") as fh:
            _, ranges = smallest_overview_tiles(fh)
        for off, cnt in ranges:
            print(f"{off}-{off + cnt - 1}")
        return 0
    if len(argv) >= 4 and argv[1] == "overview-share":
        with open(argv[2], "rb") as fh:
            info = structure(fh)
            geom, ranges = smallest_overview_tiles(fh)
        tiles = []
        for (off, cnt), path in zip(ranges, argv[3:]):
            with open(path, "rb") as tf:
                blob = tf.read()
            if len(blob) != cnt:
                raise TiffError(f"{path}: {len(blob)} bytes, expected {cnt}")
            tiles.append(blob)
        if len(tiles) != len(ranges):
            raise TiffError(f"got {len(tiles)} overview tiles, expected {len(ranges)}")
        print(json.dumps({"width": info["width"], "height": info["height"],
                          "tiepoint_lon_lat": info["tiepoint_lon_lat"]} | overview_valid_share(geom, tiles)))
        return 0
    if len(argv) != 3 or argv[1] not in ("header", "validate"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        with open(argv[2], "rb") as fh:
            info = structure(fh)
            if argv[1] == "validate":
                validate_encoding(info)
                size = fh.seek(0, os.SEEK_END)
                end = max(o + c for o, c in zip(info["tile_offsets"], info["tile_byte_counts"]))
                if end > size:
                    raise TiffError(f"IFD0 tiles extend to {end} beyond file size {size}")
    except (TiffError, OSError) as exc:
        print(f"INVALID {argv[2]}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(header_summary(info), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
