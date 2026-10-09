#!/usr/bin/env python3
"""Strict pure-stdlib parser for OPeNDAP DAP2 binary (.dods) responses.

A .dods response is the DDS text of the projected variables, the marker
"\nData:\n", then the XDR-encoded values in DDS declaration order:

- scalar Int32 / Float32: 4 big-endian bytes, no length prefix
- array: two big-endian int32 element counts (identical), then the elements;
  Byte arrays are packed one byte per element and zero-padded to a 4-byte
  boundary, Int16/UInt16 are widened to 4 bytes, Int32/Float32 are 4 bytes,
  Float64 is 8 bytes.

Only flat (non-Grid, non-Structure) projections are supported, which is what
this recipe requests. Any trailing or missing byte is an error.
"""
from __future__ import annotations

import re
import struct

MARKER = b"\nData:\n"
_DECL = re.compile(
    r"^\s*(Byte|Int16|UInt16|Int32|UInt32|Float32|Float64)\s+(\w+)((?:\[[^\]]*\])*);\s*$",
    re.M,
)
_DIM = re.compile(r"\[(?:\w+\s*=\s*)?(\d+)\]")


def parse_dds(text: str) -> list[tuple[str, str, list[int]]]:
    if not text.lstrip().startswith("Dataset {"):
        raise ValueError("DDS does not start with 'Dataset {'")
    if "Grid" in text or "Structure" in text or "Sequence" in text:
        raise ValueError("constructor types are not supported in this projection")
    decls = []
    for typ, name, dims in _DECL.findall(text):
        shape = [int(d) for d in _DIM.findall(dims)]
        decls.append((typ, name, shape))
    body_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(("Dataset {", "}"))]
    if len(body_lines) != len(decls):
        raise ValueError(f"unparsed DDS lines: {body_lines!r}")
    return decls


def parse(buf: bytes) -> dict[str, object]:
    pos = buf.find(MARKER)
    if pos < 0:
        snippet = buf[:300].decode("utf-8", "replace")
        raise ValueError(f"no DAP2 'Data:' marker; response starts {snippet!r}")
    dds = buf[:pos].decode("ascii")
    i = pos + len(MARKER)
    out: dict[str, object] = {}
    for typ, name, shape in parse_dds(dds):
        if not shape:
            if typ in ("Int32", "Int16", "Byte"):
                out[name] = struct.unpack_from(">i", buf, i)[0]
                i += 4
            elif typ in ("UInt32", "UInt16"):
                out[name] = struct.unpack_from(">I", buf, i)[0]
                i += 4
            elif typ == "Float32":
                out[name] = struct.unpack_from(">f", buf, i)[0]
                i += 4
            else:
                out[name] = struct.unpack_from(">d", buf, i)[0]
                i += 8
            continue
        n = 1
        for d in shape:
            n *= d
        if i + 8 > len(buf):
            raise ValueError(f"truncated before counts of {name}")
        n1, n2 = struct.unpack_from(">ii", buf, i)
        i += 8
        if n1 != n or n2 != n:
            raise ValueError(f"{name}: XDR counts {n1},{n2} != DDS size {n}")
        if typ == "Byte":
            end = i + n
            if end > len(buf):
                raise ValueError(f"truncated {name}")
            out[name] = buf[i:end]
            i += (n + 3) // 4 * 4
        elif typ in ("Float32", "Int32", "UInt32"):
            end = i + 4 * n
            if end > len(buf):
                raise ValueError(f"truncated {name}")
            out[name] = (typ, buf[i:end])  # raw big-endian 4-byte elements
            i = end
        elif typ in ("Int16", "UInt16"):
            end = i + 4 * n
            if end > len(buf):
                raise ValueError(f"truncated {name}")
            out[name] = ("Int32", buf[i:end])
            i = end
        else:
            end = i + 8 * n
            if end > len(buf):
                raise ValueError(f"truncated {name}")
            out[name] = (typ, buf[i:end])
            i = end
    if i != len(buf):
        raise ValueError(f"{len(buf) - i} trailing bytes after XDR payload")
    return out


def be32_to_le(raw: bytes) -> bytes:
    """Byte-swap a buffer of 4-byte big-endian elements to little-endian."""
    if len(raw) % 4:
        raise ValueError("buffer length not a multiple of 4")
    import array

    a = array.array("I")
    if a.itemsize != 4:
        raise RuntimeError("platform array('I') is not 4 bytes")
    a.frombytes(raw)
    a.byteswap()
    return a.tobytes()


def unpack_be(typ: str, raw: bytes) -> tuple:
    code = {"Float32": "f", "Int32": "i", "UInt32": "I", "Float64": "d"}[typ]
    size = 8 if typ == "Float64" else 4
    return struct.unpack(f">{len(raw) // size}{code}", raw)


def _selftest() -> None:
    dds = (
        "Dataset {\n"
        "    Int32 xyzStartTime;\n"
        "    Float32 xyzSampleRate;\n"
        "    Byte xyzFlagPrimary[xyzCount = 5];\n"
        "    Float32 xyzZDisplacement[xyzCount = 3];\n"
        "} cdip/archive/x/x.nc;\n"
    )
    body = struct.pack(">i", 1288900800) + struct.pack(">f", 1.28)
    body += struct.pack(">ii", 5, 5) + bytes([2, 2, 9, 1, 2]) + b"\0\0\0"
    body += struct.pack(">ii", 3, 3) + struct.pack(">3f", 0.25, -1.5, -999.99)
    buf = dds.encode() + MARKER + body
    r = parse(buf)
    assert r["xyzStartTime"] == 1288900800
    assert r["xyzSampleRate"] == struct.unpack(">f", struct.pack(">f", 1.28))[0]
    assert r["xyzFlagPrimary"] == bytes([2, 2, 9, 1, 2])
    typ, raw = r["xyzZDisplacement"]
    assert unpack_be(typ, raw) == (0.25, -1.5, struct.unpack(">f", struct.pack(">f", -999.99))[0])
    le = be32_to_le(raw)
    assert struct.unpack("<3f", le) == unpack_be(typ, raw)
    for bad in (buf + b"\0", buf[:-1], buf.replace(MARKER, b"\nDota:\n")):
        try:
            parse(bad)
        except (ValueError, struct.error):
            pass
        else:
            raise AssertionError("malformed buffer accepted")
    bad_count = dds.encode() + MARKER + body.replace(struct.pack(">ii", 3, 3), struct.pack(">ii", 3, 4))
    try:
        parse(bad_count)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched XDR counts accepted")
    print("cdip_dods selftest ok")


if __name__ == "__main__":
    _selftest()
