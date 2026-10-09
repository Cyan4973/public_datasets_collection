#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py and geoschem_restart.py (no network).

* lookup3 against Bob Jenkins' reference vectors;
* HDF5 byte shuffle / unshuffle vectors and round trip;
* an end-to-end synthetic NetCDF4-like restart file mirroring the real
  layout at a small size: superblock v2, root group with *dense* link storage
  (fractal heap with a checksummed root direct block, v2 B-tree name index
  with lookup3 name hashes and a creation-order index), compact global and
  variable attributes, species variables (1, L, Y, X) float64 LE chunked one
  level per chunk with shuffle(8)+deflate, chunks stored out of level order,
  a non-species Met_ variable, a constant species and a 60%-zero species;
  build() must reproduce the original arrays byte for byte in C order, drop
  exactly the two degenerate species, and verify() must pass;
* corruption cases must be rejected: wrong datatype, a fletcher32 filter in
  the pipeline, a nonzero chunk filter mask, a missing chunk, NaN values,
  the netCDF default fill, a damaged metadata checksum, a tampered sample.
"""
from __future__ import annotations

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
import geoschem_restart as gr  # noqa: E402
import h5lite  # noqa: E402
from h5lite import UNDEF, H5Error, lookup3  # noqa: E402

F64_BE = bytes.fromhex("11213f000800000000004000340b0034ff030000")
L, Y, X = 4, 3, 5
SPEC = {
    "file_size": None,  # set per synthetic file
    "shape": (1, L, Y, X),
    "chunk_dims": (1, 1, Y, X, 8),
    "root_links": 5,
    "species": 4,
    "min_distinct_values": 10,  # synthetic fields hold only L*Y*X = 60 values
    "check_floor": False,
    # Synthetic exclusion list: CH4 holds a normal field that would pass the
    # degeneracy rule, so excluding it proves exclusions apply first.
    "semantic_classes": {"kpp_prod_loss_tracker": ({"CH4"}, "synthetic semantic exclusion")},
    "check_o2_ratio": False,
    "global_attrs": {"title": "GEOS-Chem diagnostic collection: Restart",
                     "simulation_end_date_and_time": "2019-01-01 00:00:00z"},
}


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"selftest FAILED: {what}")


def expect_error(fn, what: str) -> None:
    try:
        fn()
    except (gr.RecipeError, H5Error):
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
    check(gr.verify_unshuffle(shuffled, 8) == data, "verify unshuffle vector")
    blob = bytes((i * 37 + 11) & 0xFF for i in range(4096))
    check(h5lite.unshuffle(h5lite.shuffle(blob, 8), 8) == blob, "shuffle round trip")
    stats = gr.field_stats(struct.pack("<4d", 0.0, -0.0, 1e-20, -3.5))
    check(stats["zero_values"] == 2 and stats["negative_values"] == 1, "zero/negative counting")
    check(stats["min"] == -3.5 and stats["max"] == 1e-20 and stats["distinct_values"] == 4, "min/max/distinct")
    floor = gr.field_stats(struct.pack("<2000d", *[1e-30 * (1 + i * 1e-9) for i in range(2000)]))
    check(gr.degenerate_reason(floor).startswith("never above"), "floor-only field must be dropped")
    check(gr.degenerate_reason(gr.field_stats(struct.pack("<2000d", *[1e-12 * (1 + i) for i in range(2000)]))) == "",
          "ordinary field must be kept")


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


def str_attr(name: str, value: str) -> bytes:
    raw_name = name.encode() + b"\x00"
    raw = value.encode()
    datatype = bytes([0x13, 0, 0, 0]) + struct.pack("<I", len(raw))
    space = bytes([2, 0, 0, 0])
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + raw)


def link_payload(name: str, addr: int, order: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x04]) + struct.pack("<Q", order) + bytes([len(raw)]) + raw + struct.pack("<Q", addr)


def tree_leaf(entries: list[tuple[int, int, int, int]]) -> bytes:
    """entries: (stored size, filter mask, level, address)."""
    body = b"TREE" + bytes([1, 0]) + struct.pack("<H", len(entries)) + struct.pack("<QQ", UNDEF, UNDEF)
    for size, mask, level, addr in entries:
        body += struct.pack("<II5Q", size, mask, 0, level, 0, 0, 0) + struct.pack("<Q", addr)
    body += struct.pack("<II5Q", 0, 0, 1, L, Y, X, 0)
    return body


def field(kind: str, seed: int) -> list[float]:
    rng = random.Random(seed)
    n = L * Y * X
    if kind == "constant":
        return [1e-20] * n
    if kind == "zeros":
        return [0.0 if i % 5 < 3 else rng.uniform(1e-12, 1e-9) for i in range(n)]
    if kind == "nan":
        out = [rng.lognormvariate(-20, 3) for _ in range(n)]
        out[7] = float("nan")
        return out
    if kind == "ncfill":
        out = [rng.lognormvariate(-20, 3) for _ in range(n)]
        out[3] = 9.969209968386869e36
        return out
    return [rng.lognormvariate(-20 + seed, 3) * (1 if i % 17 else -1e-3) for i in range(n)]


class Options(dict):
    def __getattr__(self, key):
        return self.get(key)


def align(buf: bytearray) -> None:
    while len(buf) % 8:
        buf.append(0)


def build_file(opts: Options | None = None) -> tuple[bytes, dict[str, bytes]]:
    opts = opts or Options()
    buf = bytearray(b"\x00" * 48)
    variables = [("SpeciesRst_O3", opts.o3_kind or "normal", 1), ("SpeciesRst_CH4", "normal", 2),
                 ("SpeciesRst_LCH4", "zeros", 3), ("SpeciesRst_N2", "constant", 4), ("Met_DELPDRY", "normal", 5)]
    originals: dict[str, bytes] = {}
    headers: dict[str, int] = {}
    for vi, (name, kind, seed) in enumerate(variables):
        values = field(kind, seed)
        raw = struct.pack(f"<{len(values)}d", *values)
        originals[name] = raw
        level_bytes = Y * X * 8
        entries = []
        for level in reversed(range(L)):  # stored out of level order
            if opts.drop_chunk and name == "SpeciesRst_O3" and level == 2:
                continue
            stored = zlib.compress(h5lite.shuffle(raw[level * level_bytes:(level + 1) * level_bytes], 8), 1)
            mask = 1 if (opts.mask and name == "SpeciesRst_O3" and level == 1) else 0
            entries.append((len(stored), mask, level, len(buf)))
            buf += stored
        align(buf)
        btree = len(buf)
        buf += tree_leaf(entries)
        datatype = F64_BE if (opts.big_endian and name == "SpeciesRst_O3") else gr.F64LE
        filters = bytes([2, 2]) + struct.pack("<HHHI", 2, 1, 1, 8) + struct.pack("<HHHI", 1, 1, 1, 1)
        if opts.fletcher and name == "SpeciesRst_O3":
            filters = bytes([2, 3]) + struct.pack("<HHHI", 2, 1, 1, 8) + struct.pack("<HHHI", 1, 1, 1, 1) + struct.pack("<HHH", 3, 0, 0)
        layout = bytes([3, 2, 5]) + struct.pack("<Q", btree) + struct.pack("<5I", 1, 1, Y, X, 8)
        short = name.split("_", 1)[1]
        msgs = [(0x01, dataspace((1, L, Y, X))), (0x05, b"\x03\x07"), (0x0B, filters), (0x08, layout),
                (0x0C, str_attr("long_name", f"Dry mixing ratio of species {short}")),
                (0x0C, str_attr("units", "mol mol-1 dry" if name.startswith("Species") else "Pa")),
                (0x0C, str_attr("averaging_method", "instantaneous")), (0x03, datatype)]
        align(buf)
        headers[name] = len(buf)
        buf += ohdr(msgs)
    # Dense link storage: fractal heap with one checksummed root direct block.
    align(buf)
    heap_addr = len(buf)
    block_size = 512
    block_addr = heap_addr + 160
    heap_hdr_len = 4 + 1 + 2 + 2 + 1 + 4 + 96 + 2 + 16 + 4 + 8 + 2
    objects, ids = bytearray(), []
    header_len = 4 + 1 + 8 + 4 + 4
    for order, (name, _kind, _seed) in enumerate(variables):
        payload = link_payload(name, headers[name], order)
        offset = header_len + len(objects)
        ids.append((name, order, bytes([0]) + struct.pack("<I", offset) + struct.pack("<H", len(payload))))
        objects += payload
    check(header_len + len(objects) <= block_size, "synthetic heap block too small")
    fields = [0, UNDEF, 0, UNDEF, block_size, block_size, 0, len(variables), 0, 0, 0, 0]
    heap = (b"FRHP" + bytes([0]) + struct.pack("<HH", 7, 0) + bytes([0x02]) + struct.pack("<I", 4096)
            + struct.pack("<12Q", *fields) + struct.pack("<H", 4) + struct.pack("<QQ", block_size, 65536)
            + struct.pack("<HH", 32, 1) + struct.pack("<Q", block_addr) + struct.pack("<H", 0))
    check(len(heap) == heap_hdr_len, "fractal heap header length")
    buf += checksummed(heap)
    buf += b"\x00" * (block_addr - len(buf))
    block = bytearray(b"FHDB" + bytes([0]) + struct.pack("<Q", heap_addr) + struct.pack("<I", 0) + b"\x00" * 4)
    block += objects
    block += b"\x00" * (block_size - len(block))
    struct.pack_into("<I", block, 17, lookup3(bytes(block)))
    buf += block
    # v2 B-trees: name index (type 5) and creation-order index (type 6).
    def btree2(btype: int, records: list[bytes]) -> int:
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
    name_records = sorted(struct.pack("<I", lookup3(n.encode())) + hid for n, _o, hid in ids)
    if opts.bad_hash:
        name_records[0] = struct.pack("<I", 12345) + name_records[0][4:]
    name_bt = btree2(5, name_records)
    order_bt = btree2(6, [struct.pack("<Q", o) + hid for _n, o, hid in ids])
    link_info = bytes([0, 0x03]) + struct.pack("<Q", len(variables)) + struct.pack("<QQQ", heap_addr, name_bt, order_bt)
    root_msgs = [(0x02, link_info)] + [(0x0C, str_attr(k, v)) for k, v in SPEC["global_attrs"].items()]
    align(buf)
    root_addr = len(buf)
    buf += ohdr(root_msgs)
    eof = len(buf)
    sb = b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root_addr)
    buf[0:48] = checksummed(sb)
    return bytes(buf), originals


def run_build(tmp: Path, raw: bytes, label: str) -> tuple[Path, dict, dict]:
    root = tmp / label
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    src = root / "restart.nc4"
    src.write_bytes(raw)
    spec = dict(SPEC, file_size=len(raw))
    index = root / "index" / gr.DATASET_ID / "samples.jsonl"
    stats = root / "filtered" / gr.DATASET_ID
    summary = gr.build(src, root, spec, index, stats, log=lambda *_: None)
    return root, spec, summary


def test_end_to_end(tmp: Path) -> None:
    raw, originals = build_file()
    root, spec, summary = run_build(tmp, raw, "good")
    check(summary["samples"] == 1, f"expected 1 kept species, got {summary['samples']}")
    check(sorted(d["variable"] for d in summary["dropped_degenerate"]) == ["SpeciesRst_LCH4", "SpeciesRst_N2"], "dropped list")
    check([d["variable"] for d in summary["excluded_semantic"]] == ["SpeciesRst_CH4"], "excluded list")
    check(summary["excluded_semantic"][0]["class"] == "kpp_prod_loss_tracker", "exclusion class recorded")
    table = (root / "filtered" / gr.DATASET_ID / "species_stats.tsv").read_text().splitlines()
    decisions = {line.split("\t")[0]: line.split("\t")[1] for line in table[1:]}
    check(decisions == {"SpeciesRst_CH4": "excluded_semantic", "SpeciesRst_LCH4": "dropped_degenerate",
                        "SpeciesRst_N2": "dropped_degenerate", "SpeciesRst_O3": "kept"}, f"decisions {decisions}")
    rows = [json.loads(x) for x in (root / "index" / gr.DATASET_ID / "samples.jsonl").read_text().splitlines()]
    check([r["variable"] for r in rows] == ["SpeciesRst_O3"], "kept species order")
    for row in rows:
        data = (root / row["sample_path"]).read_bytes()
        check(data == originals[row["variable"]], f"{row['variable']} bytes differ from the original C-order array")
        vals = struct.unpack(f"<{len(data) // 8}d", data)
        check(row["min"] == min(vals) and row["max"] == max(vals), "index min/max from stored f64")
        check(row["value_count"] == L * Y * X, "value count")
    index = root / "index" / gr.DATASET_ID / "samples.jsonl"
    stats = root / "filtered" / gr.DATASET_ID
    src = root / "restart.nc4"
    gr.verify(src, root, spec, index, stats, None, log=lambda *_: None)
    # Tampered sample must fail verify.
    sample = root / rows[0]["sample_path"]
    good = sample.read_bytes()
    sample.write_bytes(good[:-8] + struct.pack("<d", 1.0))
    expect_error(lambda: gr.verify(src, root, spec, index, stats, None, log=lambda *_: None), "tampered sample")
    sample.write_bytes(good)
    # An excluded species smuggled into the index (with a correct sample file
    # and statistics) must fail verify.
    index_text = index.read_text()
    ch4 = originals["SpeciesRst_CH4"]
    vals = struct.unpack(f"<{len(ch4) // 8}d", ch4)
    smuggled = dict(rows[0], variable="SpeciesRst_CH4", species="CH4", sample_path=gr.sample_rel_path("SpeciesRst_CH4"),
                    min=min(vals), max=max(vals), sha256=__import__("hashlib").sha256(ch4).hexdigest())
    (root / smuggled["sample_path"]).write_bytes(ch4)
    index.write_text(json.dumps(smuggled, sort_keys=True) + "\n" + index_text)
    expect_error(lambda: gr.verify(src, root, spec, index, stats, None, log=lambda *_: None), "excluded species in index")
    (root / smuggled["sample_path"]).unlink()
    index.write_text(index_text)
    gr.verify(src, root, spec, index, stats, None, log=lambda *_: None)
    # An exclusion naming a species absent from the file must fail the build.
    bad_spec = dict(SPEC, semantic_classes={"clock_tracer": ({"CLOCK"}, "absent")})
    expect_error(lambda: gr.build(src, root, dict(bad_spec, file_size=len(raw)), index, stats, log=lambda *_: None),
                 "exclusion of an absent species")
    # Damaged metadata checksum (flip a byte inside the root object header).
    bad = bytearray(raw)
    root_addr = struct.unpack_from("<Q", bad, 36)[0]
    bad[root_addr + 20] ^= 0xFF
    expect_error(lambda: run_build(tmp, bytes(bad), "badsum"), "corrupted root object header")


def test_rejections(tmp: Path) -> None:
    cases = {
        "big_endian": "big-endian datatype",
        "fletcher": "fletcher32 filter in pipeline",
        "mask": "nonzero chunk filter mask",
        "drop_chunk": "missing chunk",
        "bad_hash": "wrong link name hash",
    }
    for key, what in cases.items():
        raw, _ = build_file(Options({key: True}))
        expect_error(lambda raw=raw, key=key: run_build(tmp, raw, key), what)
    for kind in ("nan", "ncfill"):
        raw, _ = build_file(Options({"o3_kind": kind}))
        expect_error(lambda raw=raw, kind=kind: run_build(tmp, raw, kind), f"{kind} values")


def main() -> int:
    test_units()
    tmp = Path(tempfile.mkdtemp(prefix="geoschem_selftest_"))
    try:
        test_end_to_end(tmp)
        test_rejections(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest ok: lookup3, shuffle, stats, dense-link synthetic restart build/verify, 12 rejection cases (incl. semantic exclusions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
