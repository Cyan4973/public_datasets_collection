#!/usr/bin/env python3
"""Self-test for sxs_h5 / blockstore / sxs_modes on a synthetic HDF5 file.

The synthetic file mirrors the SXS layout: superblock v0, version-1 object
headers, a root symbol-table group holding ``Extrapolated_N2.dir`` (itself a
symbol-table group whose B-tree has two levels and several SNODs), group
attributes, and float64 ``[N, 3]`` datasets chunked ``(C, 1)`` with the
shuffle+deflate pipeline and multi-level chunk B-trees (N not a multiple of C,
so edge chunks carry padding).  It then runs the planner -> range fetch ->
decode loop entirely offline and checks corruption is rejected.
"""
from __future__ import annotations

import hashlib
import math
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sxs_h5  # noqa: E402
import blockstore  # noqa: E402
import sxs_modes  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF


def pad8(b: bytes) -> bytes:
    return b + b"\x00" * ((-len(b)) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)  # superblock placeholder

    def alloc(self, data: bytes, align: int = 8) -> int:
        self.buf += b"\x00" * ((-len(self.buf)) % align)
        addr = len(self.buf)
        self.buf += data
        return addr

    def reserve(self, size: int) -> int:
        return self.alloc(b"\x00" * size)

    def put(self, addr: int, data: bytes) -> None:
        self.buf[addr:addr + len(data)] = data


def msg(mtype: int, payload: bytes, flags: int = 0) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", mtype, len(payload), flags) + payload


def object_header(messages: list[bytes]) -> bytes:
    body = b"".join(messages)
    return struct.pack("<BBHII4x", 1, 0, len(messages), 1, len(body)) + body


F64_TYPE = bytes([0x11, 0x20, 0x3F, 0x00]) + struct.pack("<IHHBBBBI", 8, 0, 64, 52, 11, 0, 52, 1023)


def dataspace(dims: tuple[int, ...]) -> bytes:
    return struct.pack("<BBBB4x", 1, len(dims), 0, 0) + b"".join(struct.pack("<Q", d) for d in dims)


def filters_msg() -> bytes:
    out = struct.pack("<BB6x", 1, 2)
    for fid, name, vals in ((2, b"shuffle\x00", (8,)), (1, b"deflate\x00", (6,))):
        out += struct.pack("<4H", fid, len(name), 1, len(vals)) + pad8(name)
        out += b"".join(struct.pack("<I", v) for v in vals) + (b"\x00" * 4 if len(vals) % 2 else b"")
    return out


def attribute(name: str, values: list[float]) -> bytes:
    nb = name.encode() + b"\x00"
    sp = dataspace((len(values),))
    return (struct.pack("<BBHHH", 1, 0, len(nb), len(F64_TYPE), len(sp)) + pad8(nb) + pad8(F64_TYPE)
            + pad8(sp) + struct.pack(f"<{len(values)}d", *values))


def write_chunk_btree(w: Writer, entries: list[tuple[int, int, tuple[int, int], int]], dims: tuple[int, int],
                      fanout: int) -> int:
    """entries: (size, mask, (row, col), addr) sorted; returns root address (2 levels if needed)."""
    def key(size: int, mask: int, off: tuple[int, int]) -> bytes:
        return struct.pack("<II3Q", size, mask, off[0], off[1], 0)

    final = key(0, 0, (dims[0], dims[1]))

    def node(level: int, items: list[tuple[bytes, int]], last: bytes) -> bytes:
        out = b"TREE" + struct.pack("<BBHQQ", 1, level, len(items), UNDEF, UNDEF)
        for k, child in items:
            out += k + struct.pack("<Q", child)
        return out + last

    leaves = [entries[i:i + fanout] for i in range(0, len(entries), fanout)]
    if len(leaves) == 1:
        return w.alloc(node(0, [(key(s, m, o), a) for s, m, o, a in leaves[0]], final))
    leaf_addrs = []
    for i, group in enumerate(leaves):
        nxt = leaves[i + 1][0] if i + 1 < len(leaves) else None
        last = key(0, 0, nxt[2]) if nxt else final
        leaf_addrs.append((key(group[0][0], group[0][1], group[0][2]),
                           w.alloc(node(0, [(key(s, m, o), a) for s, m, o, a in group], last))))
    return w.alloc(node(1, leaf_addrs, final))


def write_dataset(w: Writer, rows: list[tuple[float, float, float]], chunk_rows: int, fanout: int) -> int:
    n = len(rows)
    entries = []
    for col in range(3):
        for r0 in range(0, n, chunk_rows):
            vals = [rows[r][col] if r < n else 0.0 for r in range(r0, r0 + chunk_rows)]
            raw = struct.pack(f"<{chunk_rows}d", *vals)
            stored = zlib.compress(sxs_h5.shuffle(raw, 8), 6)
            entries.append((len(stored), 0, (r0, col), w.alloc(stored, 1)))
    entries.sort(key=lambda e: e[2])
    btree = write_chunk_btree(w, entries, (n, 3), fanout)
    layout = struct.pack("<BBBQ3I", 3, 2, 3, btree, chunk_rows, 1, 8)
    hdr = object_header([msg(0x01, dataspace((n, 3))), msg(0x03, F64_TYPE), msg(0x0B, filters_msg()),
                         msg(0x08, layout)])
    return w.alloc(hdr)


def write_group(w: Writer, links: dict[str, int], snod_cap: int, attrs: list[bytes]) -> int:
    names = sorted(links)
    heap_data = bytearray(b"\x00" * 8)
    offsets = {}
    for name in names:
        offsets[name] = len(heap_data)
        heap_data += pad8(name.encode() + b"\x00")
    data_addr = w.alloc(bytes(heap_data))
    heap_addr = w.alloc(b"HEAP" + struct.pack("<B3xQQQ", 0, len(heap_data), UNDEF, data_addr))
    groups = [names[i:i + snod_cap] for i in range(0, len(names), snod_cap)]
    children = []
    for g in groups:
        body = b"SNOD" + struct.pack("<BBH", 1, 0, len(g))
        for name in g:
            body += struct.pack("<QQII16x", offsets[name], links[name], 0, 0)
        children.append((offsets[g[-1]], w.alloc(body)))

    def gnode(level: int, items: list[tuple[int, int]], first_key: int) -> bytes:
        out = b"TREE" + struct.pack("<BBHQQ", 0, level, len(items), UNDEF, UNDEF) + struct.pack("<Q", first_key)
        for k, child in items:
            out += struct.pack("<QQ", child, k)
        return out

    if len(children) <= 2:
        root = w.alloc(gnode(0, [(k, c) for k, c in children], 0))
    else:  # two leaf group nodes under one internal node
        half = (len(children) + 1) // 2
        a = w.alloc(gnode(0, children[:half], 0))
        b = w.alloc(gnode(0, children[half:], children[half - 1][0]))
        root = w.alloc(gnode(1, [(children[half - 1][0], a), (children[-1][0], b)], 0))
    hdr = object_header([msg(0x11, struct.pack("<QQ", root, heap_addr))] + [msg(0x0C, a) for a in attrs])
    return w.alloc(hdr)


def build_file(n: int, chunk_rows: int) -> tuple[bytes, dict]:
    w = Writer()
    truth = {}
    links = {}
    t = [-100.0 + 0.37 * i + 1e-3 * math.sin(i) for i in range(n)]
    for l in range(2, 6):
        for m in range(-l, l + 1):
            amp = 0.3 / (l * l) * (1 + 0.1 * m)
            rows = [(t[i], amp * math.cos(0.01 * (m + 3) * i), -amp * math.sin(0.01 * (l + 1) * i) + 1e-9 * i)
                    for i in range(n)]
            truth[(l, m)] = rows
            links[f"Y_l{l}_m{m}.dat"] = write_dataset(w, rows, chunk_rows, fanout=5 if (l + m) % 2 else 64)
    attrs = [attribute("space_translation", [1e-4, -2e-2, 3e-6]), attribute("boost_velocity", [-3e-7, 5e-6, -2e-8])]
    n2 = write_group(w, links, snod_cap=8, attrs=attrs)
    other = write_group(w, {"Y_l2_m2.dat": links["Y_l2_m2.dat"]}, snod_cap=8, attrs=[])
    root = write_group(w, {"Extrapolated_N2.dir": n2, "Extrapolated_N3.dir": other}, snod_cap=8, attrs=[])
    w.buf += b"\x00" * 300000  # tail padding so the file spans many blocks
    eof = len(w.buf)
    root_msgs = sxs_h5.H5File  # noqa: F841 (documentation only)
    sb = (sxs_h5.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
          + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII16x", 0, root, 1, 0))
    assert len(sb) == 96
    w.put(0, sb)
    return bytes(w.buf), truth


def expect_error(fn, what: str) -> None:
    try:
        fn()
    except (sxs_h5.H5Error, SystemExit, ValueError):
        return
    raise AssertionError(f"expected failure: {what}")


def main() -> int:
    # 1. shuffle round trip and coalescing
    raw = struct.pack("<7d", *[1.5, -2.25, 3e-300, 4e300, 0.0, -0.0, 7.0]) + b"xyz"
    assert sxs_h5.unshuffle(sxs_h5.shuffle(raw, 8), 8) == raw
    assert sxs_modes.coalesce([1, 2, 3, 6, 10, 11]) == [(1, 6), (10, 11)]
    assert sxs_modes.coalesce(list(range(0, 200)))[0] == (0, 63)

    n, chunk_rows = 1234, 300
    data, truth = build_file(n, chunk_rows)
    f = sxs_h5.H5File(data, len(data))
    root = f.group_links(f.root_addr)
    assert set(root) == {"Extrapolated_N2.dir", "Extrapolated_N3.dir"}, root
    g = f.resolve("Extrapolated_N2.dir")
    links = f.group_links(g)
    assert len(links) == 32, len(links)
    attrs = f.attributes(g)
    assert attrs["boost_velocity"] == [-3e-7, 5e-6, -2e-8], attrs
    for (l, m), rows in truth.items():
        info = f.dataset(links[f"Y_l{l}_m{m}.dat"])
        assert info["shape"] == (n, 3) and info["chunk_dims"] == (chunk_rows, 1)
        assert [x[0] for x in info["filters"]] == [2, 1]
        got = f.read_array_bytes(info)
        want = b"".join(struct.pack("<3d", *r) for r in rows)
        assert got == want, (l, m)
    print(f"selftest: direct decode ok ({len(truth)} datasets, {len(data)} bytes)")

    # 2. offline planner -> fetch -> decode loop through the block store
    with tempfile.TemporaryDirectory(prefix="sxs_selftest_") as tmp:
        tmp = Path(tmp)
        sims = tmp / "sims.tsv"
        sims.write_text("\t".join(["sxs_id", "record_id", "lev", "h5_key", "h5_size", "h5_md5", "meta_key",
                                   "meta_size", "meta_md5"]) + "\n" + "\t".join(
            ["SXS:BBH:9999", "1", "3", "Lev3/x.h5", str(len(data)), hashlib.md5(data).hexdigest(),
             "Lev3/metadata.json", "1", "0"]) + "\n", encoding="utf-8")
        downloads = tmp / "dl"
        req = tmp / "req.tsv"

        class Args:
            pass

        a = Args()
        a.sims, a.downloads, a.requests = str(sims), str(downloads), str(req)
        rounds = fetched = 0
        while sxs_modes.cmd_plan(a) == 3:
            rounds += 1
            assert rounds < 30, "planner did not converge"
            for line in req.read_text().splitlines():
                _url, start, end, bdir, first, total = line.split("\t")
                start, end, first = int(start), int(end), int(first)
                assert int(total) == len(data) and start == first * blockstore.BLOCK_SIZE
                Path(bdir).mkdir(parents=True, exist_ok=True)
                piece = data[start:end + 1]
                for k in range(0, len(piece), blockstore.BLOCK_SIZE):
                    Path(bdir, f"blk_{first + k // blockstore.BLOCK_SIZE:06d}.bin").write_bytes(
                        piece[k:k + blockstore.BLOCK_SIZE])
                    fetched += 1
        sim = sxs_modes.read_sims(sims)[0]
        decoded = sxs_modes.decode_sim(sim, downloads)
        assert decoded["rows"] == n and len(decoded["modes"]) == 21
        for (l, m), reim in decoded["modes"].items():
            rows = truth[(l, m)]
            assert list(reim[0::2]) == [r[1] for r in rows] and list(reim[1::2]) == [r[2] for r in rows]
        assert list(decoded["time"]) == [r[0] for r in truth[(2, 2)]]
        total_blocks = -(-len(data) // blockstore.BLOCK_SIZE)
        print(f"selftest: planner converged in {rounds} rounds, fetched {fetched}/{total_blocks} blocks; decode ok")

        # 3. corruption must be rejected: flip a byte inside one stored chunk
        info = f.dataset(links["Y_l3_m1.dat"])
        size, _mask, _off, addr = f.chunk_entries(info["chunk_btree"], 2)[0]
        bad = bytearray(data)
        bad[addr + size // 2] ^= 0xFF
        expect_error(lambda: sxs_h5.H5File(bytes(bad)).read_array_bytes(
            sxs_h5.H5File(bytes(bad)).dataset(links["Y_l3_m1.dat"])), "corrupted deflate chunk")
        # a missing chunk entry in the index must be rejected
        info2 = dict(info)
        orig = sxs_h5.H5File.chunk_entries
        sxs_h5.H5File.chunk_entries = lambda self, b, r: orig(self, b, r)[1:]
        try:
            expect_error(lambda: f.read_array_bytes(info2), "missing chunk")
        finally:
            sxs_h5.H5File.chunk_entries = orig
        expect_error(lambda: sxs_h5.H5File(data[:8] + b"\x02" + data[9:]), "superblock v2")
    print("selftest: corruption checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
