#!/usr/bin/env python3
"""Self-test for pe_h5 / blockstore / gwtc3_pe on synthetic PESummary-like HDF5.

The synthetic files mirror the GWTC-3 release layout: superblock v0, version-1
object headers, a root symbol-table group holding several analysis groups
(``C01:IMRPhenomXPHM``, ``C01:Mixed``, ``C01:SEOBNRv4PHM``, ``history``), each
a symbol-table group with ``posterior_samples`` (a rank-1 *compound* dataset
of named IEEE float64 members, contiguous and unfiltered) next to decoy
datasets.  It checks:

1. compound datatype decoding (versions 1 and 3) and member offsets;
2. a chunked shuffle+deflate compound dataset decodes identically;
3. the full offline planner -> range fetch -> build -> verify loop (including
   the whole-file control comparison) reproduces the source columns bit-exactly;
4. corruption (wrong pinned span, non-IEEE member, NaN, truncated table,
   tampered sample) is rejected.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import random
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blockstore  # noqa: E402
import gwtc3_pe  # noqa: E402
import pe_h5  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF
F64_BODY = struct.pack("<I", 8) + pe_h5.IEEE_F64_PROPS
F64_TYPE = bytes([0x11, 0x20, 0x3F, 0x00]) + F64_BODY


def pad8(b: bytes) -> bytes:
    return b + b"\x00" * ((-len(b)) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)

    def alloc(self, data: bytes, align: int = 8) -> int:
        self.buf += b"\x00" * ((-len(self.buf)) % align)
        addr = len(self.buf)
        self.buf += data
        return addr


def msg(mtype: int, payload: bytes) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", mtype, len(payload), 0) + payload


def object_header(messages: list[bytes]) -> bytes:
    body = b"".join(messages)
    return struct.pack("<BBHII4x", 1, 0, len(messages), 1, len(body)) + body


def dataspace(dims: tuple[int, ...]) -> bytes:
    return struct.pack("<BBBB4x", 1, len(dims), 0, 0) + b"".join(struct.pack("<Q", d) for d in dims)


def compound_v1(names: list[str], member_type: bytes = F64_TYPE) -> bytes:
    out = bytes([0x16, len(names) & 0xFF, len(names) >> 8, 0]) + struct.pack("<I", 8 * len(names))
    for i, name in enumerate(names):
        out += pad8(name.encode() + b"\x00") + struct.pack("<IB3xI4x16x", 8 * i, 0, 0) + member_type
    return out


def compound_v3(names: list[str]) -> bytes:
    size = 8 * len(names)
    width = max(1, (size.bit_length() + 7) // 8)
    out = bytes([0x36, len(names) & 0xFF, len(names) >> 8, 0]) + struct.pack("<I", size)
    for i, name in enumerate(names):
        out += name.encode() + b"\x00" + (8 * i).to_bytes(width, "little") + F64_TYPE
    return out


def contiguous_dataset(w: Writer, dtype: bytes, n: int, table: bytes) -> int:
    addr = w.alloc(table)
    layout = struct.pack("<BBQQ", 3, 1, addr, len(table))
    return w.alloc(object_header([msg(0x01, dataspace((n,))), msg(0x03, dtype), msg(0x08, layout)]))


def chunked_dataset(w: Writer, dtype: bytes, n: int, table: bytes, rec: int, chunk: int) -> int:
    entries = []
    for r0 in range(0, n, chunk):
        raw = table[r0 * rec:(r0 + chunk) * rec]
        raw += b"\x00" * (chunk * rec - len(raw))
        stored = zlib.compress(pe_h5.shuffle(raw, rec), 4)
        entries.append((len(stored), r0, w.alloc(stored, 1)))
    body = b"TREE" + struct.pack("<BBHQQ", 1, 0, len(entries), UNDEF, UNDEF)
    for size, r0, addr in entries:
        body += struct.pack("<IIQQ", size, 0, r0, 0) + struct.pack("<Q", addr)
    body += struct.pack("<IIQQ", 0, 0, n, 0)
    btree = w.alloc(body)
    filt = struct.pack("<BB6x", 1, 2)
    for fid, name, vals in ((2, b"shuffle\x00", (rec,)), (1, b"deflate\x00", (4,))):
        filt += struct.pack("<4H", fid, len(name), 1, len(vals)) + pad8(name)
        filt += b"".join(struct.pack("<I", v) for v in vals) + (b"\x00" * 4 if len(vals) % 2 else b"")
    layout = struct.pack("<BBBQ2I", 3, 2, 2, btree, chunk, rec)
    return w.alloc(object_header([msg(0x01, dataspace((n,))), msg(0x03, dtype), msg(0x0B, filt),
                                  msg(0x08, layout)]))


def write_group(w: Writer, links: dict[str, int], snod_cap: int = 4) -> int:
    names = sorted(links)
    heap = bytearray(b"\x00" * 8)
    offs = {}
    for name in names:
        offs[name] = len(heap)
        heap += pad8(name.encode() + b"\x00")
    data_addr = w.alloc(bytes(heap))
    heap_addr = w.alloc(b"HEAP" + struct.pack("<B3xQQQ", 0, len(heap), UNDEF, data_addr))
    children = []
    for i in range(0, len(names), snod_cap):
        g = names[i:i + snod_cap]
        body = b"SNOD" + struct.pack("<BBH", 1, 0, len(g))
        for name in g:
            body += struct.pack("<QQII16x", offs[name], links[name], 0, 0)
        children.append((offs[g[-1]], w.alloc(body)))
    node = b"TREE" + struct.pack("<BBHQQ", 0, 0, len(children), UNDEF, UNDEF) + struct.pack("<Q", 0)
    for key, child in children:
        node += struct.pack("<QQ", child, key)
    root = w.alloc(node)
    return w.alloc(object_header([msg(0x11, struct.pack("<QQ", root, heap_addr))]))


def draw_row(rng: random.Random, names: list[str], t0: float) -> list[float]:
    vals = {}
    m1 = rng.uniform(5.0, 80.0)
    for name in names:
        lo, hi = gwtc3_pe.BOUNDS.get(name, (-1.0, 1.0))
        if name == "mass_1_source":
            v = m1
        elif name == "mass_2_source":
            v = m1 * rng.uniform(0.1, 1.0)
        elif name == "geocent_time":
            v = t0 + rng.uniform(-0.1, 0.1)
        elif name == "luminosity_distance":
            v = rng.uniform(100.0, 9000.0)
        elif name == "log_likelihood":
            v = rng.gauss(60.0, 4.0)
        elif name == "final_mass_source":
            v = m1 * 1.9
        elif name in ("pn_phase_order", "maximum_frequency"):
            v = 7.0
        else:
            v = rng.uniform(lo, hi)
        vals[name] = v
    return [vals[n] for n in names]


def build_file(n: int, seed: int, extra: list[str]) -> tuple[bytes, list[str], list[list[float]], dict]:
    rng = random.Random(seed)
    names = list(extra[:3]) + gwtc3_pe.MEMBERS[::-1] + list(extra[3:])
    rows = [draw_row(rng, names, 1262000000.0 + seed) for _ in range(n)]
    table = b"".join(struct.pack(f"<{len(names)}d", *r) for r in rows)
    w = Writer()
    w.alloc(b"\x00" * (1_100_000 + 9000 * seed % 50000))  # push metadata past the 1 MiB head prefetch
    decoy = contiguous_dataset(w, F64_TYPE, 7, struct.pack("<7d", *range(7)))
    ps = contiguous_dataset(w, compound_v1(names), n, table)
    xphm = write_group(w, {"posterior_samples": ps, "psds": decoy, "priors": decoy, "approximant": decoy,
                           "meta_data": decoy, "skymap": decoy})
    mixed_names = names[:5]
    mixed_table = b"".join(struct.pack("<5d", *r[:5]) for r in rows[: n // 3])
    mixed = write_group(w, {"posterior_samples": contiguous_dataset(w, compound_v1(mixed_names), n // 3, mixed_table)})
    seob = write_group(w, {"posterior_samples": contiguous_dataset(w, compound_v3(mixed_names), n // 3, mixed_table)})
    root = write_group(w, {"C01:IMRPhenomXPHM": xphm, "C01:Mixed": mixed, "C01:SEOBNRv4PHM": seob,
                           "history": write_group(w, {"x": decoy})})
    w.buf += b"\x00" * 200000
    eof = len(w.buf)
    sb = (pe_h5.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
          + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII16x", 0, root, 1, 0))
    assert len(sb) == 96
    w.buf[0:96] = sb
    data = bytes(w.buf)
    f = pe_h5.H5File(data, len(data))
    info = f.dataset(f.group_links(f.group_links(f.root_addr)["C01:IMRPhenomXPHM"])["posterior_samples"])
    return data, names, rows, info


def expect_error(fn, what: str) -> None:
    try:
        fn()
    except (pe_h5.H5Error, SystemExit, ValueError, KeyError):
        return
    raise AssertionError(f"expected failure: {what}")


def fake_fetch(files: dict[str, bytes], meta_req: Path, span_req: Path) -> int:
    fetched = 0
    for line in meta_req.read_text().splitlines():
        url, start, end, bdir, first, total = line.split("\t")
        start, end, first = int(start), int(end), int(first)
        data = files[url]
        assert int(total) == len(data) and start == first * blockstore.BLOCK_SIZE
        Path(bdir).mkdir(parents=True, exist_ok=True)
        piece = data[start:end + 1]
        for k in range(0, len(piece), blockstore.BLOCK_SIZE):
            Path(bdir, f"blk_{first + k // blockstore.BLOCK_SIZE:06d}.bin").write_bytes(piece[k:k + blockstore.BLOCK_SIZE])
        fetched += len(piece)
    for line in span_req.read_text().splitlines():
        url, start, end, out, total = line.split("\t")
        data = files[url]
        assert int(total) == len(data)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(data[int(start):int(end) + 1])
        fetched += int(end) - int(start) + 1
    return fetched


def manifest_text(totals: dict[str, tuple[int, int]]) -> str:
    out = []
    for sid in gwtc3_pe.MEMBERS:
        count, size = totals[sid]
        out.append(f'[[series]]\nid = "{sid}"\nrole = "primary"\n'
                   f'source_field = "{gwtc3_pe.ANALYSIS}/{gwtc3_pe.TABLE}.{sid}"\n'
                   f"sample_count = {count}\ntotal_size_bytes = {size}\n")
    return "\n".join(out)


class Args:
    pass


def main() -> int:
    # 1. compound decoding, v1 and v3, and the chunked shuffle+deflate path
    names = ["alpha", "beta_long_member_name", "gamma"]
    for enc in (compound_v1, compound_v3):
        dt = pe_h5.decode_datatype(enc(names))
        assert dt["kind"] == "compound" and dt["size"] == 24, dt
        assert [(m["name"], m["offset"], m["code"]) for m in dt["members"]] == [
            ("alpha", 0, "d"), ("beta_long_member_name", 8, "d"), ("gamma", 16, "d")], dt
    bad_float = bytes([0x11, 0x20, 0x3F, 0x00]) + struct.pack("<I", 8) + struct.pack("<HHBBBBI", 0, 64, 52, 11, 0, 52, 1022)
    expect_error(lambda: pe_h5.decode_datatype(compound_v1(names, bad_float)), "non-IEEE member")
    raw = struct.pack("<7d", 1.5, -2.25, 3e-300, 4e300, 0.0, -0.0, 7.0) + b"xyz"
    assert pe_h5.unshuffle(pe_h5.shuffle(raw, 8), 8) == raw
    assert gwtc3_pe.coalesce([1, 2, 3, 6, 10, 11]) == [(1, 6), (10, 11)]
    rng = random.Random(5)
    n = 1003
    table = b"".join(struct.pack("<3d", rng.random(), rng.gauss(0, 1), rng.uniform(-9, 9)) for _ in range(n))
    w = Writer()
    a = contiguous_dataset(w, compound_v1(names), n, table)
    c = chunked_dataset(w, compound_v1(names), n, table, 24, 128)
    eof = len(w.buf)
    root = write_group(w, {"a": a, "c": c})
    eof = len(w.buf)
    w.buf[0:96] = (pe_h5.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
                   + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII16x", 0, root, 1, 0))
    f = pe_h5.H5File(bytes(w.buf))
    links = f.group_links(f.root_addr)
    ia, ic = f.dataset(links["a"]), f.dataset(links["c"])
    assert ia["layout_class"] == 1 and ic["layout_class"] == 2 and [x[0] for x in ic["filters"]] == [2, 1]
    assert f.read_rows(ia) == table and f.read_rows(ic) == table
    print("selftest: compound v1/v3, contiguous and chunked shuffle+deflate decode ok")

    # 2. offline plan -> fetch -> build -> verify loop over three synthetic events
    quiet = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="gwtc3_selftest_") as tmp, contextlib.redirect_stdout(quiet):
        tmp = Path(tmp)
        events = [("GW200322_091133", 1200, 11), ("GW191103_012549", 2500, 12), ("GW200129_065458", 1777, 13)]
        extras = [["H1_optimal_snr", "pn_phase_order", "chirp_mass"], ["maximum_frequency", "redshift", "zenith", "iota"],
                  ["V1_time", "chi_eff", "spin_1z", "cos_iota", "psi_wrapped"]]
        files, truth, lines = {}, {}, ["\t".join(["event", "key", "size", "md5", "rows", "members", "table_offset",
                                                 "table_bytes"])]
        for (event, rows_n, seed), extra in zip(events, extras):
            data, mnames, rows, info = build_file(rows_n, seed, extra)
            key = f"IGWN-GWTC3p0-v2-{event}_PEDataRelease_mixed_cosmo.h5"
            files[f"{gwtc3_pe.API}/{gwtc3_pe.RECORD_ID}/files/{key}/content"] = data
            truth[event] = (mnames, rows)
            lines.append("\t".join(map(str, [event, key, len(data), hashlib.md5(data).hexdigest(), rows_n,
                                             len(mnames), info["data_addr"], info["data_size"]])))
        sources = tmp / "sources.tsv"
        sources.write_text("\n".join(lines) + "\n")
        downloads = tmp / "dl"
        a = Args()
        a.sources, a.downloads = str(sources), str(downloads)
        a.meta_requests, a.span_requests = str(tmp / "meta.tsv"), str(tmp / "span.tsv")
        rounds = fetched = 0
        while gwtc3_pe.cmd_plan(a) == 3:
            rounds += 1
            assert rounds < 20, "planner did not converge"
            fetched += fake_fetch(files, Path(a.meta_requests), Path(a.span_requests))
        total = sum(len(d) for d in files.values())
        assert fetched < total, (fetched, total)
        assert gwtc3_pe.cmd_check_tables(a) == 0
        data_root = tmp / "data"
        a.data_root, a.index, a.stats = str(data_root), str(data_root / "index.jsonl"), str(data_root / "stats.json")
        assert gwtc3_pe.cmd_build(a) == 0
        idx = [json.loads(x) for x in Path(a.index).read_text().splitlines()]
        assert len(idx) == len(events) * len(gwtc3_pe.MEMBERS)
        for event, (mnames, rows) in truth.items():
            for name in gwtc3_pe.MEMBERS:
                j = mnames.index(name)
                got = (data_root / gwtc3_pe.sample_rel(event, name)).read_bytes()
                assert got == struct.pack(f"<{len(rows)}d", *[r[j] for r in rows]), (event, name)
        totals = {}
        for row in idx:
            c, s = totals.get(row["series_id"], (0, 0))
            totals[row["series_id"]] = (c + 1, s + row["sample_size_bytes"])
        manifest = tmp / "manifest.toml"
        manifest.write_text(manifest_text(totals))
        control = tmp / "control.h5"
        control.write_bytes(files[f"{gwtc3_pe.API}/{gwtc3_pe.RECORD_ID}/files/IGWN-GWTC3p0-v2-GW200322_091133_PEDataRelease_mixed_cosmo.h5/content"])
        a.manifest, a.control = str(manifest), str(control)
        assert gwtc3_pe.cmd_verify(a) == 0
        summary = f"selftest: planner converged in {rounds} rounds, fetched {fetched}/{total} bytes; build+verify ok"

        # 3. corruption / drift must be rejected
        rel = gwtc3_pe.sample_rel("GW191103_012549", "a_1")
        good = (data_root / rel).read_bytes()
        (data_root / rel).write_bytes(good[:-8] + struct.pack("<d", 0.5))
        expect_error(lambda: gwtc3_pe.cmd_verify(a), "tampered sample")
        (data_root / rel).write_bytes(good)
        stray = data_root / "samples" / gwtc3_pe.DATASET_ID / "a_1" / "extra.f64"
        stray.write_bytes(good)
        expect_error(lambda: gwtc3_pe.cmd_verify(a), "stray sample")
        stray.unlink()
        manifest.write_text(manifest_text({k: (c, s + 8) for k, (c, s) in totals.items()}))
        expect_error(lambda: gwtc3_pe.cmd_verify(a), "manifest size mismatch")
        manifest.write_text(manifest_text(totals))
        tpath = gwtc3_pe.table_path(downloads, gwtc3_pe.read_sources(sources)[1])
        tgood = tpath.read_bytes()
        tpath.write_bytes(tgood[:-1])
        expect_error(lambda: gwtc3_pe.cmd_build(a), "truncated table")
        mnames, _rows = truth["GW191103_012549"]
        j = mnames.index("luminosity_distance")
        tbad = bytearray(tgood)
        tbad[8 * j:8 * j + 8] = struct.pack("<d", float("nan"))
        tpath.write_bytes(bytes(tbad))
        expect_error(lambda: gwtc3_pe.cmd_check_tables(a), "NaN value")
        tbad[8 * j:8 * j + 8] = struct.pack("<d", 1e9)
        tpath.write_bytes(bytes(tbad))
        expect_error(lambda: gwtc3_pe.cmd_check_tables(a), "out-of-bounds value")
        tpath.write_bytes(tgood)
        drift = sources.read_text().splitlines()
        cols = drift[2].split("\t")
        cols[6] = str(int(cols[6]) + 8)
        drift[2] = "\t".join(cols)
        sources.write_text("\n".join(drift) + "\n")
        expect_error(lambda: gwtc3_pe.cmd_check_tables(a), "pinned table span drift")
    print(summary)
    expect_error(lambda: pe_h5.H5File(b"\x89HDF\r\n\x1a\n\x02" + bytes(200)), "superblock v2")
    print("selftest: corruption checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
