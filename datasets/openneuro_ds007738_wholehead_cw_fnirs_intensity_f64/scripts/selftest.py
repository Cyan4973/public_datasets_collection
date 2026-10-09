#!/usr/bin/env python3
"""Synthetic end-to-end self-test of the SNIRF decode path and payload policy.

Writes a tiny SNIRF-like HDF5 file byte by byte: superblock v0, v1 object
headers (one with a continuation block), symbol-table groups (the data1 group
behind a two-level group B-tree), a variable-length formatVersion string in a
global heap, a contiguous H5T_IEEE_F64LE (T x C) dataTimeSeries, a time
vector, C measurementList groups of scalar 64-bit integers, /nirs/probe/
wavelengths and ignored aux/metaDataTags groups. The file is exposed through a
sparse BlockStore exactly as download.sh caches it; the real read_layout must
return the exact data range (bytes compared bit for bit), report MissingBlock
for an absent block, and reject every corrupted variant. payload_stats must
accept a canonical-NaN first frame and reject the other missing-value
violations, and the scale test must separate integer-times-constant channels
from generic float64.
"""

from __future__ import annotations

import hashlib
import random
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402
import snirf_fnirs as S  # noqa: E402
from scale_test import ratio_test  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF
F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")
VLEN_STR = bytes.fromhex("1901010010000000") + bytes.fromhex("1300000001000000")
C = 6
T = 40
LAYOUT = [(1, 1, 1, 1, 0), (1, 2, 1, 1, 0), (2, 2, 1, 1, 0), (1, 1, 2, 1, 0), (1, 2, 2, 1, 0), (2, 2, 2, 1, 0)]


def pad8(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)

    def add(self, data: bytes) -> int:
        self.buf += b"\0" * (-len(self.buf) % 8)
        address = len(self.buf)
        self.buf += data
        return address


def message(kind: int, payload: bytes) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", kind, len(payload), 0) + payload


def object_header(w: Writer, messages: list[tuple[int, bytes]], split: int | None = None) -> int:
    if split is None:
        body = b"".join(message(k, p) for k, p in messages)
        return w.add(struct.pack("<BBHII4x", 1, 0, len(messages), 1, len(body)) + body)
    tail = b"".join(message(k, p) for k, p in messages[split:])
    tail_address = w.add(tail)
    head = b"".join(message(k, p) for k, p in messages[:split])
    head += message(H.MSG_CONTINUATION, struct.pack("<QQ", tail_address, len(tail)))
    return w.add(struct.pack("<BBHII4x", 1, 0, len(messages) + 1, 1, len(head)) + head)


def local_heap(w: Writer, names: list[str]) -> tuple[int, dict[str, int]]:
    data = bytearray(8)
    offsets = {}
    for name in names:
        offsets[name] = len(data)
        data += pad8(name.encode() + b"\0")
    data_address = w.add(bytes(data))
    return w.add(b"HEAP" + bytes(4) + struct.pack("<QQQ", len(data), UNDEF, data_address)), offsets


def group(w: Writer, entries: list[tuple[str, int]], two_level: bool = False) -> tuple[int, int]:
    entries = sorted(entries)
    heap, offsets = local_heap(w, [name for name, _ in entries])

    def leaf(chunk: list[tuple[str, int]]) -> int:
        body = bytearray(b"SNOD" + bytes([1, 0]) + struct.pack("<H", len(chunk)))
        for name, address in chunk:
            body += struct.pack("<QQII16s", offsets[name], address, 0, 0, b"\0" * 16)
        child = w.add(bytes(body))
        node = b"TREE" + bytes([0, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF)
        return w.add(node + struct.pack("<QQQ", 0, child, offsets[chunk[-1][0]]))

    if not two_level:
        return leaf(entries), heap
    half = len(entries) // 2
    left, right = leaf(entries[:half]), leaf(entries[half:])
    node = b"TREE" + bytes([0, 1]) + struct.pack("<HQQ", 2, UNDEF, UNDEF)
    node += struct.pack("<QQQQQ", 0, left, offsets[entries[half - 1][0]], right, offsets[entries[-1][0]])
    return w.add(node), heap


def group_header(w: Writer, entries: list[tuple[str, int]], two_level: bool = False) -> int:
    btree, heap = group(w, entries, two_level)
    return object_header(w, [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", btree, heap))])


SCALAR_SPACE = bytes([1, 0, 0, 0, 0, 0, 0, 0])


def contiguous(w: Writer, raw: bytes, dims: tuple[int, ...], dtype: bytes, extra: list[tuple[int, bytes]] = (),
               size_override: int | None = None, split: int | None = None) -> int:
    address = w.add(raw)
    if dims:
        space = struct.pack("<BBBB4x" + "Q" * len(dims), 1, len(dims), 0, 0, *dims)
    else:
        space = SCALAR_SPACE
    layout = struct.pack("<BBQQ", 3, 1, address, len(raw) if size_override is None else size_override)
    msgs = [(H.MSG_DATASPACE, space), (H.MSG_DATATYPE, dtype), (H.MSG_LAYOUT, layout)] + list(extra)
    return object_header(w, msgs, split=split)


STORED_NAN = struct.pack("<Q", S.CANONICAL_NAN)


def with_nans(raw: bytes, positions) -> bytes:
    """Overwrite values with the stored NaN bit pattern (Python packs float("nan") as 0x7FF8...)."""
    out = bytearray(raw)
    for i in positions:
        out[8 * i : 8 * i + 8] = STORED_NAN
    return bytes(out)


def synthetic_matrix() -> list[float]:
    """Integer counts times one scale per channel; frame 0 partly canonical NaN."""
    rng = random.Random(7738)
    scales = [rng.uniform(1e-7, 1e-5) for _ in range(C)]
    values = []
    for t in range(T):
        for c in range(C):
            if t == 0 and c < 4:
                values.append(0.0)  # replaced by the stored NaN pattern in make_file
            else:
                values.append(rng.randrange(1000, 1 << 22) * scales[c])
    return values


def make_file(mutate: str = "") -> tuple[bytes, bytes]:
    values = synthetic_matrix()
    raw = with_nans(struct.pack(f"<{len(values)}d", *values), range(4))
    w = Writer()
    strings = ["1.0", "1.1", "sub-xx"]
    gbody = bytearray()
    index = {}
    for number, text in enumerate(strings, 1):
        b = text.encode()
        gbody += struct.pack("<HHIQ", number, 1, 0, len(b)) + pad8(b)
        index[text] = number
    gbody += struct.pack("<HHIQ", 0, 0, 0, 16)
    gaddr = w.add(b"GCOL" + bytes([1, 0, 0, 0]) + struct.pack("<Q", 16 + len(gbody)) + bytes(gbody))

    def vstr_dataset(text: str) -> int:
        data_address = w.add(struct.pack("<IQI", len(text.encode()), gaddr, index[text]))
        layout = struct.pack("<BBQQ", 3, 1, data_address, 16)
        return object_header(w, [(H.MSG_DATASPACE, SCALAR_SPACE), (H.MSG_DATATYPE, VLEN_STR), (H.MSG_LAYOUT, layout)])

    channels = C + 1 if mutate == "channels" else C
    dtype = F32LE if mutate == "f32_dtype" else H.H5T_IEEE_F64LE
    if mutate == "f32_dtype":
        raw32 = struct.pack(f"<{len(values)}f", *values)
        payload = raw32
    elif mutate == "channels":
        payload = raw + bytes(8 * T)
    else:
        payload = raw
    extra = []
    if mutate == "filters":
        deflate = struct.pack("<HHHH", 1, 8, 1, 1) + b"deflate\0" + struct.pack("<II", 4, 0)
        extra.append((H.MSG_FILTER, struct.pack("<BB6x", 1, 1) + deflate))
    size_override = len(payload) - 8 if mutate == "size_mismatch" else None
    dts = contiguous(w, payload, (T, channels), dtype, extra, size_override, split=2)
    time = contiguous(w, struct.pack(f"<{T}d", *[0.11125 * i for i in range(T)]), (T,), H.H5T_IEEE_F64LE)
    layout = [list(row) for row in LAYOUT]
    if mutate == "datatype2":
        layout[3][3] = 2
    if mutate == "swap_order":
        layout[1], layout[2] = layout[2], layout[1]
    entries = [("dataTimeSeries", dts), ("time", time)]
    count = C - 1 if mutate == "missing_ml" else C
    for number in range(1, count + 1):
        row = layout[number - 1]
        fields = [(name, contiguous(w, struct.pack("<q", value), (), S.H5T_STD_U64LE))
                  for name, value in zip(S.ML_FIELDS, row)]
        fields.append(("wavelengthActual", contiguous(w, struct.pack("<d", 760.5), (), H.H5T_IEEE_F64LE)))
        entries.append((f"measurementList{number}", group_header(w, fields)))
    data1 = group_header(w, entries, two_level=True)
    wl = (760.0, 830.0) if mutate == "wavelengths" else (760.0, 850.0)
    probe = group_header(w, [("wavelengths", contiguous(w, struct.pack("<2d", *wl), (2,), H.H5T_IEEE_F64LE)),
                             ("sourcePos3D", contiguous(w, struct.pack("<6d", *range(6)), (2, 3), H.H5T_IEEE_F64LE))])
    tags = group_header(w, [("SubjectID", vstr_dataset("sub-xx"))])
    aux = group_header(w, [("dataTimeSeries", contiguous(w, struct.pack(f"<{T}d", *range(T)), (T,), H.H5T_IEEE_F64LE))])
    nirs_entries = [("data1", data1), ("probe", probe), ("metaDataTags", tags), ("aux1", aux)]
    if mutate == "data2":
        nirs_entries.append(("data2", group_header(w, [("time", time)])))
    nirs = group_header(w, nirs_entries)
    version = vstr_dataset("1.1" if mutate == "format_version" else "1.0")
    root_btree, root_heap = group(w, [("formatVersion", version), ("nirs", nirs)])
    root = object_header(w, [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", root_btree, root_heap))])
    w.buf += b"\0" * (-len(w.buf) % 8)
    superblock = (H.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
                  + struct.pack("<QQQQ", 0, UNDEF, len(w.buf), UNDEF)
                  + struct.pack("<QQII", 0, root, 1, 0) + struct.pack("<QQ", root_btree, root_heap))
    assert len(superblock) == 96
    w.buf[0:96] = superblock
    return bytes(w.buf), raw


def store_blocks(payload: bytes, directory: Path, block_size: int, skip: set[int] = frozenset()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for number, start in enumerate(range(0, len(payload), block_size)):
        if number not in skip:
            (directory / f"blk_{number:06d}.bin").write_bytes(payload[start : start + block_size])


def layout_of(payload: bytes, root: Path, block_size: int = 1024) -> dict[str, object]:
    store_blocks(payload, root, block_size)
    return S.read_layout(H.BlockStore(root, len(payload), block_size), len(payload))


def expect_layout_failure(label: str, payload: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="snirf_selftest_") as tmp:
        try:
            layout_of(payload, Path(tmp))
        except ValueError as exc:
            print(f"selftest reject_ok case={label} reason={str(exc)[:100]!r}")
            return
    raise SystemExit(f"selftest FAILED: corrupted case {label!r} was accepted")


def expect_payload_failure(label: str, raw: bytes, time_points: int) -> None:
    try:
        S.payload_stats(raw, time_points)
    except ValueError as exc:
        print(f"selftest reject_ok case={label} reason={str(exc)[:100]!r}")
        return
    raise SystemExit(f"selftest FAILED: payload case {label!r} was accepted")


def main() -> int:
    S.CHANNELS = C
    S.MIN_TIME_POINTS = 10
    S.MAX_NAN_FRACTION = 0.05  # 12 of 240 synthetic values; the base file has 4
    S.LAYOUT_SHA256 = hashlib.sha256(S.channel_table_text(LAYOUT).encode()).hexdigest()
    payload, raw = make_file()
    with tempfile.TemporaryDirectory(prefix="snirf_selftest_") as tmp:
        root = Path(tmp)
        store_blocks(payload, root, 1024, skip={0})
        try:
            S.read_layout(H.BlockStore(root, len(payload), 1024), len(payload))
        except H.MissingBlock as missing:
            print(f"selftest missing_block_ok block={missing.index}")
        else:
            raise SystemExit("selftest FAILED: missing superblock block was not reported")
        layout = layout_of(payload, root)
    start = int(layout["data_address"])
    extracted = payload[start : start + int(layout["data_bytes"])]
    if extracted != raw or layout["time_points"] != T or layout["channels"] != C:
        raise SystemExit("selftest FAILED: dataTimeSeries range not recovered bit for bit")
    print(f"selftest decode_ok address={start} shape=({T},{C}) bytes={len(extracted)}")
    stats = S.payload_stats(extracted, T)
    if stats["nan_count"] != 4 or stats["nan_rows"] != [0] or stats["negative_count"] != 0:
        raise SystemExit(f"selftest FAILED: payload stats {stats}")
    if stats["scale_channels_int24_like"] != C:
        raise SystemExit(f"selftest FAILED: integer x scale channels not recognised: {stats}")
    print(f"selftest payload_ok nan={stats['nan_count']} distinct={stats['distinct_count']} "
          f"int24_like={stats['scale_channels_int24_like']}/{stats['scale_channels_tested']}")
    rng = random.Random(1)
    bits, err = ratio_test([rng.uniform(0.01, 0.9) for _ in range(200)])
    if bits <= 64:
        raise SystemExit(f"selftest FAILED: generic float64 gave lcm_bits={bits}")
    print(f"selftest scale_test generic_lcm_bits={bits} err={err:.1e}")
    for case in ("datatype2", "f32_dtype", "filters", "channels", "size_mismatch", "swap_order", "data2",
                 "wavelengths", "missing_ml", "format_version"):
        expect_layout_failure(case, make_file(case)[0])
    expect_layout_failure("bad_eof", payload + b"\0" * 8)
    expect_layout_failure("bad_signature", b"\0" + payload[1:])
    bad_nan = bytearray(raw)
    bad_nan[8 * 10 : 8 * 11] = struct.pack("<Q", 0x7FF8000000000000)  # positive NaN: not the stored pattern
    expect_payload_failure("noncanonical_nan", bytes(bad_nan), T)
    inf = bytearray(raw)
    inf[8 * 20 : 8 * 21] = struct.pack("<d", float("inf"))
    expect_payload_failure("infinite", bytes(inf), T)
    expect_payload_failure("too_many_nan", with_nans(raw, range(C, 4 * C)), T)
    expect_payload_failure("constant", struct.pack(f"<{T * C}d", *([0.5] * (T * C))), T)
    expect_payload_failure("low_distinct", struct.pack(f"<{T * C}d", *([0.5, 0.25] * (T * C // 2))), T)
    expect_payload_failure("short", raw[:-8], T)
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
