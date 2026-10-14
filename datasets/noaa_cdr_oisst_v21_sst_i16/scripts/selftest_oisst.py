#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py and the OISST sst decode path.

Builds small NetCDF4-like HDF5 files from scratch, with superblock v0 and v2:

* version-2 object headers with an OCHK continuation
* dense links in a fractal heap with a root indirect block, a depth-1 v2
  B-tree name index plus a creation-order index
* dense variable attributes and compact lat/lon axis attributes
* a decoy int16 dataset with an identical layout
* an int16 720x1440 variable stored as one shuffle(2)+deflate chunk indexed by
  a rank-5 version-1 B-tree, exactly as in the real files

It checks that both decode routes (name index + slice unshuffle, creation
order + zip unshuffle) return the exact grid. It also checks that corrupted or
out-of-scope variants are rejected.
"""
from __future__ import annotations

import array
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

U8 = bytes.fromhex("100000000100000000000800")
I16 = bytes.fromhex("100800000200000000001000")
U16 = bytes.fromhex("100000000200000000001000")
I16_BE = bytes.fromhex("100900000200000000001000")
F32 = bytes.fromhex("11201f000400000000002000170800177f000000")
ROWS, COLS = 720, 1440
DATE = "2020-01-15"
ROW = {"date": DATE, "key": "data/v2.1/avhrr/202001/oisst-avhrr-v02r01.20200115.nc"}


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


def i16_attr(name: str, value: int) -> bytes:
    return attribute(name, I16, (1,), struct.pack("<h", value))


def f32_attr(name: str, value: float) -> bytes:
    return attribute(name, F32, (1,), struct.pack("<f", value))


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


def shuffle(data: bytes, element: int) -> bytes:
    """HDF5 shuffle filter (forward): byte j of element i goes to j * n + i."""
    n = len(data) // element
    return b"".join(data[j::element] for j in range(element))


def synthetic_grid(seed: int = 0, land_cells: int | None = None) -> bytes:
    import oisst_sst as osst

    land = osst.LAND_FILL_CELLS if land_cells is None else land_cells
    values = array.array("h", [osst.FILL]) * (ROWS * COLS)
    for i in range(land, ROWS * COLS):
        y, x = divmod(i, COLS)
        values[i] = -180 + (y * 7 + x * 3 + seed + (x * y) % 11) % 3400
    if sys.byteorder == "big":
        values.byteswap()
    return values.tobytes()


def build(grid: bytes, *, superblock: int = 2, filters: list | None = None, datatype: bytes = I16,
          stored_cut: int = 0, target_name: str = "sst", title_suffix: str = " - Final",
          scale: float = 0.01, date: str = DATE, element: int = 2) -> bytes:
    import oisst_sst as osst

    if filters is None:
        filters = [(2, (2,)), (1, (4,))]
    w = Writer()
    sb = w.alloc(48 if superblock == 2 else 96)

    def chunked_dataset(data: bytes, pipeline: bytes, dense_attrs: list[bytes]) -> int:
        stored = zlib.compress(shuffle(data, element), 4)
        if stored_cut:
            stored = stored[:-stored_cut]
        chunk_addr = w.add(stored)
        key0 = struct.pack("<II5Q", len(stored), 0, 0, 0, 0, 0, 0)
        key1 = struct.pack("<II5Q", 0, 0, 1, 1, ROWS, COLS, 2)
        tree = w.add(b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF) + key0 + struct.pack("<Q", chunk_addr) + key1)
        layout = bytes([3, 2, 5]) + struct.pack("<Q", tree) + struct.pack("<5I", 1, 1, ROWS, COLS, 2)
        msgs = [(0x01, dataspace((1, 1, ROWS, COLS))), (0x03, datatype), (0x0B, pipeline), (0x08, layout)]
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
        string_attr("long_name", "Daily sea surface temperature"),
        string_attr("units", "Celsius"),
        i16_attr("_FillValue", -999),
        f32_attr("add_offset", 0.0),
        f32_attr("scale_factor", scale),
        i16_attr("valid_min", -300),
        i16_attr("valid_max", 4500),
    ]
    target = chunked_dataset(grid, filters_v2(filters), attrs)
    decoy_grid = bytes(reversed(grid))
    decoy = chunked_dataset(decoy_grid, filters_v2([(2, (2,)), (1, (6,))]), attrs[:3])

    def axis(name: str) -> int:
        msgs = [(0x0C, string_attr("grids", osst.EXPECTED_AXIS_GRIDS[name])), (0x0C, string_attr("units", "deg"))]
        return w.add(ohdr(msgs, 0x00))

    names = [target_name, "anom", "lat", "lon", "err"]
    targets = [target, decoy, axis("lat"), axis("lon"), decoy]
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
    name_records = sorted((struct.pack("<I", lookup3(n.encode())) + heap_ids[i]) for i, n in enumerate(names))
    leaf_a = w.add(btlf(5, name_records[:2]))
    leaf_b = w.add(btlf(5, name_records[3:]))
    root_node = w.add(btin(5, name_records[2:3], [(leaf_a, 2), (leaf_b, 2)]))
    name_bt = w.add(bthd(5, 256, 11, 1, root_node, 1, len(names)))
    order_leaf = w.add(btlf(6, [struct.pack("<Q", i) + heap_ids[i] for i in range(len(names))]))
    order_bt = w.add(bthd(6, 256, 15, 0, order_leaf, len(names), len(names)))

    g = osst.EXPECTED_GLOBAL_ATTRS
    globals_a = [
        string_attr("title", g["title"].replace(" - Final", title_suffix)),
        string_attr("product_version", g["product_version"]),
        string_attr("processing_level", g["processing_level"]),
        string_attr("institution", g["institution"]),
        string_attr("metadata_link", g["metadata_link"]),
    ]
    globals_b = [
        f32_attr("geospatial_lat_resolution", 0.25),
        f32_attr("geospatial_lon_resolution", 0.25),
        f32_attr("geospatial_lat_min", -90.0),
        f32_attr("geospatial_lat_max", 90.0),
        f32_attr("geospatial_lon_min", 0.0),
        f32_attr("geospatial_lon_max", 360.0),
        string_attr("id", "oisst-avhrr-v02r01." + date.replace("-", "") + ".nc"),
        string_attr("time_coverage_start", f"{date}T00:00:00Z"),
        string_attr("time_coverage_end", f"{date}T23:59:59Z"),
        string_attr("history", "Final file created using preliminary as first guess, and 3 days of AVHRR data."),
        string_attr("_NCProperties", "version=2,netcdf=selftest,hdf5=selftest"),
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
    import oisst_sst as osst

    assert lookup3(b"") == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago") == 0x17770551
    assert lookup3(b"Four score and seven years ago", 1) == 0xCD628161

    # Shuffle inverses against a hand-computed 2-byte example.
    sample = struct.pack("<3h", 0x0102, -999, 0x7F80)
    shuffled = shuffle(sample, 2)
    if shuffled != bytes([0x02, 0x19, 0x80, 0x01, 0xFC, 0x7F]):
        raise SystemExit("selftest: forward shuffle reference mismatch")
    if osst.unshuffle_slices(shuffled) != sample or osst.unshuffle_zip(shuffled) != sample:
        raise SystemExit("selftest: unshuffle reference mismatch")

    grid = synthetic_grid()
    for superblock in (0, 2):
        raw = build(grid, superblock=superblock)
        for index, unshuffle in (("name", osst.unshuffle_slices), ("creation_order", osst.unshuffle_zip)):
            payload, meta = osst.decode_grid(raw, ROW, index, unshuffle)
            if payload != grid:
                raise SystemExit(f"selftest: decoded grid differs (superblock {superblock}, {index})")
            if meta["checked_metadata_blocks"] < 10:
                raise SystemExit("selftest: too few checksummed blocks visited")
    profile = osst.grid_profile(grid)
    if profile["fill_cells"] != osst.LAND_FILL_CELLS or profile["ocean_min"] != -180:
        raise SystemExit(f"selftest: unexpected profile {profile}")

    good = build(grid)
    bad_row = dict(ROW, date="2020-01-16")
    expect_failure("wrong date", lambda: osst.decode_grid(good, bad_row, "name", osst.unshuffle_slices))
    expect_failure("preliminary title", lambda: osst.decode_grid(build(grid, title_suffix=" - Interim"), ROW, "name", osst.unshuffle_slices))
    expect_failure("shuffle element size 1", lambda: osst.decode_grid(build(grid, filters=[(2, (1,)), (1, (4,))], element=1), ROW, "name", osst.unshuffle_slices))
    expect_failure("deflate without shuffle", lambda: osst.decode_grid(build(grid, filters=[(1, (4,))], element=1), ROW, "name", osst.unshuffle_slices))
    expect_failure("extra fletcher32 filter", lambda: osst.decode_grid(build(grid, filters=[(2, (2,)), (1, (4,)), (3, ())]), ROW, "name", osst.unshuffle_slices))
    expect_failure("unsigned datatype", lambda: osst.decode_grid(build(grid, datatype=U16), ROW, "name", osst.unshuffle_slices))
    expect_failure("big-endian datatype", lambda: osst.decode_grid(build(grid, datatype=I16_BE), ROW, "name", osst.unshuffle_slices))
    expect_failure("wrong scale_factor", lambda: osst.decode_grid(build(grid, scale=0.001), ROW, "name", osst.unshuffle_slices))
    expect_failure("truncated chunk", lambda: osst.decode_grid(build(grid, stored_cut=7), ROW, "name", osst.unshuffle_slices))
    expect_failure("missing target link", lambda: osst.decode_grid(build(grid, target_name="sst_x"), ROW, "name", osst.unshuffle_slices))
    expect_failure("changed land mask", lambda: osst.grid_profile(synthetic_grid(land_cells=osst.LAND_FILL_CELLS - 1)))
    out_of_range = bytearray(grid)
    out_of_range[-2:] = struct.pack("<h", 4501)
    expect_failure("value above valid_max", lambda: osst.grid_profile(bytes(out_of_range)))
    out_of_range[-2:] = struct.pack("<h", -301)
    expect_failure("value below valid_min", lambda: osst.grid_profile(bytes(out_of_range)))
    flat = struct.pack("<h", osst.FILL) * osst.LAND_FILL_CELLS + struct.pack("<h", 1500) * (ROWS * COLS - osst.LAND_FILL_CELLS)
    expect_failure("constant ocean grid", lambda: osst.grid_profile(flat))
    expect_failure("all-fill grid", lambda: osst.grid_profile(struct.pack("<h", -999) * (ROWS * COLS)))
    for marker in (b"FHDB", b"FHIB", b"BTIN", b"OCHK", b"FRHP", b"BTHD", b"TREE"):
        corrupt = bytearray(good)
        pos = corrupt.find(marker) + (5 if marker == b"TREE" else 9)
        corrupt[pos] ^= 0x55
        indexes = ("name",) if marker == b"BTIN" else ("name", "creation_order")
        for index in indexes:
            expect_failure(f"corrupted {marker.decode()} ({index})",
                           lambda c=bytes(corrupt), i=index: osst.decode_grid(c, ROW, i, osst.unshuffle_slices))
    corrupt = bytearray(good)
    corrupt[corrupt.find(b"BTLF\x00\x06") + 7] ^= 0x01
    expect_failure("corrupted creation-order leaf", lambda: osst.decode_grid(bytes(corrupt), ROW, "creation_order", osst.unshuffle_zip))
    if not quiet:
        print("selftest=ok synthetic HDF5 int16 shuffle+deflate decode and rejection checks passed")


if __name__ == "__main__":
    main()
