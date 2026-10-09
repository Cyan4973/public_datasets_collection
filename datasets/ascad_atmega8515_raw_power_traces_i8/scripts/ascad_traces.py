#!/usr/bin/env python3
"""ASCAD v1 fixed-key raw ATMega8515 traces: zip-range -> HDF5 -> int8 traces.

Pure standard library. Subcommands:
  check-tail   validate the pinned zip tail (zip64 EOCD + central directory)
  check-range  validate the downloaded member prefix (local header, DEFLATE,
               HDF5 superblock, 'traces' layout) without writing samples
  build        emit the first N complete traces as raw int8 samples + index
  verify       independently re-inflate, re-parse and byte-compare everything
  selftest     exercise the zip/HDF5 parsers on synthetic inputs
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import zlib

DATASET_ID = "ascad_atmega8515_raw_power_traces_i8"
SERIES_ID = "ascad_atmega8515_raw_trace_i8"
NATURAL_RECORD_KIND = "single_aes_execution_oscilloscope_acquisition_trace"

ARCHIVE_BYTES = 4435199469
MEMBER_NAME = "ASCAD_data/ASCAD_databases/ATMega8515_raw_traces.h5"
MEMBER_OFFSET = 72006934
MEMBER_COMPRESSED = 2966104128
MEMBER_UNCOMPRESSED = 6003842144
MEMBER_CRC32 = 0x1CF4A0BF
EXPECTED_TRACES_ADDRESS = 3842144
EXPECTED_TRACES_STORAGE = 6000000000
EXPECTED_DIMS = (60000, 100000)
N_TRACES = 1500

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
INFLATE_BLOCK = 1 << 20


# --------------------------------------------------------------------- zip


def parse_zip_tail(tail: bytes, tail_start: int, archive_bytes: int) -> dict[str, dict]:
    """Parse the zip64 EOCD and central directory contained in ``tail``."""
    if tail_start + len(tail) != archive_bytes:
        raise ValueError("tail does not end at the archive end")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        raise ValueError("no end-of-central-directory record in tail")
    loc = tail.rfind(b"PK\x06\x07", 0, eocd)
    if loc < 0:
        raise ValueError("no zip64 EOCD locator in tail")
    _, _, z64_eocd_off, _ = struct.unpack_from("<IIQI", tail, loc)
    p = z64_eocd_off - tail_start
    if p < 0 or tail[p : p + 4] != b"PK\x06\x06":
        raise ValueError("zip64 EOCD not where the locator says")
    (_, _, _, _, _, _, _, total, cd_size, cd_off) = struct.unpack_from("<IQHHIIQQQQ", tail, p)
    q = cd_off - tail_start
    if q < 0 or q + cd_size > len(tail):
        raise ValueError("central directory not fully inside tail")
    entries: dict[str, dict] = {}
    for _ in range(total):
        if tail[q : q + 4] != b"PK\x01\x02":
            raise ValueError("bad central directory entry signature")
        f = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, q)
        flags, method, crc, csz, usz = f[3], f[4], f[7], f[8], f[9]
        nlen, elen, clen, off = f[10], f[11], f[12], f[16]
        name = tail[q + 46 : q + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        extra = tail[q + 46 + nlen : q + 46 + nlen + elen]
        z64: list[int] = []
        r = 0
        while r + 4 <= len(extra):
            hid, hlen = struct.unpack_from("<HH", extra, r)
            if hid == 1:
                z64 = list(struct.unpack_from(f"<{hlen // 8}Q", extra, r + 4))
            r += 4 + hlen
        it = iter(z64)
        if usz == 0xFFFFFFFF:
            usz = next(it)
        if csz == 0xFFFFFFFF:
            csz = next(it)
        if off == 0xFFFFFFFF:
            off = next(it)
        entries[name] = {
            "flags": flags, "method": method, "crc32": crc,
            "compressed": csz, "uncompressed": usz, "offset": off,
        }
        q += 46 + nlen + elen + clen
    return entries


def check_member_entry(entry: dict) -> None:
    expected = {
        "flags": 0, "method": 8, "crc32": MEMBER_CRC32, "compressed": MEMBER_COMPRESSED,
        "uncompressed": MEMBER_UNCOMPRESSED, "offset": MEMBER_OFFSET,
    }
    for key, value in expected.items():
        if entry.get(key) != value:
            raise ValueError(f"central directory {key} mismatch: {entry.get(key)!r} != {value!r}")


def parse_local_header(buf: bytes, member_name: str) -> int:
    """Return the offset of the DEFLATE stream inside ``buf`` after validation."""
    if buf[:4] != b"PK\x03\x04":
        raise ValueError("range does not start with a zip local file header")
    (_, _version, flags, method, _t, _d, crc, csz, usz, nlen, elen) = struct.unpack_from(
        "<4s5H3I2H", buf, 0
    )
    name = buf[30 : 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    if name != member_name:
        raise ValueError(f"local header names {name!r}, expected {member_name!r}")
    if flags & 0x1:
        raise ValueError("member is encrypted")
    if method != 8:
        raise ValueError(f"member method {method} is not DEFLATE")
    if crc != MEMBER_CRC32:
        raise ValueError(f"local header crc32 {crc:08x} mismatch")
    extra = buf[30 + nlen : 30 + nlen + elen]
    sizes: list[int] = []
    r = 0
    while r + 4 <= len(extra):
        hid, hlen = struct.unpack_from("<HH", extra, r)
        if hid == 1:
            sizes = list(struct.unpack_from(f"<{hlen // 8}Q", extra, r + 4))
        r += 4 + hlen
    it = iter(sizes)
    if usz == 0xFFFFFFFF:
        usz = next(it)
    if csz == 0xFFFFFFFF:
        csz = next(it)
    if usz != MEMBER_UNCOMPRESSED or csz != MEMBER_COMPRESSED:
        raise ValueError(f"local header sizes mismatch: csz={csz} usz={usz}")
    return 30 + nlen + elen


class PrefixInflater:
    """Stream-inflate a raw DEFLATE prefix and serve sequential reads."""

    def __init__(self, path: Path, data_offset: int):
        self._fh = path.open("rb")
        self._fh.seek(data_offset)
        self._dec = zlib.decompressobj(-15)
        self._buf = bytearray()
        self.consumed = 0  # uncompressed bytes already handed out
        self.exhausted = False

    def _fill(self, need: int) -> None:
        while len(self._buf) < need and not self.exhausted:
            block = self._fh.read(INFLATE_BLOCK)
            if not block:
                self.exhausted = True
                break
            self._buf += self._dec.decompress(block)
            if self._dec.eof:
                raise ValueError("DEFLATE stream ended inside the pinned prefix")

    def read(self, n: int) -> bytes:
        self._fill(n)
        if len(self._buf) < n:
            raise ValueError(
                f"inflated prefix too short: need {self.consumed + n} uncompressed bytes, "
                f"have {self.consumed + len(self._buf)}"
            )
        out = bytes(self._buf[:n])
        del self._buf[:n]
        self.consumed += n
        return out

    def close(self) -> None:
        self._fh.close()


# -------------------------------------------------------------------- hdf5


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _u64(b: bytes, o: int) -> int:
    return struct.unpack_from("<Q", b, o)[0]


def _need(b: bytes, o: int, n: int, what: str) -> None:
    if o < 0 or o + n > len(b):
        raise ValueError(f"{what} at {o}+{n} lies outside the parsed HDF5 prefix ({len(b)} B)")


def _object_messages(b: bytes, addr: int) -> list[tuple[int, bytes]]:
    _need(b, addr, 16, "object header")
    if b[addr] != 1:
        raise ValueError(f"object header at {addr} is not version 1")
    count = _u16(b, addr + 2)
    size = _u32(b, addr + 8)
    _need(b, addr + 16, size, "object header body")
    out: list[tuple[int, bytes]] = []
    blocks = [(addr + 16, size)]
    while blocks and len(out) < count:
        cur, length = blocks.pop(0)
        end = cur + length
        while cur + 8 <= end and len(out) < count:
            mtype, msize = _u16(b, cur), _u16(b, cur + 2)
            payload = bytes(b[cur + 8 : cur + 8 + msize])
            if cur + 8 + msize > end:
                raise ValueError("object header message overruns its block")
            if mtype == 0x10:  # continuation
                caddr, clen = _u64(payload, 0), _u64(payload, 8)
                _need(b, caddr, clen, "object header continuation")
                blocks.append((caddr, clen))
            out.append((mtype, payload))
            cur += 8 + msize
    return out


def _cstr(b: bytes, o: int) -> str:
    end = b.index(b"\0", o)
    return b[o:end].decode("ascii")


def _group_links(b: bytes, btree: int, heap: int) -> dict[str, int]:
    _need(b, heap, 32, "local heap")
    if b[heap : heap + 4] != b"HEAP" or b[heap + 4] != 0:
        raise ValueError("bad local heap")
    seg = _u64(b, heap + 24)
    links: dict[str, int] = {}

    def walk(node: int) -> None:
        _need(b, node, 24, "group B-tree node")
        if b[node : node + 4] != b"TREE" or b[node + 4] != 0:
            raise ValueError("bad group B-tree node")
        level, entries = b[node + 5], _u16(b, node + 6)
        for i in range(entries):
            child = _u64(b, node + 24 + 8 + i * 16)
            if level > 0:
                walk(child)
                continue
            _need(b, child, 8, "symbol table node")
            if b[child : child + 4] != b"SNOD" or b[child + 4] != 1:
                raise ValueError("bad symbol table node")
            for k in range(_u16(b, child + 6)):
                e = child + 8 + 40 * k
                name_off, ohdr = _u64(b, e), _u64(b, e + 8)
                links[_cstr(b, seg + name_off)] = ohdr

    walk(btree)
    return links


def parse_traces_dataset(b: bytes, eof_expected: int) -> dict:
    """Parse HDF5 v0 superblock -> root group -> 'traces' dataset layout."""
    _need(b, 0, 96, "superblock")
    if b[:8] != HDF5_SIGNATURE:
        raise ValueError("missing HDF5 signature")
    if b[8] != 0:
        raise ValueError(f"superblock version {b[8]} is not 0")
    if b[13] != 8 or b[14] != 8:
        raise ValueError("HDF5 offsets/lengths are not 8 bytes")
    base, eof = _u64(b, 24), _u64(b, 40)
    if base != 0:
        raise ValueError("non-zero HDF5 base address")
    if eof != eof_expected:
        raise ValueError(f"HDF5 end-of-file address {eof} != member size {eof_expected}")
    # root group symbol table entry at 56
    root_ohdr = _u64(b, 64)
    root_msgs = _object_messages(b, root_ohdr)
    stabs = [p for t, p in root_msgs if t == 0x11]
    if len(stabs) != 1:
        raise ValueError("root group lacks a single symbol table message")
    links = _group_links(b, _u64(stabs[0], 0), _u64(stabs[0], 8))
    if "traces" not in links:
        raise ValueError(f"root group has no 'traces' link: {sorted(links)}")
    msgs = _object_messages(b, links["traces"])
    kinds = [t for t, _ in msgs]
    if 0x0B in kinds:
        raise ValueError("'traces' has a filter pipeline; expected unfiltered storage")
    one = lambda t: [p for k, p in msgs if k == t]  # noqa: E731
    space, dtype, layout = one(0x01), one(0x03), one(0x08)
    if len(space) != 1 or len(dtype) != 1 or len(layout) != 1:
        raise ValueError("'traces' lacks single dataspace/datatype/layout messages")
    sp = space[0]
    if sp[0] == 1:
        rank, dims_at = sp[1], 8
    elif sp[0] == 2:
        rank, dims_at = sp[1], 4
    else:
        raise ValueError(f"unsupported dataspace version {sp[0]}")
    dims = tuple(_u64(sp, dims_at + 8 * i) for i in range(rank))
    dt = dtype[0]
    dclass, dver = dt[0] & 0x0F, dt[0] >> 4
    bits0 = dt[1]
    dsize = _u32(dt, 4)
    if dclass != 0 or dsize != 1:
        raise ValueError(f"'traces' datatype is not a 1-byte fixed-point type (class={dclass} size={dsize})")
    signed = bool(bits0 & 0x08)
    big_endian = bool(bits0 & 0x01)
    bit_offset, precision = _u16(dt, 8), _u16(dt, 10)
    if not signed or big_endian or bit_offset != 0 or precision != 8:
        raise ValueError("'traces' datatype is not signed little-endian 8-bit")
    ly = layout[0]
    if ly[0] != 3 or ly[1] != 1:
        raise ValueError(f"'traces' layout is not v3 contiguous (version={ly[0]} class={ly[1]})")
    address, storage = _u64(ly, 2), _u64(ly, 10)
    if storage != math.prod(dims) * dsize:
        raise ValueError("contiguous storage size disagrees with dims")
    if address + storage > eof:
        raise ValueError("contiguous storage exceeds HDF5 file")
    return {
        "root_links": sorted(links),
        "dims": list(dims),
        "datatype_version": dver,
        "signed": signed,
        "element_bytes": dsize,
        "address": address,
        "storage_bytes": storage,
    }


def check_expected_layout(info: dict) -> None:
    if tuple(info["dims"]) != EXPECTED_DIMS:
        raise ValueError(f"traces dims {info['dims']} != {EXPECTED_DIMS}")
    if info["address"] != EXPECTED_TRACES_ADDRESS:
        raise ValueError(f"traces address {info['address']} != {EXPECTED_TRACES_ADDRESS}")
    if info["storage_bytes"] != EXPECTED_TRACES_STORAGE:
        raise ValueError(f"traces storage {info['storage_bytes']} != {EXPECTED_TRACES_STORAGE}")


def open_traces(range_path: Path) -> tuple[PrefixInflater, dict]:
    """Inflate the member prefix, parse the HDF5 header, position at trace 0."""
    with range_path.open("rb") as fh:
        head = fh.read(4096)
    data_offset = parse_local_header(head, MEMBER_NAME)
    inflater = PrefixInflater(range_path, data_offset)
    header = inflater.read(EXPECTED_TRACES_ADDRESS)
    info = parse_traces_dataset(header, MEMBER_UNCOMPRESSED)
    check_expected_layout(info)
    # parsed address equals what we consumed (asserted above), so the next
    # inflated byte is traces[0, 0].
    return inflater, info


# ------------------------------------------------------------------ stats


def trace_stats(payload: bytes) -> dict:
    vals = memoryview(payload).cast("b")
    hist = [0] * 256
    for v in payload:
        hist[v] += 1
    n = len(payload)
    present = [(i if i < 128 else i - 256, c) for i, c in enumerate(hist) if c]
    lo = min(v for v, _ in present)
    hi = max(v for v, _ in present)
    mean = sum(v * c for v, c in present) / n
    var = sum(c * (v - mean) ** 2 for v, c in present) / n
    h0 = -sum(c / n * math.log2(c / n) for _, c in present)
    top = max(c for _, c in present) / n
    del vals
    return {
        "min": lo, "max": hi, "distinct_values": len(present), "mean": round(mean, 6),
        "std": round(math.sqrt(var), 6), "entropy_bits": round(h0, 6),
        "dominant_value_fraction": round(top, 6),
    }


def check_trace(payload: bytes, idx: int) -> dict:
    if len(payload) != EXPECTED_DIMS[1]:
        raise ValueError(f"trace {idx} has {len(payload)} bytes")
    st = trace_stats(payload)
    if st["min"] == st["max"]:
        raise ValueError(f"trace {idx} is constant")
    if st["distinct_values"] < 32:
        raise ValueError(f"trace {idx} is degenerate: {st['distinct_values']} distinct values")
    if st["dominant_value_fraction"] > 0.5:
        raise ValueError(f"trace {idx} dominated by one value ({st['dominant_value_fraction']})")
    if st["min"] == -128 and st["max"] == 127 and st["dominant_value_fraction"] > 0.2:
        raise ValueError(f"trace {idx} looks saturated")
    return st


class InterTrace:
    """Per-position running moments and adjacent-trace differences."""

    def __init__(self, length: int):
        self.n = 0
        self.s = [0] * length
        self.s2 = [0] * length
        self.prev: bytes | None = None
        self.adj_mad: list[float] = []
        self.dup_adjacent = 0

    def add(self, payload: bytes) -> None:
        vals = memoryview(payload).cast("b").tolist()
        s, s2 = self.s, self.s2
        for j, v in enumerate(vals):
            s[j] += v
            s2[j] += v * v
        if self.prev is not None:
            if payload == self.prev:
                self.dup_adjacent += 1
            pv = memoryview(self.prev).cast("b").tolist()
            self.adj_mad.append(sum(abs(a - c) for a, c in zip(vals, pv)) / len(vals))
        self.prev = payload
        self.n += 1

    def summary(self) -> dict:
        n, L = self.n, len(self.s)
        pos_var = sum(self.s2[j] / n - (self.s[j] / n) ** 2 for j in range(L)) / L
        tot_mean = sum(self.s) / (n * L)
        tot_var = sum(self.s2) / (n * L) - tot_mean ** 2
        mad = sorted(self.adj_mad)
        return {
            "traces": n,
            "mean_per_position_inter_trace_variance": round(pos_var, 6),
            "total_variance": round(tot_var, 6),
            "inter_trace_variance_fraction": round(pos_var / tot_var, 6),
            "adjacent_mean_abs_diff_min": round(mad[0], 6),
            "adjacent_mean_abs_diff_median": round(mad[len(mad) // 2], 6),
            "adjacent_mean_abs_diff_max": round(mad[-1], 6),
            "identical_adjacent_traces": self.dup_adjacent,
        }


# --------------------------------------------------------------- commands


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while blk := fh.read(8 << 20):
            h.update(blk)
    return h.hexdigest()


def cmd_check_tail(args: argparse.Namespace) -> None:
    tail = args.tail.read_bytes()
    entries = parse_zip_tail(tail, ARCHIVE_BYTES - len(tail), ARCHIVE_BYTES)
    if MEMBER_NAME not in entries:
        raise SystemExit(f"member {MEMBER_NAME} not in central directory")
    check_member_entry(entries[MEMBER_NAME])
    print(f"zip_tail_validation=ok entries={len(entries)} member_offset={MEMBER_OFFSET} "
          f"method=8 compressed={MEMBER_COMPRESSED} uncompressed={MEMBER_UNCOMPRESSED}")


def cmd_check_range(args: argparse.Namespace) -> None:
    inflater, info = open_traces(args.range)
    try:
        need = N_TRACES * EXPECTED_DIMS[1]
        got = 0
        while got < need:
            got += len(inflater.read(min(8 << 20, need - got)))
    finally:
        inflater.close()
    print(f"range_validation=ok traces_address={info['address']} dims={info['dims']} "
          f"inflated_through={EXPECTED_TRACES_ADDRESS + need}")


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    root = args.data_root.resolve()
    return (root, root / "samples" / DATASET_ID / SERIES_ID,
            root / "index" / DATASET_ID / "samples.jsonl",
            root / "filtered" / DATASET_ID / "ingest_stats.json")


def cmd_build(args: argparse.Namespace) -> None:
    root, out_dir, index_path, stats_path = _paths(args)
    tmp_dir = out_dir.parent / f".{SERIES_ID}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    inflater, info = open_traces(args.range)
    rows, agg, inter = [], hashlib.sha256(), InterTrace(EXPECTED_DIMS[1])
    gmin, gmax = 127, -128
    distinct = []
    try:
        if info["dims"][0] < N_TRACES:
            raise ValueError("fewer traces in file than requested")
        for i in range(N_TRACES):
            payload = inflater.read(EXPECTED_DIMS[1])
            st = check_trace(payload, i)
            inter.add(payload)
            gmin, gmax = min(gmin, st["min"]), max(gmax, st["max"])
            distinct.append(st["distinct_values"])
            agg.update(payload)
            name = f"trace_{i:05d}.bin"
            (tmp_dir / name).write_bytes(payload)
            rows.append({
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
                "sample_path": (out_dir / name).relative_to(root).as_posix(),
                "numeric_kind": "int", "bit_width": 8, "endianness": "little",
                "element_size_bytes": 1, "sample_size_bytes": EXPECTED_DIMS[1],
                "value_count": EXPECTED_DIMS[1], "shape": [EXPECTED_DIMS[1]],
                "natural_record_kind": NATURAL_RECORD_KIND,
                "source_member": MEMBER_NAME, "source_field": "/traces",
                "trace_index": i, "sample_sha256": hashlib.sha256(payload).hexdigest(),
                **st,
            })
            if (i + 1) % 250 == 0:
                print(f"traces_written={i + 1}/{N_TRACES}", flush=True)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    finally:
        inflater.close()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.replace(out_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    ds = sorted(distinct)
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "hdf5": info,
        "sample_count": len(rows), "total_values": len(rows) * EXPECTED_DIMS[1],
        "total_size_bytes": len(rows) * EXPECTED_DIMS[1],
        "aggregate_sha256": agg.hexdigest(), "min": gmin, "max": gmax,
        "distinct_values_per_trace": {"min": ds[0], "median": ds[len(ds) // 2], "max": ds[-1]},
        "inter_trace": inter.summary(),
        "range_sha256": file_sha256(args.range),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    root, out_dir, index_path, stats_path = _paths(args)
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != N_TRACES:
        raise SystemExit(f"index has {len(rows)} rows, expected {N_TRACES}")
    on_disk = sorted(p.name for p in out_dir.iterdir())
    if on_disk != [f"trace_{i:05d}.bin" for i in range(N_TRACES)]:
        raise SystemExit("sample directory does not hold exactly the expected trace files")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    inflater, info = open_traces(args.range)
    agg = hashlib.sha256()
    seen: set[str] = set()
    try:
        for i, row in enumerate(rows):
            expect = {
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
                "numeric_kind": "int", "bit_width": 8, "endianness": "little",
                "element_size_bytes": 1, "sample_size_bytes": EXPECTED_DIMS[1],
                "value_count": EXPECTED_DIMS[1], "trace_index": i,
                "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/trace_{i:05d}.bin",
            }
            for k, v in expect.items():
                if row.get(k) != v:
                    raise SystemExit(f"index row {i} field {k}={row.get(k)!r}, expected {v!r}")
            ref = inflater.read(EXPECTED_DIMS[1])
            sample = (root / row["sample_path"]).read_bytes()
            if sample != ref:
                raise SystemExit(f"trace {i} differs from re-inflated source")
            digest = hashlib.sha256(sample).hexdigest()
            if digest != row["sample_sha256"]:
                raise SystemExit(f"trace {i} sha256 mismatch")
            if digest in seen:
                raise SystemExit(f"trace {i} duplicates an earlier trace exactly")
            seen.add(digest)
            st = check_trace(sample, i)
            for k in ("min", "max", "distinct_values"):
                if st[k] != row[k]:
                    raise SystemExit(f"trace {i} stat {k} mismatch")
            agg.update(sample)
    finally:
        inflater.close()
    if agg.hexdigest() != stats["aggregate_sha256"]:
        raise SystemExit("aggregate sha256 mismatch")
    if info["dims"] != stats["hdf5"]["dims"] or info["address"] != stats["hdf5"]["address"]:
        raise SystemExit("HDF5 layout disagrees with build stats")
    total = sum(r["sample_size_bytes"] for r in rows)
    print(f"verify=ok samples={len(rows)} total_bytes={total} aggregate_sha256={agg.hexdigest()}")


# ---------------------------------------------------------------- selftest


def _synthetic_hdf5(n: int, length: int, signed: bool = True, filtered: bool = False) -> bytes:
    """Build a minimal HDF5 v0 file with root group {'meta','traces'}."""
    b = bytearray(0x1000)
    b[0:8] = HDF5_SIGNATURE
    b[8] = 0
    b[13], b[14] = 8, 8
    struct.pack_into("<HH", b, 16, 4, 16)
    root_oh, btree, heap, seg, snod, traces_oh, data = 0x60, 0x88, 0x2A8, 0x2C8, 0x460, 0x5A8, 0x800
    storage = n * length
    struct.pack_into("<QQQQ", b, 24, 0, 0xFFFFFFFFFFFFFFFF, data + storage, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into("<QQII", b, 56, 0, root_oh, 1, 0)
    struct.pack_into("<QQ", b, 80, btree, heap)
    # root object header: one symbol-table message
    struct.pack_into("<BBHII", b, root_oh, 1, 0, 1, 1, 24)
    struct.pack_into("<HHB3x", b, root_oh + 16, 0x11, 16, 1)
    struct.pack_into("<QQ", b, root_oh + 24, btree, heap)
    b[btree:btree + 4] = b"TREE"
    struct.pack_into("<BBHQQ", b, btree + 4, 0, 0, 1, 2**64 - 1, 2**64 - 1)
    struct.pack_into("<QQQ", b, btree + 24, 0, snod, 16)
    b[heap:heap + 4] = b"HEAP"
    struct.pack_into("<QQQ", b, heap + 8, 32, 2**64 - 1, seg)
    b[seg + 8:seg + 13] = b"meta\0"
    b[seg + 16:seg + 23] = b"traces\0"
    b[snod:snod + 4] = b"SNOD"
    struct.pack_into("<BBH", b, snod + 4, 1, 0, 2)
    struct.pack_into("<QQII", b, snod + 8, 8, 0x700, 0, 0)
    struct.pack_into("<QQII", b, snod + 48, 16, traces_oh, 0, 0)
    msgs = []
    msgs.append((0x01, struct.pack("<BBB5xQQ", 1, 2, 0, n, length)))
    msgs.append((0x03, bytes([0x10, 0x08 if signed else 0x00, 0, 0]) + struct.pack("<IHH", 1, 0, 8)))
    if filtered:
        msgs.append((0x0B, b"\x01\x00" + b"\x00" * 14))
    msgs.append((0x08, struct.pack("<BBQQ", 3, 1, data, storage) + b"\0" * 6))
    body = b"".join(struct.pack("<HHB3x", t, len(p), 0) + p for t, p in msgs)
    struct.pack_into("<BBHII", b, traces_oh, 1, 0, len(msgs), 1, len(body))
    b[traces_oh + 16:traces_oh + 16 + len(body)] = body
    b = b[:data]
    payload = bytes(((i * 7 + (i // length) * 3) % 200) - 100 & 0xFF for i in range(storage))
    return bytes(b) + payload


def cmd_selftest(_args: argparse.Namespace) -> None:
    h5 = _synthetic_hdf5(4, 300)
    info = parse_traces_dataset(h5, len(h5))
    assert info["dims"] == [4, 300] and info["address"] == 0x800 and info["storage_bytes"] == 1200, info
    assert info["root_links"] == ["meta", "traces"], info
    for bad, why in ((_synthetic_hdf5(4, 300, signed=False), "unsigned"),
                     (_synthetic_hdf5(4, 300, filtered=True), "filtered")):
        try:
            parse_traces_dataset(bad, len(bad))
        except ValueError:
            pass
        else:
            raise AssertionError(f"parser accepted {why} datatype")
    try:
        parse_traces_dataset(h5, len(h5) + 1)
    except ValueError:
        pass
    else:
        raise AssertionError("parser accepted wrong EOF")
    # zip local header + raw deflate round trip with a zip64 extra field
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    stream = comp.compress(h5) + comp.flush()
    name = MEMBER_NAME.encode()
    extra = struct.pack("<HHQQ", 1, 16, MEMBER_UNCOMPRESSED, MEMBER_COMPRESSED)
    lh = struct.pack("<4s5H3I2H", b"PK\x03\x04", 45, 0, 8, 0, 0, MEMBER_CRC32,
                     0xFFFFFFFF, 0xFFFFFFFF, len(name), len(extra)) + name + extra
    blob = lh + stream
    off = parse_local_header(blob, MEMBER_NAME)
    assert off == len(lh)
    dec = zlib.decompressobj(-15)
    assert dec.decompress(blob[off:]) == h5
    try:
        parse_local_header(blob.replace(b"PK\x03\x04", b"PK\x03\x05", 1), MEMBER_NAME)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted bad local header")
    # zip64 central directory parse
    cd_name = name
    cd_extra = struct.pack("<HHQQQ", 1, 24, MEMBER_UNCOMPRESSED, MEMBER_COMPRESSED, MEMBER_OFFSET)
    cd = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 45, 45, 0, 8, 0, 0, MEMBER_CRC32,
                     0xFFFFFFFF, 0xFFFFFFFF, len(cd_name), len(cd_extra), 0, 0, 0, 0,
                     0xFFFFFFFF) + cd_name + cd_extra
    archive = 1000
    tail_start = archive - (len(cd) + 56 + 20 + 22)
    z64 = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, 1, 1, len(cd), tail_start)
    loc = struct.pack("<IIQI", 0x07064B50, 0, tail_start + len(cd), 1)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    tail = cd + z64 + loc + eocd
    entries = parse_zip_tail(tail, tail_start, archive)
    check_member_entry(entries[MEMBER_NAME])
    # trace checks
    good = bytes(((i % 150) - 75) & 0xFF for i in range(EXPECTED_DIMS[1]))
    check_trace(good, 0)
    for bad in (bytes(EXPECTED_DIMS[1]), bytes([1, 2] * (EXPECTED_DIMS[1] // 2))):
        try:
            check_trace(bad, 0)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted degenerate trace")
    print("selftest=ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-tail")
    p.add_argument("--tail", type=Path, required=True)
    for name in ("check-range", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--range", type=Path, required=True)
        p.add_argument("--data-root", type=Path, default=Path(".data"))
    sub.add_parser("selftest")
    args = ap.parse_args()
    {"check-tail": cmd_check_tail, "check-range": cmd_check_range, "build": cmd_build,
     "verify": cmd_verify, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
