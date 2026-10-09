#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py and hutubs_sofa.py (no network, no real data).

* lookup3 against Bob Jenkins' reference vectors; 8-byte shuffle vectors and
  agreement between h5lite.unshuffle and the independent verify_unshuffle8;
* end-to-end: three synthetic SOFA-like files mirroring the real HUTUBS
  layout at a small size (M=6 directions, R=2 ears, N=16 taps): superblock
  v2, root group with *dense* link storage (fractal heap, v2 B-tree name
  index with lookup3 hashes and a creation-order index) and *dense* global
  attribute storage (second fractal heap with 8-byte heap IDs, v2 B-tree type
  8), Data.IR float64 LE stored as one shuffle(8)+deflate chunk, Data.Delay,
  Data.SamplingRate and SourcePosition (with compact Type/Units attributes);
  build() must reproduce every IR byte for byte in C order and verify() must
  pass;
* corruption cases must be rejected: big-endian and float32 Data.IR,
  fletcher32 in the pipeline, deflate without shuffle, NaN, the netCDF
  double fill, an all-zero (direction, ear) row, a _FillValue attribute,
  wrong License / DatabaseName / ListenerShortName, wrong sampling rate,
  a damaged metadata checksum, a different SourcePosition grid, a duplicate
  subject, a sha256 pin mismatch, a tampered sample, an orphan sample, and a
  manifest total mismatch.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
import hutubs_sofa as hs  # noqa: E402
from h5lite import UNDEF, H5Error, lookup3  # noqa: E402

M, R, N = 6, 2, 16
SPEC = dict(hs.SPEC, n_subjects=3, M=M, R=R, N=N, min_distinct_values=150)
F64_BE = bytes.fromhex("11213f000800000000004000340b0034ff030000")
F32_LE = bytes.fromhex("11201f000400000000002000170800177f000000")


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"selftest FAILED: {what}")


def expect_error(fn, what: str) -> None:
    try:
        fn()
    except (hs.RecipeError, H5Error):
        return
    raise SystemExit(f"selftest FAILED: {what} was not rejected")


def test_units() -> None:
    check(lookup3(b"") == 0xDEADBEEF, "lookup3 empty")
    check(lookup3(b"Four score and seven years ago") == 0x17770551, "lookup3 vector 1")
    check(lookup3(b"Four score and seven years ago", 1) == 0xCD628161, "lookup3 vector 2")
    data = bytes(range(16))
    shuffled = bytes([0, 8, 1, 9, 2, 10, 3, 11, 4, 12, 5, 13, 6, 14, 7, 15])
    check(h5lite.shuffle(data, 8) == shuffled, "forward shuffle vector")
    check(h5lite.unshuffle(shuffled, 8) == data, "unshuffle vector")
    check(hs.verify_unshuffle8(shuffled) == data, "independent unshuffle vector")
    blob = bytes((i * 37 + 11) & 0xFF for i in range(8 * 515))
    check(hs.verify_unshuffle8(h5lite.shuffle(blob, 8)) == blob, "independent unshuffle round trip")
    check(h5lite.unshuffle(h5lite.shuffle(blob, 8), 8) == blob, "h5lite unshuffle round trip")


# --------------------------------------------------- synthetic HDF5 writer
def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def message(mtype: int, payload: bytes) -> bytes:
    return struct.pack("<BHB", mtype, len(payload), 0) + payload


def ohdr(messages: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(message(t, p) for t, p in messages)
    return checksummed(b"OHDR" + bytes([2, 0x02]) + struct.pack("<I", len(body)) + body)


def dataspace(dims: tuple[int, ...]) -> bytes:
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


def attr_payload(name: str, datatype: bytes, space: bytes, data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + data)


def str_attr(name: str, value: str) -> bytes:
    raw = value.encode()
    return attr_payload(name, bytes([0x13, 0, 0, 0]) + struct.pack("<I", len(raw)), bytes([2, 0, 0, 0]), raw)


def f64_attr(name: str, value: float) -> bytes:
    return attr_payload(name, hs.F64LE, dataspace((1,)), struct.pack("<d", value))


def link_payload(name: str, addr: int, order: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x04]) + struct.pack("<Q", order) + bytes([len(raw)]) + raw + struct.pack("<Q", addr)


def filters_v2(entries: list[tuple[int, list[int]]]) -> bytes:
    out = bytes([2, len(entries)])
    for fid, values in entries:
        out += struct.pack("<HHH", fid, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
    return out


SHUF_DEFL = filters_v2([(2, [8]), (1, [1])])


def tree_leaf(size: int, mask: int, rank: int, addr: int, final: tuple[int, ...]) -> bytes:
    body = b"TREE" + bytes([1, 0]) + struct.pack("<H", 1) + struct.pack("<QQ", UNDEF, UNDEF)
    body += struct.pack("<II", size, mask) + struct.pack(f"<{rank}Q", *([0] * rank)) + struct.pack("<Q", addr)
    body += struct.pack("<II", 0, 0) + struct.pack(f"<{rank}Q", *final)
    return body


def align(buf: bytearray) -> None:
    while len(buf) % 8:
        buf.append(0)


def write_heap(buf: bytearray, payloads: list[bytes], id_len: int) -> tuple[int, list[bytes]]:
    """Fractal heap with one checksummed root direct block holding payloads."""
    align(buf)
    heap_addr = len(buf)
    block_size = 2048
    block_addr = heap_addr + 160
    header_len = 4 + 1 + 8 + 4 + 4
    objects, ids = bytearray(), []
    for payload in payloads:
        offset = header_len + len(objects)
        hid = bytes([0]) + struct.pack("<I", offset) + struct.pack("<H", len(payload))
        ids.append(hid + b"\x00" * (id_len - len(hid)))
        objects += payload
    check(header_len + len(objects) <= block_size, "synthetic heap block too small")
    fields = [0, UNDEF, 0, UNDEF, block_size, block_size, 0, len(payloads), 0, 0, 0, 0]
    heap = (b"FRHP" + bytes([0]) + struct.pack("<HH", id_len, 0) + bytes([0x02]) + struct.pack("<I", 4096)
            + struct.pack("<12Q", *fields) + struct.pack("<H", 4) + struct.pack("<QQ", block_size, 65536)
            + struct.pack("<HH", 32, 1) + struct.pack("<Q", block_addr) + struct.pack("<H", 0))
    buf += checksummed(heap)
    check(len(buf) <= block_addr, "heap header overlaps block")
    buf += b"\x00" * (block_addr - len(buf))
    block = bytearray(b"FHDB" + bytes([0]) + struct.pack("<Q", heap_addr) + struct.pack("<I", 0) + b"\x00" * 4)
    block += objects
    block += b"\x00" * (block_size - len(block))
    struct.pack_into("<I", block, 17, lookup3(bytes(block)))
    buf += block
    return heap_addr, ids


def write_btree2(buf: bytearray, btype: int, records: list[bytes]) -> int:
    align(buf)
    leaf_addr = len(buf)
    buf.extend(checksummed(b"BTLF" + bytes([0, btype]) + b"".join(records)))
    align(buf)
    hdr_addr = len(buf)
    buf.extend(checksummed(b"BTHD" + bytes([0, btype]) + struct.pack("<I", 512)
                           + struct.pack("<HH", len(records[0]), 0) + bytes([100, 40])
                           + struct.pack("<Q", leaf_addr) + struct.pack("<H", len(records))
                           + struct.pack("<Q", len(records))))
    return hdr_addr


def make_ir(seed: int, opts: dict) -> list[float]:
    rng = random.Random(seed)
    vals = []
    for row in range(M * R):
        onset = 3 + row % 4
        for n in range(N):
            if n < onset - 2:
                vals.append(0.0 if n == 0 else rng.gauss(0, 1e-5))
            else:
                k = n - onset
                vals.append(math.exp(-0.4 * max(k, 0)) * math.cos(1.3 * k + row) + rng.gauss(0, 1e-4))
    if opts.get("nan"):
        vals[17] = float("nan")
    if opts.get("fill"):
        vals[40] = hs.NC_FILL_DOUBLE
    if opts.get("zero_row"):
        vals[3 * N:4 * N] = [0.0] * N
    return vals


def build_file(subject: int, opts: dict | None = None) -> tuple[bytes, bytes]:
    opts = opts or {}
    buf = bytearray(b"\x00" * 48)
    headers: dict[str, int] = {}
    fill_msg = bytes([3, 0x2B]) + struct.pack("<I", 8) + struct.pack("<d", hs.NC_FILL_DOUBLE)

    def f64_var(name: str, values: list[float], shape: tuple[int, ...], extra=(), datatype=None, filters=SHUF_DEFL,
                shuffle=True) -> bytes:
        esize = 4 if datatype == F32_LE else 8
        raw = struct.pack(f"<{len(values)}{'f' if esize == 4 else 'd'}", *values)
        if datatype == F64_BE:
            raw = struct.pack(f">{len(values)}d", *values)
        stored = zlib.compress(h5lite.shuffle(raw, esize) if shuffle else raw, 1)
        align(buf)
        chunk_addr = len(buf)
        buf.extend(stored)
        align(buf)
        btree = len(buf)
        rank = len(shape) + 1
        buf.extend(tree_leaf(len(stored), 0, rank, chunk_addr, shape + (esize,)))
        layout = bytes([3, 2, rank]) + struct.pack("<Q", btree) + struct.pack(f"<{rank}I", *shape, esize)
        msgs = [(0x01, dataspace(shape)), (0x03, datatype or hs.F64LE), (0x05, fill_msg), (0x0B, filters),
                (0x08, layout)] + list(extra)
        align(buf)
        headers[name] = len(buf)
        buf.extend(ohdr(msgs))
        return raw

    ir_vals = make_ir(100 + subject + (0 if not opts.get("duplicate_of") else opts["duplicate_of"] - subject), opts)
    ir_extra = [(0x0C, f64_attr("_FillValue", hs.NC_FILL_DOUBLE))] if opts.get("fill_attr") else []
    ir_dtype = F64_BE if opts.get("big_endian") else (F32_LE if opts.get("float32") else None)
    ir_filters = SHUF_DEFL
    if opts.get("fletcher"):
        ir_filters = filters_v2([(2, [8]), (1, [1]), (3, [])])
    if opts.get("deflate_only"):
        ir_filters = filters_v2([(1, [1])])
    ir_raw = f64_var("Data.IR", ir_vals, (M, R, N), ir_extra, ir_dtype, ir_filters, shuffle=not opts.get("deflate_only"))
    f64_var("Data.SamplingRate", [48000.0 if opts.get("rate") else 44100.0], (1,))
    f64_var("Data.Delay", [0.0, 0.0], (1, R))
    grid = []
    for m in range(M):
        grid += [(60.0 * m + (5.0 if opts.get("grid") else 0.0)) % 360.0, 10.0 * (m % 3), 1.47]
    f64_var("SourcePosition", grid, (M, 3),
            [(0x0C, str_attr("Type", "spherical")), (0x0C, str_attr("Units", "degree, degree, metre"))])
    # remaining SOFA variables: tiny f64 placeholders (links must exist)
    for name in sorted(hs.EXPECTED_LINKS - set(headers)):
        f64_var(name, [1.0, 2.0], (2,))
    # dense links
    names = sorted(hs.EXPECTED_LINKS)
    link_heap, link_ids = write_heap(buf, [link_payload(n, headers[n], k) for k, n in enumerate(names)], 7)
    name_records = sorted(struct.pack("<I", lookup3(n.encode())) + hid for n, hid in zip(names, link_ids))
    name_bt = write_btree2(buf, 5, name_records)
    order_bt = write_btree2(buf, 6, [struct.pack("<Q", k) + hid for k, hid in enumerate(link_ids)])
    link_info = bytes([0, 0x03]) + struct.pack("<Q", len(names)) + struct.pack("<QQQ", link_heap, name_bt, order_bt)
    # dense global attributes
    gattrs = dict(hs.GLOBAL_ATTRS, ListenerShortName=f"pp{subject}", APIName="ARI SOFA API for Matlab/Octave")
    if opts.get("license"):
        gattrs["License"] = "No license provided, ask the author for permission"
    if opts.get("database"):
        gattrs["DatabaseName"] = "ARI"
    if opts.get("listener"):
        gattrs["ListenerShortName"] = "pp99"
    anames = list(gattrs)
    attr_heap, attr_ids = write_heap(buf, [str_attr(k, v) for k, v in gattrs.items()], 8)
    attr_records = sorted(hid + bytes([0]) + struct.pack("<I", k) + struct.pack("<I", lookup3(n.encode()))
                          for k, (n, hid) in enumerate(zip(anames, attr_ids)))
    attr_bt = write_btree2(buf, 8, attr_records)
    attr_info = bytes([0, 0]) + struct.pack("<QQ", attr_heap, attr_bt)
    align(buf)
    root_addr = len(buf)
    buf += ohdr([(0x02, link_info), (0x15, attr_info)])
    eof = len(buf)
    sb = b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root_addr)
    buf[0:48] = checksummed(sb)
    return bytes(buf), ir_raw


def make_tree(tmp: Path, label: str, per_subject: dict | None = None, pin: dict | None = None) -> tuple[Path, list[bytes]]:
    root = tmp / label
    if root.exists():
        shutil.rmtree(root)
    downloads = root / "downloads" / hs.DATASET_ID
    downloads.mkdir(parents=True)
    lines = ["subject\tfile\tsize_bytes\tlast_modified\tsha256"]
    irs = []
    for subject in range(1, SPEC["n_subjects"] + 1):
        raw, ir = build_file(subject, (per_subject or {}).get(subject))
        name = f"pp{subject}_HRIRs_measured.sofa"
        (downloads / name).write_bytes(raw)
        digest = (pin or {}).get(subject, hashlib.sha256(raw).hexdigest() if subject == 1 else "-")
        lines.append(f"{subject}\t{name}\t{len(raw)}\tTue, 23 Oct 2018 14:06:31 GMT\t{digest}")
        irs.append(ir)
    (root / "files.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root, irs


def run_build(root: Path) -> dict:
    return hs.build(root / "downloads" / hs.DATASET_ID, root / "files.tsv", root, SPEC, log=lambda *_: None)


def run_verify(root: Path, manifest: Path | None = None) -> dict:
    return hs.verify(root / "downloads" / hs.DATASET_ID, root / "files.tsv", root, manifest, SPEC, log=lambda *_: None)


def test_end_to_end(tmp: Path) -> None:
    root, irs = make_tree(tmp, "good")
    summary = run_build(root)
    check(summary["samples"] == 3 and summary["total_size_bytes"] == 3 * M * R * N * 8, f"summary {summary}")
    rows = [json.loads(x) for x in (root / "index" / hs.DATASET_ID / "samples.jsonl").read_text().splitlines()]
    check([r["subject"] for r in rows] == [1, 2, 3], "index order")
    for row, ir in zip(rows, irs):
        data = (root / row["sample_path"]).read_bytes()
        check(data == ir, f"pp{row['subject']}: sample differs from the original C-order array")
        vals = struct.unpack(f"<{M * R * N}d", data)
        check(row["min"] == min(vals) and row["max"] == max(vals), "index min/max from stored f64")
        check(row["value_count"] == M * R * N and row["shape"] == [M, R, N], "value count / shape")
    check(rows[0]["subject_note"].startswith("FABIAN"), "FABIAN note on subject 1")
    run_verify(root)
    manifest = root / "manifest.toml"
    manifest.write_text(f'dataset_id = "{hs.DATASET_ID}"\n[[series]]\nid = "{hs.SERIES_ID}"\nrole = "primary"\n'
                        f'numeric_kind = "float"\nbit_width = 64\nsample_count = 3\ntotal_size_bytes = {3 * M * R * N * 8}\n')
    run_verify(root, manifest)
    manifest.write_text(manifest.read_text().replace("sample_count = 3", "sample_count = 4"))
    expect_error(lambda: run_verify(root, manifest), "manifest sample_count mismatch")
    sample = root / rows[1]["sample_path"]
    good = sample.read_bytes()
    sample.write_bytes(good[:-8] + struct.pack("<d", 0.123))
    expect_error(lambda: run_verify(root), "tampered sample")
    sample.write_bytes(good)
    orphan = sample.parent / "pp004.bin"
    orphan.write_bytes(good)
    expect_error(lambda: run_verify(root), "orphan sample file")
    orphan.unlink()
    run_verify(root)
    # validate subcommand on a real-layout synthetic file must accept subject 1's file
    src = root / "downloads" / hs.DATASET_ID / "pp1_HRIRs_measured.sofa"
    decoded = hs.decode_sofa(src.read_bytes(), 1, SPEC)
    check(decoded["checked_blocks"] >= 10, f"metadata checksums verified: {decoded['checked_blocks']}")
    bad = bytearray(src.read_bytes())
    root_addr = struct.unpack_from("<Q", bad, 36)[0]
    bad[root_addr + 12] ^= 0xFF
    expect_error(lambda: hs.decode_sofa(bytes(bad), 1, SPEC), "corrupted root object header checksum")


def test_rejections(tmp: Path) -> None:
    file_cases = {
        "big_endian": "big-endian Data.IR",
        "float32": "float32 Data.IR",
        "fletcher": "fletcher32 filter",
        "deflate_only": "deflate without shuffle",
        "nan": "NaN value",
        "fill": "netCDF double fill value",
        "zero_row": "all-zero (direction, ear) row",
        "fill_attr": "_FillValue attribute on Data.IR",
        "license": "wrong License attribute",
        "database": "wrong DatabaseName",
        "listener": "wrong ListenerShortName",
        "rate": "wrong sampling rate",
    }
    for key, what in file_cases.items():
        root, _ = make_tree(tmp, key, {2: {key: True}})
        expect_error(lambda root=root: run_build(root), what)
    root, _ = make_tree(tmp, "grid", {3: {"grid": True}})
    expect_error(lambda: run_build(root), "different SourcePosition grid")
    root, _ = make_tree(tmp, "dup", {3: {"duplicate_of": 2}})
    expect_error(lambda: run_build(root), "duplicate subject IR")
    root, _ = make_tree(tmp, "pin", pin={2: "0" * 64})
    expect_error(lambda: run_build(root), "sha256 pin mismatch")


def main() -> int:
    test_units()
    tmp = Path(tempfile.mkdtemp(prefix="hutubs_selftest_"))
    try:
        test_end_to_end(tmp)
        test_rejections(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest ok: lookup3, 8-byte shuffle (two implementations), synthetic dense-link/dense-attribute "
          "SOFA build/verify, 3 verify tamper cases, 15 build rejection cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
