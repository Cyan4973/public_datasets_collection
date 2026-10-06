#!/usr/bin/env python3
"""Self-test for scripts/cdf5.py on synthetic CDF-1/CDF-2/CDF-5 inputs.

Covers: 64-bit NON_NEG counts and 64-bit OFFSETs (CDF-5), names and
attribute payloads whose lengths are not multiples of four (padding), char
and numeric attributes, scalar variables, 1-D and 2-D variables, a begin
offset above 2**32, truncated prefixes, bad magic, and the exact big-endian
payload decode used by the recipe.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdf5  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"selftest FAIL: {message}")


def roundtrip(version: int) -> None:
    ncol, lev = 7, 3
    t_values = [200.0 + i * 0.123456789012345 + (i % 5) * 1e-9 for i in range(lev * ncol)]
    f_values = [1.5, -2.25, 3.0e-7, 4.0, 5.5, 6.75, 7.125]
    gattrs = [("ne", 4, 4), ("calendar", 2, "NO_LEAP"), ("odd", 3, [1, -2, 3])]
    variables = [
        ("ymd", [], [], 4, struct.pack(">i", 20101)),
        ("tod", [], [], 4, struct.pack(">i", 43200)),
        ("frac", ["ncol"], [("units", 2, "1")], 5, struct.pack(">7f", *f_values)),
        ("state_t", ["lev", "ncol"], [("long_name", 2, "Temperature K")], 6,
         struct.pack(f">{lev * ncol}d", *t_values)),
        ("tag", ["ncol"], [], 1, bytes([1, 2, 3, 4, 5, 6, 7])),
    ]
    blob = cdf5.write_synthetic(version, [("ncol", ncol), ("lev", lev)], gattrs, variables)
    header = cdf5.parse_header(blob)
    check(header.version == version, f"v{version}: version")
    check(header.numrecs == 0, f"v{version}: numrecs")
    check([(d.name, d.length) for d in header.dims] == [("ncol", 7), ("lev", 3)], f"v{version}: dims")
    check(header.gattrs == {"ne": 4, "calendar": "NO_LEAP", "odd": [1, -2, 3]}, f"v{version}: gattrs {header.gattrs}")
    names = [v.name for v in header.vars]
    check(names == ["ymd", "tod", "frac", "state_t", "tag"], f"v{version}: var names {names}")
    state_t = header.var("state_t")
    check(state_t.type_name == "NC_DOUBLE" and state_t.shape == [3, 7], f"v{version}: state_t type/shape")
    check(state_t.vsize == 3 * 7 * 8 and state_t.value_count == 21, f"v{version}: state_t vsize")
    check(state_t.attrs == {"long_name": "Temperature K"}, f"v{version}: var attrs")
    decoded = struct.unpack(f">{state_t.value_count}d", blob[state_t.begin:state_t.begin + state_t.vsize])
    check(list(decoded) == t_values, f"v{version}: state_t payload")
    little = struct.pack(f"<{len(decoded)}d", *decoded)
    check(struct.unpack(f"<{len(decoded)}d", little) == tuple(t_values), f"v{version}: LE re-emit")
    frac = header.var("frac")
    check(frac.vsize == 28, f"v{version}: frac vsize")
    check(list(struct.unpack(">7f", blob[frac.begin:frac.begin + 28])) == [struct.unpack('>f', struct.pack('>f', x))[0] for x in f_values], f"v{version}: frac payload")
    tag = header.var("tag")
    check(tag.vsize == 8 and blob[tag.begin:tag.begin + 7] == bytes(range(1, 8)), f"v{version}: padded byte var")
    check(struct.unpack(">i", blob[header.var("ymd").begin:header.var("ymd").begin + 4])[0] == 20101, f"v{version}: ymd")
    check(struct.unpack(">i", blob[header.var("tod").begin:header.var("tod").begin + 4])[0] == 43200, f"v{version}: tod")
    check(header.header_end == header.var("ymd").begin, f"v{version}: header_end")
    check(tag.begin + tag.vsize == len(blob), f"v{version}: layout end")
    # Every strict prefix shorter than the header must raise NeedMoreBytes.
    for cut in range(0, header.header_end):
        try:
            cdf5.parse_header(blob[:cut])
        except cdf5.NeedMoreBytes:
            continue
        except cdf5.CDFError as exc:
            if cut < 4:
                continue
            raise SystemExit(f"selftest FAIL: v{version} prefix {cut} raised {exc!r}")
        raise SystemExit(f"selftest FAIL: v{version} prefix {cut} parsed")


def big_offsets_cdf5() -> None:
    v = 5
    out = b"CDF\x05" + struct.pack(">q", 0)
    out += struct.pack(">i", cdf5.NC_DIMENSION) + struct.pack(">q", 2)
    out += cdf5._w_name(v, "ncol") + struct.pack(">q", 384)
    out += cdf5._w_name(v, "lev") + struct.pack(">q", 60)
    out += b"\x00\x00\x00\x00" + struct.pack(">q", 0)  # ABSENT gatts (ZERO ZERO64)
    out += struct.pack(">i", cdf5.NC_VARIABLE) + struct.pack(">q", 1)
    out += cdf5._w_name(v, "state_t") + struct.pack(">q", 2) + struct.pack(">qq", 1, 0)
    out += b"\x00\x00\x00\x00" + struct.pack(">q", 0)
    out += struct.pack(">i", 6) + struct.pack(">q", (1 << 32) + 16) + struct.pack(">q", (1 << 33) + 8)
    header = cdf5.parse_header(out)
    var = header.var("state_t")
    check(var.begin == (1 << 33) + 8 and var.vsize == (1 << 32) + 16, "CDF-5 64-bit begin/vsize")
    check(var.shape == [60, 384], "CDF-5 dim mapping")
    check(header.header_end == len(out), "CDF-5 header_end")
    # A 32-bit reading of the same counts must not silently succeed.
    try:
        cdf5.parse_header(b"CDF\x01" + out[4:])
    except cdf5.CDFError:
        pass
    else:
        raise SystemExit("selftest FAIL: CDF-5 bytes parsed as CDF-1")


def bad_inputs() -> None:
    for blob in (b"HDF\x05" + b"\x00" * 32, b"CDF\x03" + b"\x00" * 32, b"\x89HDF\r\n\x1a\n"):
        try:
            cdf5.parse_header(blob)
        except cdf5.CDFError:
            continue
        raise SystemExit(f"selftest FAIL: bad magic {blob[:4]!r} accepted")


def main() -> int:
    for version in (1, 2, 5):
        roundtrip(version)
    big_offsets_cdf5()
    bad_inputs()
    check(not math.isnan(0.0), "sanity")
    print("cdf5 selftest ok (CDF-1, CDF-2, CDF-5 round trips; 64-bit offsets; truncation; bad magic)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
