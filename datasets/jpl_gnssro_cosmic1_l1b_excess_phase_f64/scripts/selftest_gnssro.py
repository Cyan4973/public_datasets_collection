#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py, the build decoder (gnssro.py) and the
independent verifier (verify_samples.py).

Builds small NetCDF4-like HDF5 files from scratch that mirror the JPL COSMIC-1
L1b layout: superblock v2, a root group with dense links (fractal heap with a
root indirect block, depth-1 v2 B-tree name index plus a creation-order
index), dense global attributes (fractal heap direct block, v2 B-tree type 8)
plus compact attributes in an OCHK continuation chunk, and contiguous
little-endian float64 / char datasets (``excess_phase`` (signal, time),
``phase_observation_code``, ``carrier_frequency``, ``time``, ``start_time``
and a decoy ``snr`` with the same shape).  It then checks that build and
verify return identical, exact L1 bytes (L1 on row 0 and on row 1, with edge
fill stripped), agree on every documented drop reason, and reject wrong
product identities and corrupted metadata.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

F64 = bytes.fromhex("11203f000800000000004000340b0034ff030000")
F64_BE = bytes.fromhex("11213f000800000000004000340b0034ff030000")
I32 = bytes.fromhex("100800000400000000002000")
CHAR = bytes.fromhex("1300000001000000")
FILL = -9.99e20
GRANULE = "gnssro_cosmic1_jpl_l1b_v2.6_cosmic1c3-G17-201103150842"
ROW = {
    "key": f"contributed/v2.0/gnssro_cosmic1_jpl_l1b/2011/03/15/{GRANULE}.nc4",
    "granule": GRANULE,
    "receiver": "cosmic1c3",
    "transmitter": "G17",
    "stamp": "201103150842",
    "month": "2011-03",
    "day": "15",
    "md5": "0" * 32,
    "size": 0,
}


def fixed_string_type(size: int) -> bytes:
    return bytes([0x13, 0, 0, 0]) + struct.pack("<I", size)


def dataspace(dims: tuple[int, ...]) -> bytes:
    if not dims:
        return bytes([2, 0, 0, 0])
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray()

    def alloc(self, size: int) -> int:
        while len(self.buf) % 8:
            self.buf.append(0)
        addr = len(self.buf)
        self.buf.extend(b"\x00" * size)
        return addr

    def put(self, addr: int, data: bytes) -> None:
        self.buf[addr:addr + len(data)] = data

    def add(self, data: bytes) -> int:
        addr = self.alloc(len(data))
        self.put(addr, data)
        return addr


def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def message(mtype: int, payload: bytes, with_order: bool, flags: int = 0) -> bytes:
    head = struct.pack("<BHB", mtype, len(payload), flags)
    return head + (b"\x00\x00" if with_order else b"") + payload


def ohdr(messages: list[tuple[int, bytes]], flags: int) -> bytes:
    with_order = bool(flags & 0x04)
    body = b"".join(message(t, p, with_order) for t, p in messages)
    size_len = 1 << (flags & 0x03)
    return checksummed(b"OHDR" + bytes([2, flags]) + len(body).to_bytes(size_len, "little") + body)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return (
        bytes([3, 0])
        + struct.pack("<HHH", len(raw_name), len(datatype), len(space))
        + b"\x00"
        + raw_name
        + datatype
        + space
        + data
    )


def string_attr(name: str, value: str) -> bytes:
    raw = value.encode()
    return attribute(name, fixed_string_type(len(raw)), (), raw)


def i32_attr(name: str, value: int) -> bytes:
    return attribute(name, I32, (1,), struct.pack("<i", value))


def f64_attr(name: str, values: list[float]) -> bytes:
    return attribute(name, F64, (len(values),), struct.pack(f"<{len(values)}d", *values))


def heap_header(id_len: int, flags: int, max_managed: int, width: int, start: int, max_direct: int,
                root: int, rows: int, n_objects: int) -> bytes:
    fields = [0, UNDEF, 0, UNDEF, 0, 0, 0, n_objects, 0, 0, 0, 0]
    body = (
        b"FRHP" + bytes([0]) + struct.pack("<HHBI", id_len, 0, flags, max_managed)
        + struct.pack("<12Q", *fields)
        + struct.pack("<HQQHHQH", width, start, max_direct, 32, 1, root, rows)
    )
    return checksummed(body)


def direct_block(heap_addr: int, block_offset: int, size: int, objects: bytes) -> bytes:
    head = b"FHDB" + bytes([0]) + struct.pack("<QI", heap_addr, block_offset)
    block = bytearray(head + b"\x00\x00\x00\x00" + objects)
    if len(block) > size:
        raise AssertionError("synthetic direct block overflow")
    block.extend(b"\x00" * (size - len(block)))
    block[len(head):len(head) + 4] = struct.pack("<I", lookup3(bytes(block)))
    return bytes(block)


def heap_id(offset: int, length: int, id_len: int) -> bytes:
    out = bytes([0]) + struct.pack("<I", offset) + struct.pack("<H", length)
    return out + b"\x00" * (id_len - len(out))


def link_message(name: str, order: int, target: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x04]) + struct.pack("<Q", order) + bytes([len(raw)]) + raw + struct.pack("<Q", target)


def bthd(btype: int, node_size: int, record_size: int, depth: int, root: int, root_n: int, total: int) -> bytes:
    return checksummed(
        b"BTHD" + bytes([0, btype]) + struct.pack("<IHHBBQHQ", node_size, record_size, depth, 100, 40, root, root_n, total)
    )


def btlf(btype: int, records: list[bytes]) -> bytes:
    return checksummed(b"BTLF" + bytes([0, btype]) + b"".join(records))


def btin(btype: int, records: list[bytes], children: list[tuple[int, int]]) -> bytes:
    pointers = b"".join(struct.pack("<QB", addr, n) for addr, n in children)
    return checksummed(b"BTIN" + bytes([0, btype]) + b"".join(records) + pointers)


def synthetic_profile(n: int, scale: float, seed: int) -> list[float]:
    """Smooth occultation-like phase ramp with small wiggles (all distinct)."""
    return [scale * (1.0 - i / n) ** 2 + 0.37 * math.sin(0.013 * i + seed) + 1e-7 * i for i in range(n)]


def build(
    *,
    n: int = 1600,
    codes: tuple[str, ...] = ("L1W", "L2W"),
    freqs: tuple[float, ...] = (1575.42e6, 1227.6e6),
    l1_lead: int = 37,
    l1_trail: int = 5,
    holes: tuple[int, ...] = (),
    nan_at: tuple[int, ...] = (),
    constant: bool = False,
    step: float = 0.02,
    layout: str = "contiguous",
    ep_filters: bool = False,
    ep_type: bytes = F64,
    globals_override: dict | None = None,
) -> tuple[bytes, bytes]:
    """Return (file bytes, expected L1 payload bytes)."""
    nsig = len(codes)
    rows = []
    expected = b""
    for r, code in enumerate(codes):
        values = synthetic_profile(n, 4000.0 + 900.0 * r, r)
        if code.startswith("L1"):
            if constant:
                values = [123.25] * n
            for i in range(l1_lead):
                values[i] = FILL
            for i in range(n - l1_trail, n):
                values[i] = FILL
            for i in holes:
                values[i] = FILL
            for i in nan_at:
                values[i] = float("nan")
            expected = struct.pack(f"<{n - l1_lead - l1_trail}d", *values[l1_lead:n - l1_trail])
        else:
            for i in range(n // 3):
                values[i] = FILL  # L2-style leading fill run
        rows.append(values)
    ep_bytes = struct.pack(f"<{nsig * n}d", *[x for row in rows for x in row])
    if ep_type == F64_BE:
        ep_bytes = struct.pack(f">{nsig * n}d", *[x for row in rows for x in row])

    w = Writer()
    sb = w.alloc(48)

    def contiguous(name_attrs: list[bytes], dims: tuple[int, ...], dtype: bytes, data: bytes,
                   filters: bytes | None = None, chunked: bool = False) -> int:
        data_addr = w.add(data)
        if chunked:
            key0 = struct.pack("<II3Q", len(data), 0, 0, 0, 0)
            key1 = struct.pack("<II3Q", 0, 0, dims[0], dims[1], 8)
            tree = w.add(b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF) + key0
                         + struct.pack("<Q", data_addr) + key1)
            layout_msg = bytes([3, 2, 3]) + struct.pack("<Q", tree) + struct.pack("<3I", dims[0], dims[1], 8)
        else:
            layout_msg = bytes([3, 1]) + struct.pack("<QQ", data_addr, len(data))
        msgs = [(0x01, dataspace(dims)), (0x03, dtype)]
        if filters is not None:
            msgs.append((0x0B, filters))
        msgs.append((0x08, layout_msg))
        msgs += [(0x0C, a) for a in name_attrs]
        return w.add(ohdr(msgs, 0x00))

    ep_attrs = [string_attr("long_name", "excess phase"), string_attr("units", "meter"), f64_attr("_FillValue", [FILL])]
    deflate = bytes([2, 1]) + struct.pack("<HHH", 1, 1, 1) + struct.pack("<I", 4)
    times = struct.pack(f"<{n}d", *[i * step for i in range(n)])
    targets = {
        "start_time": contiguous([string_attr("units", "seconds since 1980-01-06 00:00:00 UTC")], (), F64,
                                 struct.pack("<d", 984213723.5)),
        "phase_observation_code": contiguous([], (nsig, 3), CHAR, "".join(codes).encode()),
        "carrier_frequency": contiguous([string_attr("units", "Hz")], (nsig,), F64, struct.pack(f"<{nsig}d", *freqs)),
        "time": contiguous([string_attr("units", "seconds since start")], (n,), F64, times),
        "snr": contiguous([string_attr("units", "1")], (nsig, n), F64,
                          struct.pack(f"<{nsig * n}d", *[float(i % 97) for i in range(nsig * n)])),
        "excess_phase": contiguous(ep_attrs, (nsig, n), ep_type, ep_bytes,
                                   filters=deflate if ep_filters else None, chunked=layout == "chunked"),
    }
    # Creation order differs from name order on purpose.
    names = ["start_time", "phase_observation_code", "carrier_frequency", "time", "snr", "excess_phase"]

    # Link heap: root indirect block with one row of four 256-byte direct
    # blocks; slots 0 and 2 populated, slots 1 and 3 unallocated.
    heap_addr = w.alloc(146)
    iblock_addr = w.alloc(53)
    block_size = 256
    groups = [(0, [0, 1, 2]), (2, [3, 4, 5])]
    child_addrs = [UNDEF] * 4
    heap_ids: dict[int, bytes] = {}
    for slot, members in groups:
        objects = b""
        position = 21
        for i in members:
            payload = link_message(names[i], i, targets[names[i]])
            heap_ids[i] = heap_id(slot * block_size + position, len(payload), 7)
            objects += payload
            position += len(payload)
        addr = w.alloc(block_size)
        w.put(addr, direct_block(heap_addr, slot * block_size, block_size, objects))
        child_addrs[slot] = addr
    w.put(iblock_addr, checksummed(b"FHIB" + bytes([0]) + struct.pack("<QI", heap_addr, 0) + struct.pack("<4Q", *child_addrs)))
    w.put(heap_addr, heap_header(7, 0x02, 512, 4, block_size, 2048, iblock_addr, 1, len(names)))
    name_records = sorted((struct.pack("<I", lookup3(nm.encode())) + heap_ids[i]) for i, nm in enumerate(names))
    leaf_a = w.add(btlf(5, name_records[:3]))
    leaf_b = w.add(btlf(5, name_records[4:]))
    root_node = w.add(btin(5, name_records[3:4], [(leaf_a, 3), (leaf_b, 2)]))
    name_bt = w.add(bthd(5, 256, 11, 1, root_node, 1, len(names)))
    order_leaf = w.add(btlf(6, [struct.pack("<Q", i) + heap_ids[i] for i in range(len(names))]))
    order_bt = w.add(bthd(6, 256, 15, 0, order_leaf, len(names), len(names)))

    g = {
        "mission": "cosmic1",
        "institution": "jpl",
        "institution_version": "v2.6",
        "VersionID": "2.0",
        "ShortName": "gnssro_cosmic1_jpl_l1b",
        "ProcessingLevel": "1B",
        "data_use_license": "http://creativecommons.org/licenses/by/4.0/",
        "Format": "NetCDF4",
        "source": "GNSS radio occultation",
        "GranuleID": GRANULE,
        "receiver": "cosmic1c3",
        "transmitter": "G17",
        "reference_transmitter": "G05",
        "RangeBeginningDate": "2011-03-15",
        "RangeBeginningTime": "08:41:47",
    }
    g.update(globals_override or {})
    dense = [string_attr(k, v) for k, v in g.items() if k not in ("receiver", "transmitter")]
    dense += [i32_attr("year", 2011), i32_attr("month", 3), i32_attr("day", 15)]
    compact = [string_attr("receiver", g["receiver"]), string_attr("transmitter", g["transmitter"]),
               i32_attr("hour", 8), i32_attr("minute", 42)]

    # Dense global attributes: one 2048-byte root direct block + name B-tree.
    aheap = w.alloc(146)
    ablock_size = 2048
    ablock = w.alloc(ablock_size)
    objects = b""
    records = []
    position = 21
    for order, payload in enumerate(dense):
        nm = payload[9:9 + struct.unpack_from("<H", payload, 2)[0] - 1]
        records.append(heap_id(position, len(payload), 8) + bytes([0]) + struct.pack("<II", order, lookup3(nm)))
        objects += payload
        position += len(payload)
    w.put(ablock, direct_block(aheap, 0, ablock_size, objects))
    w.put(aheap, heap_header(8, 0x02, 4096, 4, ablock_size, 65536, ablock, 0, len(dense)))
    records.sort(key=lambda rec: struct.unpack_from("<I", rec, 13)[0])
    aleaf = w.add(btlf(8, records))
    abt = w.add(bthd(8, 2048, 17, 0, aleaf, len(records), len(records)))

    ochk_body = b"OCHK" + b"".join(message(0x0C, p, True) for p in compact)
    ochk = w.add(checksummed(ochk_body))
    link_info = bytes([0, 0x03]) + struct.pack("<QQQQ", len(names), heap_addr, name_bt, order_bt)
    attr_info = bytes([0, 0]) + struct.pack("<QQ", aheap, abt)
    root_msgs = [(0x02, link_info), (0x0A, b"\x00\x00"), (0x15, attr_info),
                 (0x10, struct.pack("<QQ", ochk, len(ochk_body) + 4))]
    root = w.add(ohdr(root_msgs, 0x05))
    eof = len(w.buf)
    w.put(sb, checksummed(b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root)))
    return bytes(w.buf), expected


def decode_both(raw: bytes):
    import gnssro
    import verify_samples

    try:
        payload, meta = gnssro.decode_sounding(raw, ROW, "name")
        built = ("keep", payload, meta["phase_observation_code"], meta["l1_row"], meta["span_start"], meta["span_end"])
    except gnssro.SoundingDropped as drop:
        built = ("drop", drop.reason)
    verdict, result = verify_samples.rederive(raw, ROW)
    checked = ("keep", *result) if verdict == "keep" else ("drop", result)
    if built != checked:
        raise SystemExit(f"selftest: build {built[:1] + built[2:] if built[0] == 'keep' else built} "
                         f"!= verify {checked[:1] + checked[2:] if checked[0] == 'keep' else checked}")
    return built


def expect_failure(label: str, func) -> None:
    import gnssro

    try:
        func()
    except (gnssro.SoundingFatal, h5lite.H5Error, struct.error, KeyError, IndexError, ValueError):
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main(quiet: bool = False) -> None:
    import gnssro
    import verify_samples

    assert lookup3(b"") == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago") == 0x17770551
    assert lookup3(b"Four score and seven years ago", 1) == 0xCD628161

    # 1. L1 on row 0 with edge fill: exact bytes, both link indexes agree.
    raw, expected = build()
    got = decode_both(raw)
    if got[0] != "keep" or got[1] != expected or got[2:] != ("L1W", 0, 37, 1595):
        raise SystemExit("selftest: L1 row 0 extraction differs")
    payload, meta = gnssro.decode_sounding(raw, ROW, "creation_order")
    if payload != expected or meta["time_step_s"] != 0.02 or meta["start_time_gps_s"] != 984213723.5:
        raise SystemExit("selftest: creation-order decode or metadata differs")
    # 2. L1 on row 1 (do not assume row 0); no edge fill.
    raw, expected = build(codes=("L2X", "L1W"), freqs=(1227.6e6, 1575.42e6), l1_lead=0, l1_trail=0)
    got = decode_both(raw)
    if got[0] != "keep" or got[1] != expected or got[2:] != ("L1W", 1, 0, 1600):
        raise SystemExit("selftest: L1 row 1 extraction differs")
    # 3. three signals, L1 in the middle.
    raw, expected = build(codes=("L2W", "L1C", "L5X"), freqs=(1227.6e6, 1575.42e6, 1176.45e6))
    got = decode_both(raw)
    if got[0] != "keep" or got[1] != expected or got[3] != 1:
        raise SystemExit("selftest: three-signal extraction differs")
    # 4. documented drops: build and verify agree on the reason.
    drops = {
        "l1_interior_fill": dict(holes=(700,)),
        "l1_span_below_1000": dict(n=1200, l1_lead=150, l1_trail=60),
        "not_50hz_monotonic": dict(step=0.01),
        "no_unique_l1_row": dict(codes=("L2W", "L5X"), freqs=(1227.6e6, 1176.45e6)),
        "l1_row_not_1575_42_mhz": dict(freqs=(1227.6e6, 1227.6e6)),
        "layout_not_contiguous": dict(layout="chunked"),
        "filter_pipeline_present": dict(ep_filters=True),
        "excess_phase_not_f64_le": dict(ep_type=F64_BE),
        "l1_constant": dict(constant=True),
        "l1_all_fill": dict(n=1200, l1_lead=1200, l1_trail=0),
    }
    for reason, kwargs in drops.items():
        got = decode_both(build(**kwargs)[0])
        if got != ("drop", reason):
            raise SystemExit(f"selftest: expected drop {reason}, got {got[:1]}{got[-1:] if got[0] == 'drop' else ''}")
    got = decode_both(build(nan_at=(900,))[0])
    if got != ("drop", "l1_interior_fill"):
        raise SystemExit("selftest: interior NaN not treated as a gap")
    raw, expected = build(nan_at=(37, 38), l1_lead=37)
    got = decode_both(raw)
    if got[0] != "keep" or got[4] != 39 or got[1] != expected[16:]:
        raise SystemExit("selftest: edge NaN not stripped like fill")
    # 5. wrong product identity is fatal in both paths.
    for override in (
        {"institution_version": "v2.5"},
        {"mission": "cosmic2"},
        {"institution": "ucar"},
        {"data_use_license": "https://www.ucar.edu/terms-of-use/data"},
        {"VersionID": "1.1"},
        {"GranuleID": GRANULE.replace("G17", "G18")},
    ):
        bad = build(globals_override=override)[0]
        expect_failure(f"identity {override}", lambda b=bad: gnssro.decode_sounding(b, ROW))
        expect_failure(f"verify identity {override}", lambda b=bad: verify_samples.rederive(b, ROW))
    for override in ({"receiver": "cosmic1c4"}, {"RangeBeginningDate": "2011/03/15"}):
        bad = build(globals_override=override)[0]
        expect_failure(f"build-only identity {override}", lambda b=bad: gnssro.decode_sounding(b, ROW))
    # 6. corrupted checksummed metadata is rejected.
    good = build()[0]
    for marker in (b"FHDB", b"FHIB", b"BTIN", b"OCHK", b"FRHP", b"BTHD", b"OHDR", b"BTLF\x00\x06"):
        corrupt = bytearray(good)
        pos = corrupt.rfind(marker) + 9
        corrupt[pos] ^= 0x55
        # The name-index internal node is only read by build; the
        # creation-order leaf only by verify.
        if marker != b"BTLF\x00\x06":
            expect_failure(f"corrupted {marker!r}", lambda c=bytes(corrupt): gnssro.decode_sounding(c, ROW))
        if marker != b"BTIN":
            expect_failure(f"verify corrupted {marker!r}", lambda c=bytes(corrupt): verify_samples.rederive(c, ROW))
    expect_failure("truncated file", lambda: gnssro.decode_sounding(good[:-8], ROW))
    if not quiet:
        print("selftest=ok synthetic JPL-L1b-like HDF5 decode, drop-policy and rejection checks passed")


if __name__ == "__main__":
    main()
