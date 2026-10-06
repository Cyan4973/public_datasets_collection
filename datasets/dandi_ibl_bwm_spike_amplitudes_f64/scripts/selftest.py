#!/usr/bin/env python3
"""Synthetic end-to-end self-test for the recipe's HDF5/NWB decode path.

Writes a tiny NWB-like HDF5 file byte by byte: superblock v0, v1 object
headers (one with a continuation block), symbol-table groups (root behind a
two-level group B-tree), variable-length strings in a global heap (scalar
datasets and attributes, plus a string-array attribute), a chunked deflate
float64 ragged column `units/spike_amplitudes_uV` with an edge chunk, and its
chunked deflate uint32 `spike_amplitudes_uV_index`. The file is then exposed
through a sparse BlockStore exactly as download.sh caches it, and the real
`read_layout`, `ChunkStream` and `load_index` code must reproduce every unit's
values bit for bit, report MissingBlock for an absent block, and reject
corrupted variants. Also checks that the float32-scale disclosure test
separates float32-times-constant data from generic float64 data.
"""

from __future__ import annotations

import array
import random
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ibl_amplitudes as A  # noqa: E402
import nwb_hdf5 as H  # noqa: E402
from scale_test import float32_scale_test  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF
F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")
VLEN_STR = bytes.fromhex("1901010010000000") + bytes.fromhex("1300000001000000")
CHUNK = 700
MIN_SPIKES = 50
COUNTS = [30, 400, 1200, 10, 880, 600]


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


def group_header(w: Writer, entries: list[tuple[str, int]], attrs: list[bytes] = ()) -> int:
    btree, heap = group(w, entries)
    msgs = [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", btree, heap))]
    msgs += [(H.MSG_ATTRIBUTE, attr) for attr in attrs]
    return object_header(w, msgs)


class GlobalHeap:
    def __init__(self, w: Writer, strings: list[str]) -> None:
        body = bytearray()
        self.index = {}
        for number, text in enumerate(dict.fromkeys(strings), 1):
            raw = text.encode()
            body += struct.pack("<HHIQ", number, 1, 0, len(raw)) + pad8(raw)
            self.index[text] = number
        body += struct.pack("<HHIQ", 0, 0, 0, 16)
        self.address = w.add(b"GCOL" + bytes([1, 0, 0, 0]) + struct.pack("<Q", 16 + len(body)) + bytes(body))

    def ref(self, text: str) -> bytes:
        return struct.pack("<IQI", len(text.encode()), self.address, self.index[text])


def attribute(name: str, dtype: bytes, data: bytes, dims: tuple[int, ...] = ()) -> bytes:
    raw_name = name.encode() + b"\0"
    if dims:
        space = struct.pack("<BBBB4x" + "Q" * len(dims), 1, len(dims), 0, 0, *dims)
    else:
        space = bytes([1, 0, 0, 0, 0, 0, 0, 0])
    return (struct.pack("<BBHHH", 1, 0, len(raw_name), len(dtype), len(space))
            + pad8(raw_name) + pad8(dtype) + pad8(space) + data)


def string_dataset(w: Writer, heap: GlobalHeap, text: str) -> int:
    data_address = w.add(heap.ref(text))
    layout = struct.pack("<BBQQ", 3, 1, data_address, 16)
    return object_header(w, [(H.MSG_DATASPACE, bytes([1, 0, 0, 0, 0, 0, 0, 0])),
                             (H.MSG_DATATYPE, VLEN_STR), (H.MSG_LAYOUT, layout)])


def chunked_1d(w: Writer, raw: bytes, element: int, chunk: int, dtype: bytes, attrs: list[bytes],
               mutate: str = "", split: int | None = None) -> tuple[int, int]:
    """Write a chunked deflate 1-D dataset; return (object header address, stored bytes)."""
    n = len(raw) // element
    keys = []
    starts = list(range(0, n, chunk))
    if mutate == "missing_chunk":
        starts = starts[:-1]
    for start in starts:
        block = raw[start * element : (start + chunk) * element]
        block += b"\0" * (chunk * element - len(block))
        stored = zlib.compress(block, 4)
        if mutate == "truncated_deflate" and start == starts[-1]:
            stored = stored[:-6]
        address = w.add(stored)
        mask = 1 if mutate == "filter_mask" and start == 0 else 0
        keys.append((struct.pack("<IIQQ", len(stored), mask, start, 0), address))
    if mutate == "duplicate_chunk":
        keys.append(keys[0])
    node = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(keys), UNDEF, UNDEF)
    for key, address in keys:
        node += key + struct.pack("<Q", address)
    node += struct.pack("<IIQQ", 0, 0, n, 0)
    btree = w.add(node)
    dataspace = struct.pack("<BBBB4xQ", 1, 1, 0, 0, n)
    layout = struct.pack("<BBBQII", 3, 2, 2, btree, chunk, element)
    deflate = struct.pack("<HHHH", 1, 8, 1, 1) + b"deflate\0" + struct.pack("<II", 4, 0)
    shuffle = struct.pack("<HHHH", 2, 8, 1, 1) + b"shuffle\0" + struct.pack("<II", element, 0)
    filters = [shuffle, deflate] if mutate == "shuffle" else [deflate]
    pipeline = struct.pack("<BB6x", 1, len(filters)) + b"".join(filters)
    msgs = [(H.MSG_DATASPACE, dataspace), (H.MSG_DATATYPE, dtype), (H.MSG_LAYOUT, layout),
            (H.MSG_FILTER, pipeline)] + [(H.MSG_ATTRIBUTE, a) for a in attrs]
    stored_total = sum(struct.unpack_from("<I", key, 0)[0] for key, _ in keys)
    return object_header(w, msgs, split=split), stored_total


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def synthetic_values() -> list[float]:
    rng = random.Random(409)
    values = []
    for unit, count in enumerate(COUNTS):
        if unit == 4:  # one unit of generic float64 values (control)
            values += [rng.uniform(20.0, 400.0) for _ in range(count)]
        else:
            scale = rng.uniform(5.0, 40.0)
            values += [f32(rng.uniform(1.0, 30.0)) * scale for _ in range(count)]
    return values


SESSION = {
    "asset_id": "00000000-0000-0000-0000-000000000409",
    "lab": "testlab", "institution": "Test Institute", "session_eid": "11111111-2222-3333-4444-555555555555",
    "subject_id": "TST_001", "nwb_identifier": "66666666-7777-8888-9999-000000000000",
    "units": len(COUNTS), "spikes": sum(COUNTS), "amp_chunks": -(-sum(COUNTS) // CHUNK),
    "index_stored_bytes": 0, "amp_stored_bytes": 0,
}


def make_file(mutate: str = "") -> tuple[bytes, dict[str, int]]:
    values = synthetic_values()
    index = []
    total = 0
    for count in COUNTS:
        total += count
        index.append(total)
    if mutate == "index_nonmonotone":
        index[2], index[3] = index[3], index[2]
    if mutate == "index_last":
        index[-1] -= 1
    w = Writer()
    strings = ["NWBFile", "core", "2.9.0", "Units", "VectorData", "VectorIndex", "ElementIdentifiers",
               "Spike-sorted units from Neuropixels 1.0 probes.", A.AMP_DESCRIPTION, A.INDEX_DESCRIPTION,
               "spike_amplitudes_uV", "spike_times", "wronglab",
               SESSION["lab"], SESSION["institution"], SESSION["session_eid"], SESSION["subject_id"],
               SESSION["nwb_identifier"]]
    heap = GlobalHeap(w, strings)
    vstr = lambda name, text: attribute(name, VLEN_STR, heap.ref(text))  # noqa: E731
    amp_raw = struct.pack(f"<{len(values)}d", *values)
    amp_dtype = F32LE if mutate == "f32_dtype" else H.H5T_IEEE_F64LE
    amp_element = 4 if mutate == "f32_dtype" else 8
    if mutate == "f32_dtype":
        amp_raw = struct.pack(f"<{len(values)}f", *values)
    amp_chunk = 600 if mutate == "chunk_length" else CHUNK
    amp, amp_stored = chunked_1d(w, amp_raw, amp_element, amp_chunk, amp_dtype,
                                 [vstr("description", A.AMP_DESCRIPTION), vstr("neurodata_type", "VectorData")],
                                 mutate=mutate, split=2)
    idx, idx_stored = chunked_1d(w, struct.pack(f"<{len(index)}I", *index), 4, len(index), H.H5T_STD_U32LE,
                                 [vstr("description", A.INDEX_DESCRIPTION), vstr("neurodata_type", "VectorIndex")])
    ids, _ = chunked_1d(w, struct.pack(f"<{len(COUNTS)}I", *range(len(COUNTS))), 4, len(COUNTS),
                        H.H5T_STD_U32LE, [vstr("neurodata_type", "ElementIdentifiers")])
    colnames = attribute("colnames", VLEN_STR, heap.ref("spike_times") + heap.ref("spike_amplitudes_uV"), dims=(2,))
    units = group_header(w, [("id", ids), ("spike_amplitudes_uV", amp), ("spike_amplitudes_uV_index", idx)],
                         [vstr("neurodata_type", "Units"), colnames,
                          vstr("description", "Spike-sorted units from Neuropixels 1.0 probes.")])
    subject = group_header(w, [("subject_id", string_dataset(w, heap, SESSION["subject_id"]))])
    lab = "wronglab" if mutate == "wrong_lab" else SESSION["lab"]
    general = group_header(w, [("lab", string_dataset(w, heap, lab)),
                               ("institution", string_dataset(w, heap, SESSION["institution"])),
                               ("session_id", string_dataset(w, heap, SESSION["session_eid"])),
                               ("subject", subject)])
    identifier = string_dataset(w, heap, SESSION["nwb_identifier"])
    root_btree, root_heap = group(w, [("general", general), ("identifier", identifier), ("units", units)],
                                  two_level=True)
    root = object_header(w, [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", root_btree, root_heap)),
                             (H.MSG_ATTRIBUTE, vstr("neurodata_type", "NWBFile")),
                             (H.MSG_ATTRIBUTE, vstr("namespace", "core")),
                             (H.MSG_ATTRIBUTE, vstr("nwb_version", "2.9.0"))])
    w.buf += b"\0" * (-len(w.buf) % 8)
    superblock = (H.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
                  + struct.pack("<QQQQ", 0, UNDEF, len(w.buf), UNDEF)
                  + struct.pack("<QQII", 0, root, 1, 0) + struct.pack("<QQ", root_btree, root_heap))
    assert len(superblock) == 96
    w.buf[0:96] = superblock
    pins = {"amp_stored_bytes": amp_stored, "index_stored_bytes": idx_stored}
    return bytes(w.buf), {"values": values, "index": index, "pins": pins}


def store_blocks(payload: bytes, directory: Path, block_size: int, skip: set[int] = frozenset()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for number, start in enumerate(range(0, len(payload), block_size)):
        if number not in skip:
            (directory / f"blk_{number:06d}.bin").write_bytes(payload[start : start + block_size])


def session_for(payload: bytes, pins: dict[str, int]) -> dict[str, object]:
    session = dict(SESSION)
    session["size_bytes"] = len(payload)
    session.update(pins)
    return session


def decode(payload: bytes, root: Path, pins: dict[str, int], block_size: int = 4096) -> tuple[list[bytes], dict[str, object]]:
    session = session_for(payload, pins)
    store = H.BlockStore(root / "meta", len(payload), block_size)
    layout = A.read_layout(store, session)
    chunk_dir = root / "sessions" / str(session["asset_id"]) / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for kind, key in (("index", "index_chunks"), ("amp", "amp_chunks")):
        for chunk in layout[key]:
            start = int(chunk["address"])
            data = payload[start : start + int(chunk["stored_bytes"])]
            (chunk_dir / f"{kind}_{int(chunk['element_offset']):09d}.bin").write_bytes(data)
    index = A.load_index(chunk_dir / "index_000000000.bin", layout)
    stream = A.ChunkStream(root, session, layout)
    bounds = [0] + index
    out = [stream.read(bounds[i], bounds[i + 1]) for i in range(len(index))]
    stream.finish()
    if stream.valid_bytes != 8 * int(layout["spikes"]):
        raise ValueError("decoded size mismatch")
    return out, layout


def expect_failure(label: str, payload: bytes, pins: dict[str, int]) -> None:
    with tempfile.TemporaryDirectory(prefix="ibl_selftest_") as tmp:
        root = Path(tmp)
        store_blocks(payload, root / "meta", 4096)
        try:
            decode(payload, root, pins)
        except ValueError as exc:
            print(f"selftest reject_ok case={label} reason={str(exc)[:90]!r}")
            return
    raise SystemExit(f"selftest FAILED: corrupted case {label!r} was accepted")


def main() -> int:
    A.CHUNK_LENGTH = CHUNK
    A.MIN_SPIKES = MIN_SPIKES
    payload, truth = make_file()
    values = truth["values"]
    with tempfile.TemporaryDirectory(prefix="ibl_selftest_") as tmp:
        root = Path(tmp)
        # An absent metadata block must surface as MissingBlock, never as a parse result.
        store_blocks(payload, root / "meta", 4096, skip={0})
        try:
            A.read_layout(H.BlockStore(root / "meta", len(payload), 4096), session_for(payload, truth["pins"]))
        except H.MissingBlock as missing:
            print(f"selftest missing_block_ok block={missing.index}")
        else:
            raise SystemExit("selftest FAILED: missing superblock block was not reported")
        store_blocks(payload, root / "meta", 4096)
        units, layout = decode(payload, root, truth["pins"])
    if len(layout["amp_chunks"]) != -(-len(values) // CHUNK) or layout["amp_chunks"][-1]["valid_elements"] != len(values) % CHUNK:
        raise SystemExit("selftest FAILED: chunk plan geometry")
    start = 0
    for number, count in enumerate(COUNTS):
        expected = array.array("d", values[start : start + count])
        if sys.byteorder != "little":
            expected.byteswap()
        if units[number] != expected.tobytes():
            raise SystemExit(f"selftest FAILED: unit {number} decoded wrongly")
        start += count
    print(f"selftest decode_ok units={len(units)} spikes={len(values)} chunks={len(layout['amp_chunks'])} "
          f"strings={layout['lab']},{layout['subject_id']},{layout['nwb_identifier'][:8]}")
    # Disclosure test: float32 x constant units stay within 24 bits; generic float64 does not.
    start = 0
    for number, count in enumerate(COUNTS):
        bits, err = float32_scale_test(values[start : start + count])
        start += count
        scaled = number != 4
        if scaled and not (bits <= 24 and err < 1e-15):
            raise SystemExit(f"selftest FAILED: scaled unit {number} gave lcm_bits={bits} err={err}")
        if not scaled and bits <= 64:
            raise SystemExit(f"selftest FAILED: generic float64 unit gave lcm_bits={bits}")
        print(f"selftest scale_test unit={number} float32_scaled={scaled} lcm_bits={bits} max_rel_err={err:.2e}")
    for case in ("missing_chunk", "duplicate_chunk", "filter_mask", "truncated_deflate", "f32_dtype", "shuffle",
                 "index_nonmonotone", "index_last", "chunk_length", "wrong_lab"):
        bad, bad_truth = make_file(case)
        expect_failure(case, bad, bad_truth["pins"])
    expect_failure("bad_eof", payload + b"\0" * 8, truth["pins"])
    expect_failure("bad_signature", b"\0" + payload[1:], truth["pins"])
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
