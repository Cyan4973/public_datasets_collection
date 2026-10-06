#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py and the seaice_conc decode path.

Builds small HDF5/NetCDF4-like files from scratch (superblock v0 and v2,
version-2 object headers with an OCHK continuation, dense links in a fractal
heap with a root indirect block, a depth-1 v2 B-tree name index plus a
creation-order index, dense attributes, a global-heap vlen string, a decoy
uint8 dataset with an identical layout, version-1 and version-2 filter
pipelines and a version-1 chunk B-tree), then checks that the decoder returns
the exact grid through both link indexes and rejects corrupted or
out-of-scope variants.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

U8 = bytes.fromhex("100000000100000000000800")
I8 = bytes.fromhex("100800000100000000000800")
F32 = bytes.fromhex("11201f000400000000002000170800177f000000")
VLEN_STR = bytes([0x19, 0x01, 0x00, 0x00]) + struct.pack("<I", 16) + U8


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


def u8_attr(name: str, values: list[int]) -> bytes:
    return attribute(name, U8, (len(values),), bytes(values))


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


def filters_v2(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    out = bytes([2, len(entries)])
    for fid, values in entries:
        out += struct.pack("<HHH", fid, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
    return out


def filters_v1(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    out = bytes([1, len(entries)]) + b"\x00" * 6
    for fid, values in entries:
        out += struct.pack("<4H", fid, 0, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
        if len(values) % 2:
            out += b"\x00" * 4
    return out


def synthetic_grid(seed: int = 0) -> bytes:
    out = bytearray()
    for y in range(448):
        for x in range(304):
            r2 = (x - 152) ** 2 + (y - 224) ** 2
            if x < 20:
                v = 254
            elif x == 20:
                v = 253
            elif (x * 7 + y * 13) % 997 == 0:
                v = 252
            elif r2 < 90 ** 2:
                v = max(0, min(100, 100 - (r2 // 90) + ((x + y + seed) % 3)))
            elif (x + y * 3 + seed) % 5003 == 0:
                v = 255
            else:
                v = 0
            out.append(v)
    return bytes(out)


def build(grid: bytes, *, date: str = "2022-01-01", superblock: int = 2, filters: list | None = None,
          datatype: bytes = U8, stored_cut: int = 0, target_name: str = "cdr_seaice_conc") -> bytes:
    import seaice_conc as sc

    if filters is None:
        filters = [(2, (1,)), (1, (4,))]
    w = Writer()
    sb = w.alloc(48 if superblock == 2 else 96)
    gcol_value = b"git@example.invalid:seaice_cdr.git@selftest"
    gcol = w.add(
        b"GCOL" + bytes([1, 0, 0, 0]) + struct.pack("<Q", 16 + 16 + ((len(gcol_value) + 7) & ~7) + 16)
        + struct.pack("<HHIQ", 1, 1, 0, len(gcol_value)) + gcol_value + b"\x00" * (((len(gcol_value) + 7) & ~7) - len(gcol_value))
        + b"\x00" * 16
    )

    def chunked_dataset(data: bytes, pipeline: bytes, dense_attrs: list[bytes]) -> int:
        stored = zlib.compress(data, 4)
        if stored_cut:
            stored = stored[:-stored_cut]
        chunk_addr = w.add(stored)
        key0 = struct.pack("<II4Q", len(stored), 0, 0, 0, 0, 0)
        key1 = struct.pack("<II4Q", 0, 0, 1, 448, 304, 1)
        tree = w.add(b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF) + key0 + struct.pack("<Q", chunk_addr) + key1)
        layout = bytes([3, 2, 4]) + struct.pack("<Q", tree) + struct.pack("<4I", 1, 448, 304, 1)
        msgs = [(0x01, dataspace((1, 448, 304))), (0x03, datatype), (0x0B, pipeline), (0x08, layout)]
        if dense_attrs:
            heap_addr = w.alloc(146)
            block_size = 1024
            block_addr = w.alloc(block_size)
            objects = b""
            records = []
            position = 21
            for order, payload in enumerate(dense_attrs):
                name = payload[9:9 + struct.unpack_from("<H", payload, 2)[0] - 1]
                records.append(heap_id(position, len(payload), 8) + bytes([0]) + struct.pack("<II", order, lookup3(name)))
                objects += payload
                position += len(payload)
            w.put(block_addr, direct_block(heap_addr, 0, block_size, objects))
            w.put(heap_addr, heap_header(8, 0x02, 4096, 4, block_size, 65536, block_addr, 0, len(dense_attrs)))
            leaf = w.add(btlf(8, records))
            name_bt = w.add(bthd(8, 512, 17, 0, leaf, len(records), len(records)))
            msgs.append((0x15, bytes([0, 0]) + struct.pack("<QQ", heap_addr, name_bt)))
        return w.add(ohdr(msgs, 0x00))

    attrs = [
        string_attr("long_name", sc.EXPECTED_VARIABLE_ATTRS["long_name"]),
        string_attr("standard_name", "sea_ice_area_fraction"),
        string_attr("units", "1"),
        u8_attr("flag_values", [251, 252, 253, 254, 255]),
        string_attr("flag_meanings", sc.FLAG_MEANINGS),
        u8_attr("valid_range", [0, 100]),
        u8_attr("_FillValue", [255]),
        string_attr("_Unsigned", "true"),
        string_attr("grid_mapping", "projection"),
        attribute("scale_factor", F32, (1,), struct.pack("<f", 0.01)),
    ]
    target = chunked_dataset(grid, filters_v2(filters), attrs)
    decoy = chunked_dataset(bytes(reversed(grid)), filters_v1([(1, (6,))]), attrs[:3])

    names = [target_name, "decoy_conc", "x", "stdev_of_cdr_seaice_conc", "y"]
    targets = [target, decoy, decoy, decoy, decoy]
    # Link heap: root indirect block, one row of four 128-byte direct blocks,
    # slots 0 and 2 populated, slots 1 and 3 unallocated.
    heap_addr = w.alloc(146)
    iblock_addr = w.alloc(53)
    block_size = 128
    groups = [(0, [0, 1, 2]), (2, [3, 4])]
    child_addrs = [UNDEF] * 4
    heap_ids: dict[int, bytes] = {}
    for slot, members in groups:
        objects = b""
        position = 21
        for i in members:
            payload = link_message(names[i], i, targets[i])
            heap_ids[i] = heap_id(slot * block_size + position, len(payload), 7)
            objects += payload
            position += len(payload)
        addr = w.alloc(block_size)
        w.put(addr, direct_block(heap_addr, slot * block_size, block_size, objects))
        child_addrs[slot] = addr
    w.put(iblock_addr, checksummed(b"FHIB" + bytes([0]) + struct.pack("<QI", heap_addr, 0) + struct.pack("<4Q", *child_addrs)))
    w.put(heap_addr, heap_header(7, 0x02, 512, 4, block_size, 1024, iblock_addr, 1, len(names)))
    # Name index: depth-1 v2 B-tree (internal root with one record, two leaves).
    name_records = sorted((struct.pack("<I", lookup3(n.encode())) + heap_ids[i]) for i, n in enumerate(names))
    leaf_a = w.add(btlf(5, name_records[:2]))
    leaf_b = w.add(btlf(5, name_records[3:]))
    root_node = w.add(btin(5, name_records[2:3], [(leaf_a, 2), (leaf_b, 2)]))
    name_bt = w.add(bthd(5, 256, 11, 1, root_node, 1, len(names)))
    order_leaf = w.add(btlf(6, [struct.pack("<Q", i) + heap_ids[i] for i in range(len(names))]))
    order_bt = w.add(bthd(6, 256, 15, 0, order_leaf, len(names), len(names)))

    globals_a = [
        string_attr("cdr_variable", "cdr_seaice_conc"),
        string_attr("product_version", "v04r00"),
        string_attr("title", sc.EXPECTED_GLOBAL_ATTRS["title"]),
        string_attr("platform", sc.EXPECTED_GLOBAL_ATTRS["platform"]),
    ]
    globals_b = [
        string_attr("sensor", sc.EXPECTED_GLOBAL_ATTRS["sensor"]),
        string_attr("license", sc.EXPECTED_GLOBAL_ATTRS["license"]),
        string_attr("time_coverage_duration", "P1D"),
        string_attr("time_coverage_start", f"{date}T00:00:00Z"),
        string_attr("_NCProperties", "version=2,netcdf=selftest,hdf5=selftest"),
        attribute("software_version_id", VLEN_STR, (), struct.pack("<IQI", len(gcol_value), gcol, 1)),
    ]
    ochk_body = b"OCHK" + b"".join(message(0x0C, p, True) for p in globals_b)
    ochk = w.add(checksummed(ochk_body))
    link_info = bytes([0, 0x03]) + struct.pack("<QQQQ", len(names), heap_addr, name_bt, order_bt)
    root_msgs = [(0x02, link_info), (0x0A, b"\x00\x00")] + [(0x0C, p) for p in globals_a]
    root_msgs.append((0x10, struct.pack("<QQ", ochk, len(ochk_body) + 4)))
    root = w.add(ohdr(root_msgs, 0x05))

    eof = len(w.buf)
    if superblock == 2:
        w.put(sb, checksummed(b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root)))
    else:
        w.put(
            sb,
            b"\x89HDF\r\n\x1a\n" + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
            + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII", 0, root, 0, 0) + b"\x00" * 16,
        )
    return bytes(w.buf)


def expect_failure(label: str, func) -> None:
    try:
        func()
    except (h5lite.H5Error, struct.error, KeyError, IndexError, ValueError):
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main(quiet: bool = False) -> None:
    import seaice_conc as sc

    # lookup3 reference vectors from Bob Jenkins' lookup3.c driver5().
    assert lookup3(b"") == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago") == 0x17770551
    assert lookup3(b"Four score and seven years ago", 1) == 0xCD628161

    grid = synthetic_grid()
    for superblock in (0, 2):
        raw = build(grid, superblock=superblock)
        for index in ("name", "creation_order"):
            payload, meta = sc.decode_grid(raw, "2022-01-01", index)
            if payload != grid:
                raise SystemExit(f"selftest: decoded grid differs (superblock {superblock}, {index})")
            if meta["software_version_id"] != "git@example.invalid:seaice_cdr.git@selftest":
                raise SystemExit("selftest: vlen global attribute mismatch")
            if meta["checked_metadata_blocks"] < 10:
                raise SystemExit("selftest: too few checksummed blocks visited")
        sc.grid_profile(payload)
    deflate_only = build(grid, filters=[(1, (5,))])
    if sc.decode_grid(deflate_only, "2022-01-01", "name")[0] != grid:
        raise SystemExit("selftest: deflate-only pipeline decode differs")

    good = build(grid)
    expect_failure("wrong date", lambda: sc.decode_grid(good, "2022-01-02", "name"))
    expect_failure("shuffle element size 2", lambda: sc.decode_grid(build(grid, filters=[(2, (2,)), (1, (4,))]), "2022-01-01", "name"))
    expect_failure("extra fletcher32 filter", lambda: sc.decode_grid(build(grid, filters=[(2, (1,)), (1, (4,)), (3, ())]), "2022-01-01", "name"))
    expect_failure("signed datatype", lambda: sc.decode_grid(build(grid, datatype=I8), "2022-01-01", "name"))
    expect_failure("truncated chunk", lambda: sc.decode_grid(build(grid, stored_cut=7), "2022-01-01", "name"))
    expect_failure("missing target link", lambda: sc.decode_grid(build(grid, target_name="cdr_seaice_conc_x"), "2022-01-01", "name"))
    bad_grid = bytearray(grid)
    bad_grid[5000] = 150
    expect_failure("undocumented code 150", lambda: sc.grid_profile(bytes(bad_grid)))
    expect_failure("constant grid", lambda: sc.grid_profile(bytes([254]) * len(grid)))
    for marker, indexes in (
        (b"FHDB", ("name", "creation_order")),
        (b"FHIB", ("name", "creation_order")),
        (b"BTIN", ("name",)),
        (b"OCHK", ("name", "creation_order")),
        (b"FRHP", ("name", "creation_order")),
        (b"BTHD", ("name", "creation_order")),
        (b"TREE", ("name", "creation_order")),
    ):
        corrupt = bytearray(good)
        pos = corrupt.find(marker) + (5 if marker == b"TREE" else 9)
        corrupt[pos] ^= 0x55
        for index in indexes:
            expect_failure(f"corrupted {marker.decode()} ({index})", lambda c=bytes(corrupt), i=index: sc.decode_grid(c, "2022-01-01", i))
    corrupt = bytearray(good)
    corrupt[corrupt.find(b"cdr_seaice_conc") + 3] ^= 0x01  # link name inside a checksummed direct block
    for index in ("name", "creation_order"):
        expect_failure(f"corrupted link name ({index})", lambda c=bytes(corrupt), i=index: sc.decode_grid(c, "2022-01-01", i))
    corrupt = bytearray(good)
    corrupt[corrupt.find(b"BTLF\x00\x06") + 7] ^= 0x01  # creation-order leaf record
    expect_failure("corrupted creation-order leaf", lambda: sc.decode_grid(bytes(corrupt), "2022-01-01", "creation_order"))
    if not quiet:
        print("selftest=ok synthetic HDF5 decode and rejection checks passed")


if __name__ == "__main__":
    main()
