#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py, icon_ivm.py and verify_samples.py.

Checks, without network or real data:

* lookup3 against the reference test vectors of Bob Jenkins' lookup3.c;
* the HDF5 byte-shuffle inverse against a hand-computed vector (with a
  trailing partial element) and a forward/inverse round trip;
* decode_chunk (inflate + unshuffle) and its failure modes;
* BlockStore (sparse 16 KiB block cache) against plain bytes, including
  MissingBlock for an absent block;
* an end-to-end synthetic NetCDF4-like file mirroring the ICON IVM-A L2-7
  layout (superblock v2, v2 object headers, identity global attributes,
  three chunked 512 x f8 shuffle+deflate velocity datasets with v1 chunk
  B-trees and a padded edge chunk): resolve() over bytes and over a
  BlockStore must agree, range decode must equal whole-file decode and the
  original values, the build and the independent verify decoders must
  produce the same bytes, the missing-value policy must drop exactly the NaN
  fill and keep out-of-range values, and wrong identity, wrong dtype and
  corrupted metadata must be rejected.
"""
from __future__ import annotations

import math
import shutil
import struct
import sys
import tempfile
import zlib
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
import icon_ivm  # noqa: E402
import verify_samples  # noqa: E402
from h5lite import UNDEF, BlockStore, H5Error, H5File, MissingBlock, lookup3  # noqa: E402

F64 = icon_ivm.F64LE
F64_BE = bytes.fromhex("11213f000800000000004000340b0034ff030000")
I32 = bytes.fromhex("100800000400000000002000")
NAN = float("nan")


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"selftest FAILED: {what}")


def expect_error(fn, exc_type, what: str) -> None:
    try:
        fn()
    except exc_type:
        return
    raise SystemExit(f"selftest FAILED: {what} was not rejected")


# ------------------------------------------------------------ unit checks
def test_lookup3() -> None:
    check(lookup3(b"") == 0xDEADBEEF, "lookup3 empty")
    check(lookup3(b"Four score and seven years ago") == 0x17770551, "lookup3 vector 1")
    check(lookup3(b"Four score and seven years ago", 1) == 0xCD628161, "lookup3 vector 2")


def test_shuffle() -> None:
    data = bytes(range(17))  # two 8-byte elements plus one trailing byte
    shuffled = bytes([0, 8, 1, 9, 2, 10, 3, 11, 4, 12, 5, 13, 6, 14, 7, 15, 16])
    check(h5lite.shuffle(data, 8) == shuffled, "forward shuffle vector")
    check(h5lite.unshuffle(shuffled, 8) == data, "unshuffle vector")
    check(verify_samples.unshuffle_planes(shuffled[:16], 8) == data[:16], "verify unshuffle vector")
    blob = bytes((i * 37 + 11) & 0xFF for i in range(4096))
    check(h5lite.unshuffle(h5lite.shuffle(blob, 8), 8) == blob, "shuffle round trip")


def test_decode_chunk() -> None:
    values = [math.sin(i / 7.0) * 300.0 + i * 1e-9 for i in range(512)]
    values[5] = NAN
    raw = struct.pack("<512d", *values)
    stored = zlib.compress(h5lite.shuffle(raw, 8), 6)
    filters = [(2, 1, (8,)), (1, 1, (6,))]
    check(h5lite.decode_chunk(stored, filters, 0, 8, 4096) == raw, "decode_chunk round trip")
    check(verify_samples.decode_chunk_independent(stored, 8, 4096) == raw, "verify chunk decode")
    expect_error(lambda: h5lite.decode_chunk(stored, filters, 1, 8, 4096), H5Error, "nonzero filter mask")
    expect_error(lambda: h5lite.decode_chunk(stored, filters, 0, 8, 4088), H5Error, "wrong chunk size")
    expect_error(lambda: h5lite.decode_chunk(stored + b"x", filters, 0, 8, 4096), H5Error, "trailing bytes")
    expect_error(lambda: h5lite.decode_chunk(stored[:-3], filters, 0, 8, 4096), H5Error, "truncated deflate")
    expect_error(lambda: h5lite.decode_chunk(stored, [(4, 1, ())], 0, 8, 4096), H5Error, "unknown filter")


def write_blocks(raw: bytes, directory: Path, block_size: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range((len(raw) + block_size - 1) // block_size):
        (directory / f"blk_{index:06d}.bin").write_bytes(raw[index * block_size:(index + 1) * block_size])


def test_blockstore(tmp: Path) -> None:
    raw = bytes((i * 131 + 7) & 0xFF for i in range(50_000))
    write_blocks(raw, tmp / "bs", 16384)
    store = BlockStore(tmp / "bs", len(raw), 16384)
    check(len(store) == len(raw), "BlockStore length")
    for a, b in ((0, 10), (16380, 16390), (16384, 32768), (49_990, 50_000), (100, 40_000)):
        check(store[a:b] == raw[a:b], f"BlockStore slice {a}:{b}")
    check(store[16383] == raw[16383] and store[16384] == raw[16384], "BlockStore int index")
    check(h5lite.unpack_from("<QI", store, 16380) == struct.unpack_from("<QI", raw, 16380), "unpack_from")
    (tmp / "bs" / "blk_000001.bin").unlink()
    try:
        store2 = BlockStore(tmp / "bs", len(raw), 16384)
        store2[16000:17000]
        raise SystemExit("selftest FAILED: missing block not detected")
    except MissingBlock as exc:
        check(exc.index == 1, "MissingBlock index")


# --------------------------------------------------- synthetic HDF5 writer
def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def message(mtype: int, payload: bytes) -> bytes:
    return struct.pack("<BHB", mtype, len(payload), 0) + payload


def ohdr(messages: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(message(t, p) for t, p in messages)
    return checksummed(b"OHDR" + bytes([2, 0x02]) + struct.pack("<I", len(body)) + body)


def dataspace(dims: tuple[int, ...]) -> bytes:
    if not dims:
        return bytes([2, 0, 0, 0])
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + data)


def str_attr(name: str, value: str) -> bytes:
    raw = value.encode()
    return attribute(name, bytes([0x13, 0, 0, 0]) + struct.pack("<I", len(raw)), (), raw)


def f64_attr(name: str, value: float) -> bytes:
    return attribute(name, F64, (1,), struct.pack("<d", value))


def i32_attr(name: str, value: int) -> bytes:
    return attribute(name, I32, (1,), struct.pack("<i", value))


def link(name: str, addr: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0, len(raw)]) + raw + struct.pack("<Q", addr)


def tree_leaf(entries: list[tuple[int, int, int]], final_offset: int) -> bytes:
    body = b"TREE" + bytes([1, 0]) + struct.pack("<H", len(entries)) + struct.pack("<QQ", UNDEF, UNDEF)
    for size, offset, addr in entries:
        body += struct.pack("<IIQQ", size, 0, offset, 0) + struct.pack("<Q", addr)
    body += struct.pack("<IIQQ", 0, 0, final_offset, 0)
    return body


def component_values(n: int, phase: float) -> list[float]:
    out = []
    for i in range(n):
        if 20_000 <= i < 23_000 or i % 997 == 0:
            out.append(NAN)  # shared fill pattern
        else:
            out.append(250.0 * math.sin(i / 600.0 + phase) + 0.37 * math.cos(i * 1.7) + i * 1e-7)
    pos = min(30_001, n - 3)
    out[pos] = 912.5  # outside Valid_Min/Max: kept
    out[pos + 1] = -733.25
    return out


def build_file(n: int, instrument: str = "IVM-A", datatype: bytes = F64, chunk: int = 512) -> tuple[bytes, dict]:
    buf = bytearray(b"\x00" * 48)  # superblock placeholder
    nchunks = (n + chunk - 1) // chunk
    var_headers = {}
    originals = {}
    pending_btrees = []
    for ci, (component, var) in enumerate(icon_ivm.COMPONENTS):
        values = component_values(n, phase=ci * 1.3)
        originals[component] = struct.pack(f"<{n}d", *values)
        padded = originals[component] + b"\x00" * (nchunks * chunk * 8 - n * 8)
        entries = []
        for c in range(nchunks):
            stored = zlib.compress(h5lite.shuffle(padded[c * chunk * 8:(c + 1) * chunk * 8], 8), 6)
            entries.append((len(stored), c * chunk, len(buf)))
            buf += stored
        while len(buf) % 8:
            buf.append(0)
        btree_addr = len(buf)
        buf += tree_leaf(entries, nchunks * chunk)
        pending_btrees.append(btree_addr)
        layout = bytes([3, 2, 2]) + struct.pack("<Q", btree_addr) + struct.pack("<II", chunk, 8)
        filters = bytes([2, 2]) + struct.pack("<HHHI", 2, 1, 1, 8) + struct.pack("<HHHI", 1, 1, 1, 6)
        msgs = [
            (0x01, dataspace((n,))),
            (0x03, datatype),
            (0x0B, filters),
            (0x08, layout),
            (0x0C, str_attr("Units", "m/s")),
            (0x0C, str_attr("Depend_0", "Epoch")),
            (0x0C, str_attr("Var_Type", "data")),
            (0x0C, f64_attr("FillVal", NAN)),
            (0x0C, f64_attr("Valid_Min", -500.0)),
            (0x0C, f64_attr("Valid_Max", 500.0)),
        ]
        while len(buf) % 8:
            buf.append(0)
        var_headers[var] = len(buf)
        buf += ohdr(msgs)
    row = {"date": "20210407", "version": "v06r003", "key": "synthetic", "size_bytes": 0}
    root_msgs = [(0x06, link(var, addr)) for var, addr in var_headers.items()]
    root_msgs += [
        (0x0C, str_attr("Instrument", instrument)),
        (0x0C, str_attr("LogicalSource", "ICON_L2-7_IVM-A")),
        (0x0C, str_attr("Logical_File_ID", "ICON_L2-7_IVM-A_2021-04-07_v06r003")),
        (0x0C, str_attr("Project", "NASA > ICON")),
        (0x0C, str_attr("Rules_of_Use", "Public Data for Scientific Use")),
        (0x0C, str_attr("Time_Resolution", "1 Second")),
        (0x0C, i32_attr("Data_Version_Major", 6)),
        (0x0C, f64_attr("Data_Version", 6.003)),
    ]
    while len(buf) % 8:
        buf.append(0)
    root_addr = len(buf)
    buf += ohdr(root_msgs)
    buf += b"\x00" * 40000  # trailing payload so metadata spans several blocks
    eof = len(buf)
    sb = b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root_addr)
    buf[0:48] = checksummed(sb)
    row["size_bytes"] = eof
    return bytes(buf), {"row": row, "originals": originals, "root_addr": root_addr}


def test_end_to_end(tmp: Path, n: int = 86_404, chunk: int = 512) -> None:
    raw, meta = build_file(n, chunk=chunk)
    row = meta["row"]
    plan_bytes = icon_ivm.resolve(raw, row)
    check(plan_bytes["records"] == n, "synthetic record count")
    meta_dir = tmp / f"day_{n}" / "meta"
    write_blocks(raw, meta_dir, icon_ivm.BLOCK_SIZE)
    store = BlockStore(meta_dir, len(raw), icon_ivm.BLOCK_SIZE)
    plan_store = icon_ivm.resolve(store, row)
    for component, _var in icon_ivm.COMPONENTS:
        a, b = plan_bytes["components"][component], plan_store["components"][component]
        check(a["chunks"] == b["chunks"] and a["span_start"] == b["span_start"], f"{component} plans agree")
        span = raw[a["span_start"]:a["span_end"]]
        ranged = icon_ivm.decode_component(span, b)
        check(ranged == icon_ivm.decode_from_file(raw, a), f"{component} range == whole-file decode")
        original = meta["originals"][component]
        same = all((x == y) or (x != x and y != y) for x, y in zip(array("d", ranged), array("d", original)))
        check(same and len(ranged) == len(original), f"{component} decode equals original values")
        independent = verify_samples.decode_span_independent(span, a["span_start"], a["chunks"], n, chunk)
        check(independent == ranged, f"{component} independent verify decode")
        kept, stats = icon_ivm.apply_policy(ranged)
        expected_nan = sum(1 for i in range(n) if 20_000 <= i < 23_000 or i % 997 == 0)
        check(stats["nan_dropped"] == expected_nan, f"{component} NaN fill dropped")
        check(stats["outside_valid_range"] == 2 and 912.5 in kept and -733.25 in kept, "out-of-range kept")
        vkept = verify_samples.policy_independent(independent)
        check(vkept == kept.tobytes(), f"{component} verify policy agrees")
    # A block the parser needs must surface as MissingBlock.
    needed = sorted(store.used)
    victim = needed[-1]
    (meta_dir / f"blk_{victim:06d}.bin").unlink()
    expect_error(lambda: icon_ivm.resolve(BlockStore(meta_dir, len(raw), icon_ivm.BLOCK_SIZE), row),
                 MissingBlock, "missing metadata block")
    # Identity, dtype and checksum failures.
    raw_b, _ = build_file(n, instrument="IVM-B")
    expect_error(lambda: icon_ivm.resolve(raw_b, dict(row, size_bytes=len(raw_b))), H5Error, "IVM-B identity")
    raw_be, _ = build_file(n, datatype=F64_BE)
    expect_error(lambda: icon_ivm.resolve(raw_be, dict(row, size_bytes=len(raw_be))), H5Error, "big-endian dtype")
    corrupt = bytearray(raw)
    corrupt[meta["root_addr"] + 40] ^= 0x01
    expect_error(lambda: icon_ivm.resolve(bytes(corrupt), row), H5Error, "corrupted root header")
    expect_error(lambda: icon_ivm.apply_policy(struct.pack("<3d", 1.0, float("inf"), 2.0)), H5Error, "infinite value")


def main() -> int:
    test_lookup3()
    test_shuffle()
    test_decode_chunk()
    tmp = Path(tempfile.mkdtemp(prefix="icon_ivm_selftest_"))
    try:
        test_blockstore(tmp)
        test_end_to_end(tmp)
        test_end_to_end(tmp, n=5_600, chunk=510)  # partial-day file layout (20210903)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest ok: lookup3, shuffle, decode_chunk, BlockStore, synthetic IVM-A file end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
