#!/usr/bin/env python3
"""Pure-stdlib PMTiles v3 directory reader and Mapbox Vector Tile geometry decoder.

Only what this recipe needs:
  * PMTiles v3 127-byte header, gzip-compressed varint directories
    (tile_id deltas, run_lengths, lengths, offsets with the 0 = contiguous rule)
  * Hilbert z/x/y <-> tile_id mapping (PMTiles spec)
  * MVT protobuf parsing (Tile.layers -> Layer.name/extent/features ->
    Feature.type/geometry) and the MoveTo/LineTo/ClosePath zigzag-delta
    command stream decoded to absolute tile-space integer coordinates.
"""
from __future__ import annotations

import gzip
import struct
import zlib

HEADER_LEN = 127
MAGIC = b"PMTiles"

COMPRESSION = {0: "unknown", 1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}
TILE_TYPE = {0: "unknown", 1: "mvt", 2: "png", 3: "jpeg", 4: "webp", 5: "avif"}


# --------------------------------------------------------------------------- header
def parse_header(buf: bytes) -> dict:
    if len(buf) < HEADER_LEN:
        raise ValueError("short PMTiles header")
    if buf[:7] != MAGIC:
        raise ValueError("bad PMTiles magic")
    if buf[7] != 3:
        raise ValueError(f"unsupported PMTiles version {buf[7]}")
    u64 = struct.unpack_from("<11Q", buf, 8)
    keys = [
        "root_dir_offset", "root_dir_length", "metadata_offset", "metadata_length",
        "leaf_dirs_offset", "leaf_dirs_length", "tile_data_offset", "tile_data_length",
        "addressed_tiles_count", "tile_entries_count", "tile_contents_count",
    ]
    h = dict(zip(keys, u64))
    (h["clustered"], h["internal_compression"], h["tile_compression"], h["tile_type"],
     h["min_zoom"], h["max_zoom"]) = struct.unpack_from("<6B", buf, 96)
    (h["min_lon_e7"], h["min_lat_e7"], h["max_lon_e7"], h["max_lat_e7"]) = struct.unpack_from("<4i", buf, 102)
    h["center_zoom"] = buf[118]
    h["center_lon_e7"], h["center_lat_e7"] = struct.unpack_from("<2i", buf, 119)
    return h


# --------------------------------------------------------------------------- varints
def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def encode_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


# --------------------------------------------------------------------------- directories
def decompress(data: bytes, compression: int) -> bytes:
    if compression == 1:
        return data
    if compression == 2:
        return gzip.decompress(data)
    raise ValueError(f"unsupported compression {COMPRESSION.get(compression, compression)}")


def deserialize_directory(raw: bytes) -> list[tuple[int, int, int, int]]:
    """Return entries (tile_id, offset, length, run_length) from an uncompressed directory."""
    pos = 0
    n, pos = read_varint(raw, pos)
    tile_ids = []
    last = 0
    for _ in range(n):
        d, pos = read_varint(raw, pos)
        last += d
        tile_ids.append(last)
    run_lengths = []
    for _ in range(n):
        v, pos = read_varint(raw, pos)
        run_lengths.append(v)
    lengths = []
    for _ in range(n):
        v, pos = read_varint(raw, pos)
        lengths.append(v)
    offsets = []
    for i in range(n):
        v, pos = read_varint(raw, pos)
        if v == 0:
            if i == 0:
                raise ValueError("first directory offset uses contiguous shortcut")
            offsets.append(offsets[i - 1] + lengths[i - 1])
        else:
            offsets.append(v - 1)
    if pos != len(raw):
        raise ValueError(f"directory has {len(raw) - pos} trailing bytes")
    for i in range(1, n):
        if tile_ids[i] <= tile_ids[i - 1]:
            raise ValueError("directory tile ids not strictly increasing")
    return list(zip(tile_ids, offsets, lengths, run_lengths))


def serialize_directory(entries: list[tuple[int, int, int, int]]) -> bytes:
    """Inverse of deserialize_directory (used only by self-tests)."""
    out = bytearray(encode_varint(len(entries)))
    last = 0
    for tid, _, _, _ in entries:
        out += encode_varint(tid - last)
        last = tid
    for _, _, _, rl in entries:
        out += encode_varint(rl)
    for _, _, ln, _ in entries:
        out += encode_varint(ln)
    for i, (_, off, _, _) in enumerate(entries):
        if i > 0 and off == entries[i - 1][1] + entries[i - 1][2]:
            out += encode_varint(0)
        else:
            out += encode_varint(off + 1)
    return bytes(out)


def find_entry(entries, tile_id: int):
    """PMTiles lookup: the last entry with entry.tile_id <= tile_id.

    Returns the entry if it is a leaf pointer (run_length == 0) or a tile run
    covering tile_id; otherwise None.
    """
    lo, hi = 0, len(entries) - 1
    found = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if entries[mid][0] <= tile_id:
            found = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if found < 0:
        return None
    e = entries[found]
    if e[3] == 0:
        return e
    if tile_id < e[0] + e[3]:
        return e
    return None


# --------------------------------------------------------------------------- hilbert
def zxy_to_tileid(z: int, x: int, y: int) -> int:
    if z > 31:
        raise ValueError("zoom too large")
    n = 1 << z
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError("tile x/y outside zoom")
    acc = ((1 << (2 * z)) - 1) // 3
    d = 0
    s = n >> 1
    while s > 0:
        rx = 1 if (x & s) else 0
        ry = 1 if (y & s) else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = n - 1 - x
                y = n - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def tileid_to_zxy(tile_id: int) -> tuple[int, int, int]:
    acc = 0
    z = 0
    while True:
        num = 1 << (2 * z)
        if tile_id < acc + num:
            break
        acc += num
        z += 1
        if z > 31:
            raise ValueError("tile id too large")
    n = 1 << z
    t = tile_id - acc
    x = y = 0
    s = 1
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s <<= 1
    return z, x, y


# --------------------------------------------------------------------------- protobuf / MVT
def iter_fields(buf: bytes, start: int = 0, end: int | None = None):
    """Yield (field_number, wire_type, value) where value is int or (start, end) slice."""
    pos = start
    end = len(buf) if end is None else end
    while pos < end:
        key, pos = read_varint(buf, pos)
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, pos = read_varint(buf, pos)
            yield field, wt, v
        elif wt == 2:
            ln, pos = read_varint(buf, pos)
            if pos + ln > end:
                raise ValueError("truncated length-delimited field")
            yield field, wt, (pos, pos + ln)
            pos += ln
        elif wt == 1:
            pos += 8
            yield field, wt, None
        elif wt == 5:
            pos += 4
            yield field, wt, None
        else:
            raise ValueError(f"unsupported wire type {wt}")
    if pos != end:
        raise ValueError("protobuf message overran its bounds")


def packed_uint32(buf: bytes, start: int, end: int) -> list[int]:
    out = []
    pos = start
    while pos < end:
        v, pos = read_varint(buf, pos)
        out.append(v)
    if pos != end:
        raise ValueError("packed field overran")
    return out


def unzigzag(v: int) -> int:
    return (v >> 1) ^ -(v & 1)


def decode_polygon_geometry(cmds: list[int]) -> tuple[list[int], int]:
    """Decode an MVT polygon command stream; cursor starts at (0, 0) per feature.

    Returns (interleaved absolute x,y vertices in ring order, ring count). The
    ClosePath command emits no vertex (the start vertex is not duplicated).
    Strict structure: each ring is MoveTo(1), LineTo(>=1), ClosePath(1).
    """
    out: list[int] = []
    x = y = 0
    i = 0
    n = len(cmds)
    rings = 0
    state = "move"  # expected next command
    while i < n:
        ci = cmds[i]
        i += 1
        cid, count = ci & 7, ci >> 3
        if cid == 1:
            if state != "move" or count != 1:
                raise ValueError("polygon MoveTo out of order or count != 1")
            state = "line"
        elif cid == 2:
            if state != "line" or count < 1:
                raise ValueError("polygon LineTo out of order or count < 1")
            state = "close"
        elif cid == 7:
            if state != "close" or count != 1:
                raise ValueError("polygon ClosePath out of order or count != 1")
            rings += 1
            state = "move"
            continue
        else:
            raise ValueError(f"unknown geometry command {cid}")
        if i + 2 * count > n:
            raise ValueError("geometry parameters truncated")
        for _ in range(count):
            x += unzigzag(cmds[i])
            y += unzigzag(cmds[i + 1])
            i += 2
            out.append(x)
            out.append(y)
    if state != "move":
        raise ValueError("polygon geometry ends inside a ring")
    return out, rings


def decode_layer(tile: bytes, layer_name: str) -> dict | None:
    """Decode one named layer of an uncompressed MVT tile.

    Returns dict(extent, version, features, polygon_features, other_type_counts,
    rings, coords) or None if the layer is absent. coords is the concatenation
    of every polygon feature's vertices in feature order.
    """
    target = layer_name.encode()
    found = None
    names = []
    for field, wt, val in iter_fields(tile):
        if field == 3 and wt == 2:
            s, e = val
            name = None
            for f2, w2, v2 in iter_fields(tile, s, e):
                if f2 == 1 and w2 == 2:
                    name = tile[v2[0]:v2[1]]
                    break
            names.append(name)
            if name == target:
                if found is not None:
                    raise ValueError(f"duplicate layer {layer_name}")
                found = (s, e)
    if found is None:
        return None
    s, e = found
    extent = 4096
    version = None
    features = 0
    polys = 0
    other: dict[int, int] = {}
    rings = 0
    coords: list[int] = []
    for f2, w2, v2 in iter_fields(tile, s, e):
        if f2 == 5 and w2 == 0:
            extent = v2
        elif f2 == 15 and w2 == 0:
            version = v2
        elif f2 == 2 and w2 == 2:
            features += 1
            gtype = 0
            geom = None
            for f3, w3, v3 in iter_fields(tile, v2[0], v2[1]):
                if f3 == 3 and w3 == 0:
                    gtype = v3
                elif f3 == 4 and w3 == 2:
                    geom = packed_uint32(tile, v3[0], v3[1])
            if gtype != 3:
                other[gtype] = other.get(gtype, 0) + 1
                continue
            if not geom:
                raise ValueError("polygon feature without geometry")
            pts, r = decode_polygon_geometry(geom)
            polys += 1
            rings += r
            coords.extend(pts)
    return {
        "extent": extent,
        "version": version,
        "features": features,
        "polygon_features": polys,
        "other_type_counts": other,
        "rings": rings,
        "coords": coords,
        "layer_names": [n.decode("utf-8", "replace") if n is not None else None for n in names],
    }


# --------------------------------------------------------------------------- self-test
def _encode_field_varint(field: int, v: int) -> bytes:
    return encode_varint(field << 3) + encode_varint(v)


def _encode_field_bytes(field: int, data: bytes) -> bytes:
    return encode_varint((field << 3) | 2) + encode_varint(len(data)) + data


def _zz(v: int) -> int:
    return (v << 1) ^ (v >> 63)


def _encode_polygon(rings: list[list[tuple[int, int]]], cursor=(0, 0)) -> list[int]:
    cx, cy = cursor
    cmds = []
    for ring in rings:
        cmds.append((1 & 7) | (1 << 3))
        x, y = ring[0]
        cmds += [_zz(x - cx), _zz(y - cy)]
        cx, cy = x, y
        cmds.append((2 & 7) | ((len(ring) - 1) << 3))
        for x, y in ring[1:]:
            cmds += [_zz(x - cx), _zz(y - cy)]
            cx, cy = x, y
        cmds.append((7 & 7) | (1 << 3))
    return cmds


def self_test() -> None:
    # Hilbert ids from the PMTiles specification test vectors.
    vectors = {(0, 0, 0): 0, (1, 0, 0): 1, (1, 0, 1): 2, (1, 1, 1): 3, (1, 1, 0): 4, (2, 0, 0): 5}
    for zxy, tid in vectors.items():
        assert zxy_to_tileid(*zxy) == tid, (zxy, zxy_to_tileid(*zxy), tid)
        assert tileid_to_zxy(tid) == zxy
    for z in range(0, 6):
        n = 1 << z
        seen = set()
        for x in range(n):
            for y in range(n):
                t = zxy_to_tileid(z, x, y)
                assert tileid_to_zxy(t) == (z, x, y)
                seen.add(t)
        base = ((1 << (2 * z)) - 1) // 3
        assert seen == set(range(base, base + n * n))
    # Aligned 2^k blocks are contiguous id ranges (property relied on by the plan).
    for x0, y0 in [(9648, 12312), (16592, 11272), (0, 0), (32760, 32760)]:
        ids = sorted(zxy_to_tileid(15, x0 + dx, y0 + dy) for dx in range(8) for dy in range(8))
        assert ids == list(range(ids[0], ids[0] + 64)), (x0, y0)
    for t in [0, 1, 12345678901, zxy_to_tileid(15, 9649, 12314)]:
        assert zxy_to_tileid(*tileid_to_zxy(t)) == t
    # Directory round trip including the contiguous-offset shortcut and leaves.
    entries = [(5, 0, 100, 1), (6, 100, 50, 1), (9, 150, 10, 3), (20, 5, 100, 1), (40, 160, 7, 0)]
    raw = serialize_directory(entries)
    assert deserialize_directory(raw) == entries
    assert deserialize_directory(gzip.decompress(gzip.compress(raw))) == entries
    assert find_entry(entries, 4) is None
    assert find_entry(entries, 10) == entries[2]
    assert find_entry(entries, 12) is None
    assert find_entry(entries, 41) == entries[4]
    # MVT polygon decode: two features, cursor reset per feature, negatives, holes.
    f1_rings = [[(10, 20), (4000, 20), (4000, 4100), (10, 4100)], [(100, 100), (200, 100), (150, 180)]]
    f2_rings = [[(-64, -64), (4160, -64), (4160, 4160)]]
    g1 = _encode_polygon(f1_rings)
    g2 = _encode_polygon(f2_rings)
    feat = lambda gtype, g: _encode_field_varint(3, gtype) + _encode_field_bytes(4, b"".join(encode_varint(c) for c in g))
    pt = [(1 & 7) | (1 << 3), _zz(5), _zz(6)]
    layer = (_encode_field_varint(15, 2) + _encode_field_bytes(1, b"buildings")
             + _encode_field_bytes(2, feat(3, g1)) + _encode_field_bytes(2, feat(1, pt))
             + _encode_field_bytes(2, feat(3, g2)) + _encode_field_varint(5, 4096))
    other_layer = _encode_field_varint(15, 2) + _encode_field_bytes(1, b"roads") + _encode_field_varint(5, 4096)
    tile = _encode_field_bytes(3, other_layer) + _encode_field_bytes(3, layer)
    d = decode_layer(tile, "buildings")
    expect = [v for ring in f1_rings + f2_rings for p in ring for v in p]
    assert d["coords"] == expect, d["coords"]
    assert d["polygon_features"] == 2 and d["rings"] == 3 and d["other_type_counts"] == {1: 1}
    assert d["extent"] == 4096 and d["version"] == 2
    assert decode_layer(tile, "water") is None
    # A stream whose cursor did NOT reset would decode differently: guard the semantics.
    bad = _encode_polygon(f2_rings, cursor=(f1_rings[-1][-1]))
    assert decode_polygon_geometry(bad)[0] != [v for p in f2_rings[0] for v in p]
    for broken in ([9, 0, 0, 15], [10, 0, 0, 0, 0], [9, 0, 0, 10, 2, 2]):
        try:
            decode_polygon_geometry(broken)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted malformed geometry {broken}")
    print("pmtiles_mvt self-test OK")


if __name__ == "__main__":
    self_test()
