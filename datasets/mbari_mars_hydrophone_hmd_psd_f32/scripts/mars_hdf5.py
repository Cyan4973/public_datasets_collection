#!/usr/bin/env python3
"""Minimal pure-stdlib HDF5 walker for the MBARI MARS daily HMD NetCDF4 files.

Only the structures used by these NetCDF4/HDF5 files are supported, and every
assumption is checked rather than trusted:

* superblock version 0 (root symbol-table entry) or version 2/3 (root object
  header address);
* object headers version 1 and version 2 ("OHDR", with "OCHK" continuation
  blocks and Jenkins lookup3 checksums verified);
* compact link messages (type 6) in the root group, hard links only;
* dataspace (1), datatype (3), fill value (4/5), layout (8, version 3),
  filter pipeline (11), attribute (12) and continuation (16) messages.

Datasets are located by link name through the root group; no file offset is
assumed. The caller decides what layout is acceptable.
"""

from __future__ import annotations

import struct
from typing import Any

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEF = 0xFFFFFFFFFFFFFFFF


class H5Error(ValueError):
    pass


# --------------------------------------------------------------------------
# Jenkins lookup3 hashlittle (HDF5 metadata checksum)
# --------------------------------------------------------------------------

def _rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF


def lookup3(data: bytes, initval: int = 0) -> int:
    length = len(data)
    a = b = c = (0xDEADBEEF + length + initval) & 0xFFFFFFFF
    i = 0
    M = 0xFFFFFFFF
    while length > 12:
        a = (a + data[i] + (data[i + 1] << 8) + (data[i + 2] << 16) + (data[i + 3] << 24)) & M
        b = (b + data[i + 4] + (data[i + 5] << 8) + (data[i + 6] << 16) + (data[i + 7] << 24)) & M
        c = (c + data[i + 8] + (data[i + 9] << 8) + (data[i + 10] << 16) + (data[i + 11] << 24)) & M
        a = (a - c) & M; a ^= _rot(c, 4); c = (c + b) & M
        b = (b - a) & M; b ^= _rot(a, 6); a = (a + c) & M
        c = (c - b) & M; c ^= _rot(b, 8); b = (b + a) & M
        a = (a - c) & M; a ^= _rot(c, 16); c = (c + b) & M
        b = (b - a) & M; b ^= _rot(a, 19); a = (a + c) & M
        c = (c - b) & M; c ^= _rot(b, 4); b = (b + a) & M
        length -= 12
        i += 12
    if length == 0:
        return c
    tail = data[i:i + length] + b"\0" * (12 - length)
    a = (a + tail[0] + (tail[1] << 8) + (tail[2] << 16) + (tail[3] << 24)) & M
    b = (b + tail[4] + (tail[5] << 8) + (tail[6] << 16) + (tail[7] << 24)) & M
    c = (c + tail[8] + (tail[9] << 8) + (tail[10] << 16) + (tail[11] << 24)) & M
    c ^= b; c = (c - _rot(b, 14)) & M
    a ^= c; a = (a - _rot(c, 11)) & M
    b ^= a; b = (b - _rot(a, 25)) & M
    c ^= b; c = (c - _rot(b, 16)) & M
    a ^= c; a = (a - _rot(c, 4)) & M
    b ^= a; b = (b - _rot(a, 14)) & M
    c ^= b; c = (c - _rot(b, 24)) & M
    return c


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _u(raw: Any, offset: int, size: int) -> int:
    if offset < 0 or offset + size > len(raw):
        raise H5Error(f"read of {size} bytes at {offset} outside buffer of {len(raw)}")
    return int.from_bytes(bytes(raw[offset:offset + size]), "little")


def _need(raw: Any, offset: int, size: int) -> bytes:
    if offset < 0 or offset + size > len(raw):
        raise H5Error(f"structure at {offset}+{size} outside buffer of {len(raw)}")
    return bytes(raw[offset:offset + size])


# --------------------------------------------------------------------------
# superblock
# --------------------------------------------------------------------------

def superblock(raw: Any) -> dict[str, int]:
    if _need(raw, 0, 8) != HDF5_SIGNATURE:
        raise H5Error("missing HDF5 signature at offset 0")
    version = raw[8]
    if version == 0:
        if raw[13] != 8 or raw[14] != 8:
            raise H5Error("unexpected HDF5 offset/length sizes")
        base = _u(raw, 24, 8)
        eof = _u(raw, 40, 8)
        # root group symbol table entry starts at 56
        root_ohdr = _u(raw, 56 + 8, 8)
    elif version in (2, 3):
        if raw[9] != 8 or raw[10] != 8:
            raise H5Error("unexpected HDF5 offset/length sizes")
        base = _u(raw, 12, 8)
        eof = _u(raw, 28, 8)
        root_ohdr = _u(raw, 36, 8)
        stored = _u(raw, 44, 4)
        if lookup3(_need(raw, 0, 44)) != stored:
            raise H5Error("superblock checksum mismatch")
    else:
        raise H5Error(f"unsupported superblock version {version}")
    if base != 0:
        raise H5Error(f"unsupported nonzero base address {base}")
    return {"version": version, "eof": eof, "root_ohdr": root_ohdr}


# --------------------------------------------------------------------------
# object headers
# --------------------------------------------------------------------------

def _v2_messages(raw: Any, start: int, end: int, track_order: bool, out: list, conts: list) -> None:
    cursor = start
    header = 6 if track_order else 4
    while cursor + header <= end:
        mtype = raw[cursor]
        msize = _u(raw, cursor + 1, 2)
        mflags = raw[cursor + 3]
        payload_start = cursor + header
        payload_end = payload_start + msize
        if payload_end > end:
            raise H5Error(f"v2 message at {cursor} overruns its chunk")
        payload = _need(raw, payload_start, msize)
        if mtype == 16:
            conts.append((_u(payload, 0, 8), _u(payload, 8, 8)))
        out.append((mtype, mflags, payload))
        cursor = payload_end
    # remaining bytes (< header size) are a gap and must be zero
    if any(_need(raw, cursor, end - cursor)):
        raise H5Error("nonzero gap at end of v2 object header chunk")


def object_messages(raw: Any, address: int) -> list[tuple[int, int, bytes]]:
    """Return [(type, flags, payload)] for the object header at ``address``."""
    messages: list[tuple[int, int, bytes]] = []
    if _need(raw, address, 4) == b"OHDR":
        version = raw[address + 4]
        if version != 2:
            raise H5Error(f"unsupported OHDR version {version}")
        flags = raw[address + 5]
        cursor = address + 6
        if flags & 0x20:
            cursor += 16
        if flags & 0x10:
            cursor += 4
        size_len = 1 << (flags & 0x03)
        chunk_size = _u(raw, cursor, size_len)
        cursor += size_len
        chunk_end = cursor + chunk_size
        stored = _u(raw, chunk_end, 4)
        if lookup3(_need(raw, address, chunk_end - address)) != stored:
            raise H5Error(f"OHDR checksum mismatch at {address}")
        track = bool(flags & 0x04)
        conts: list[tuple[int, int]] = []
        _v2_messages(raw, cursor, chunk_end, track, messages, conts)
        seen: set[int] = set()
        while conts:
            caddr, clen = conts.pop(0)
            if caddr in seen:
                raise H5Error("cyclic OCHK continuation")
            seen.add(caddr)
            if _need(raw, caddr, 4) != b"OCHK":
                raise H5Error(f"missing OCHK signature at {caddr}")
            stored = _u(raw, caddr + clen - 4, 4)
            if lookup3(_need(raw, caddr, clen - 4)) != stored:
                raise H5Error(f"OCHK checksum mismatch at {caddr}")
            _v2_messages(raw, caddr + 4, caddr + clen - 4, track, messages, conts)
        return messages
    # version 1 object header
    if raw[address] != 1:
        raise H5Error(f"unsupported object header at {address}")
    count = _u(raw, address + 2, 2)
    blocks = [(address + 16, _u(raw, address + 8, 4))]
    seen: set[int] = set()
    while blocks and len(messages) < count:
        start, size = blocks.pop(0)
        if start in seen:
            raise H5Error("cyclic v1 continuation")
        seen.add(start)
        cursor = start
        end = start + size
        while cursor + 8 <= end and len(messages) < count:
            mtype = _u(raw, cursor, 2)
            msize = _u(raw, cursor + 2, 2)
            mflags = raw[cursor + 4]
            payload = _need(raw, cursor + 8, msize)
            if cursor + 8 + msize > end:
                raise H5Error("v1 message overruns its block")
            if mtype == 16:
                blocks.append((_u(payload, 0, 8), _u(payload, 8, 8)))
            messages.append((mtype, mflags, payload))
            cursor += 8 + msize
    return messages


# --------------------------------------------------------------------------
# message decoders
# --------------------------------------------------------------------------

def decode_links(messages: list[tuple[int, int, bytes]]) -> dict[str, int]:
    links: dict[str, int] = {}
    for mtype, _flags, p in messages:
        if mtype == 2:
            # link info: fractal heap address must be undefined (compact storage)
            lflags = p[1]
            pos = 2 + (8 if lflags & 1 else 0)
            if _u(p, pos, 8) != UNDEF:
                raise H5Error("dense link storage (fractal heap) is not supported")
        if mtype == 17:
            raise H5Error("old-style symbol-table group is not supported")
        if mtype != 6:
            continue
        if p[0] != 1:
            raise H5Error(f"unsupported link message version {p[0]}")
        lflags = p[1]
        pos = 2
        link_type = 0
        if lflags & 0x08:
            link_type = p[pos]
            pos += 1
        if lflags & 0x04:
            pos += 8
        if lflags & 0x10:
            pos += 1
        nlen_size = 1 << (lflags & 0x03)
        nlen = _u(p, pos, nlen_size)
        pos += nlen_size
        name = p[pos:pos + nlen].decode("utf-8")
        pos += nlen
        if link_type != 0:
            raise H5Error(f"link {name!r} is not a hard link (type {link_type})")
        if name in links:
            raise H5Error(f"duplicate link name {name!r}")
        links[name] = _u(p, pos, 8)
    return links


def decode_dataspace(p: bytes) -> tuple[int, ...]:
    version = p[0]
    rank = p[1]
    flags = p[2]
    if version == 1:
        pos = 8
    elif version == 2:
        if p[3] not in (0, 1):
            raise H5Error(f"unsupported dataspace type {p[3]}")
        pos = 4
    else:
        raise H5Error(f"unsupported dataspace version {version}")
    dims = tuple(_u(p, pos + 8 * i, 8) for i in range(rank))
    if flags & 1:
        maxdims = tuple(_u(p, pos + 8 * (rank + i), 8) for i in range(rank))
        if any(m != d for m, d in zip(maxdims, dims)):
            raise H5Error(f"extendible dataspace dims={dims} max={maxdims}")
    return dims


def decode_float_type(p: bytes) -> dict[str, int]:
    cls = p[0] & 0x0F
    version = p[0] >> 4
    bits = p[1] | (p[2] << 8) | (p[3] << 16)
    size = _u(p, 4, 4)
    out = {"class": cls, "version": version, "size": size, "bitfield": bits}
    if cls == 1:
        out.update(
            byte_order_be=bits & 1 or (bits >> 6) & 1,
            bit_offset=_u(p, 8, 2),
            precision=_u(p, 10, 2),
            exp_loc=p[12],
            exp_size=p[13],
            mant_loc=p[14],
            mant_size=p[15],
            exp_bias=_u(p, 16, 4),
        )
    return out


def is_ieee_f32le(t: dict[str, int]) -> bool:
    return (
        t["class"] == 1
        and t["size"] == 4
        and not t["byte_order_be"]
        and t["bit_offset"] == 0
        and t["precision"] == 32
        and t["exp_loc"] == 23
        and t["exp_size"] == 8
        and t["mant_loc"] == 0
        and t["mant_size"] == 23
        and t["exp_bias"] == 127
    )


def decode_layout(p: bytes) -> dict[str, int]:
    version = p[0]
    if version != 3:
        raise H5Error(f"unsupported layout message version {version}")
    cls = p[1]
    if cls == 1:
        return {"class": 1, "address": _u(p, 2, 8), "size": _u(p, 10, 8)}
    return {"class": cls}


def decode_attributes(messages: list[tuple[int, int, bytes]]) -> dict[str, dict[str, Any]]:
    """Decode attribute names plus raw value bytes and datatype class/size."""
    attrs: dict[str, dict[str, Any]] = {}
    for mtype, _flags, p in messages:
        if mtype != 12:
            continue
        version = p[0]
        name_size = _u(p, 2, 2)
        dt_size = _u(p, 4, 2)
        ds_size = _u(p, 6, 2)
        if version == 1:
            pad = lambda n: (n + 7) & ~7  # noqa: E731
            pos = 8
            name = p[pos:pos + name_size].rstrip(b"\0").decode("utf-8", "replace")
            pos += pad(name_size)
            dt = p[pos:pos + dt_size]
            pos += pad(dt_size)
            ds = p[pos:pos + ds_size]
            pos += pad(ds_size)
        elif version in (2, 3):
            pos = 8 if version == 2 else 9
            name = p[pos:pos + name_size].rstrip(b"\0").decode("utf-8", "replace")
            pos += name_size
            dt = p[pos:pos + dt_size]
            pos += dt_size
            ds = p[pos:pos + ds_size]
            pos += ds_size
        else:
            raise H5Error(f"unsupported attribute message version {version}")
        attrs[name] = {"type_class": dt[0] & 0x0F, "type_size": _u(dt, 4, 4), "dtype": dt, "data": p[pos:]}
    return attrs


def describe_dataset(raw: Any, address: int) -> dict[str, Any]:
    messages = object_messages(raw, address)
    kinds = [m[0] for m in messages]
    out: dict[str, Any] = {"address": address, "message_types": kinds}
    ds = [p for t, _f, p in messages if t == 1]
    dt = [p for t, _f, p in messages if t == 3]
    lay = [p for t, _f, p in messages if t == 8]
    if len(ds) != 1 or len(dt) != 1 or len(lay) != 1:
        raise H5Error(f"object at {address} is not a single dataset: types={kinds}")
    out["shape"] = decode_dataspace(ds[0])
    out["dtype"] = decode_float_type(dt[0])
    out["layout"] = decode_layout(lay[0])
    out["filters"] = sum(1 for t in kinds if t == 11)
    out["attributes"] = decode_attributes(messages)
    return out


def root_datasets(raw: Any) -> dict[str, dict[str, Any]]:
    sb = superblock(raw)
    root = object_messages(raw, sb["root_ohdr"])
    links = decode_links(root)
    return {name: describe_dataset(raw, addr) for name, addr in sorted(links.items())}


if __name__ == "__main__":
    import json
    import sys

    data = open(sys.argv[1], "rb").read()
    info = root_datasets(data)
    for name, d in info.items():
        attrs = {k: (v["type_class"], v["type_size"], v["data"][:16].hex()) for k, v in d["attributes"].items()}
        print(name, json.dumps({k: v for k, v in d.items() if k != "attributes"}, default=str), attrs)
