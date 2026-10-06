#!/usr/bin/env python3
"""Dependency-free MATLAB Level-5 MAT reader for LUMO SHMTS files.

Each LUMO SHMTS_<yyyymmddHHMM>.mat file stores one 10-minute acquisition as a
1x1 struct variable `Dat` (inside one top-level miCOMPRESSED element) with the
fields Timestamps (MCOS datetime opaque object), Time (char start time), Fs
(double sampling rate), ChannelNames / ChannelUnits (1x22 cell arrays of char)
and Data (mxSINGLE rows x 22 matrix, column-major miSINGLE payload).

Subcommands:
  selftest   build synthetic MAT files and check the parser against them
  check      validate one extracted MAT file's schema (used by download.sh)
  build      emit one little-endian float32 sample per accelerometer channel
  verify     independently re-derive every sample and check the index
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "luh_lumo_tower_acceleration_f32"
SERIES_ID = "lumo_tower_acceleration_f32"

MI_INT8, MI_UINT8, MI_INT16, MI_UINT16, MI_INT32, MI_UINT32 = 1, 2, 3, 4, 5, 6
MI_SINGLE, MI_DOUBLE, MI_INT64, MI_UINT64 = 7, 9, 12, 13
MI_MATRIX, MI_COMPRESSED, MI_UTF8, MI_UTF16, MI_UTF32 = 14, 15, 16, 17, 18
MX_CELL, MX_STRUCT, MX_OBJECT, MX_CHAR, MX_SPARSE = 1, 2, 3, 4, 5
MX_DOUBLE, MX_SINGLE, MX_OPAQUE = 6, 7, 17
NUMERIC_CLASSES = set(range(6, 16))
NUMERIC_FORMATS = {
    MI_INT8: "b", MI_UINT8: "B", MI_INT16: "h", MI_UINT16: "H", MI_INT32: "i",
    MI_UINT32: "I", MI_SINGLE: "f", MI_DOUBLE: "d", MI_INT64: "q", MI_UINT64: "Q",
}

EXPECTED_FS = 1651.6129032258063
N_COLUMNS = 22
ACCEL_CHANNELS = [f"accel{level:02d}{axis}" for level in range(1, 10) for axis in ("x", "y")]
ACCEL_UNIT = "g"
EXCLUDED_CHANNELS = ["strain01", "strain02", "strain03", "temp01"]
STRUCT_FIELDS = ["Timestamps", "Time", "Fs", "ChannelNames", "ChannelUnits", "Data"]


class MatError(ValueError):
    pass


# --------------------------------------------------------------------------
# Low-level element parsing
# --------------------------------------------------------------------------

def read_tag(buf, pos: int, end: int) -> tuple[int, int, int, int]:
    """Return (type, nbytes, data_offset, next_offset) for the element at pos."""
    if pos + 8 > end:
        raise MatError(f"truncated element tag at {pos}")
    first, second = struct.unpack_from("<II", buf, pos)
    if first >> 16:
        dtype, nbytes = first & 0xFFFF, first >> 16
        if nbytes > 4:
            raise MatError(f"small data element with {nbytes} bytes at {pos}")
        return dtype, nbytes, pos + 4, pos + 8
    dtype, nbytes = first, second
    data = pos + 8
    if dtype == MI_COMPRESSED:
        nxt = data + nbytes
    else:
        nxt = data + ((nbytes + 7) & ~7)
    return dtype, nbytes, data, nxt


def decode_numbers(buf, dtype: int, data: int, nbytes: int) -> list:
    fmt = NUMERIC_FORMATS.get(dtype)
    if fmt is None:
        raise MatError(f"unsupported numeric data type {dtype}")
    size = struct.calcsize(fmt)
    if nbytes % size:
        raise MatError(f"numeric payload {nbytes} not a multiple of {size}")
    return list(struct.unpack_from(f"<{nbytes // size}{fmt}", buf, data))


def decode_text(buf, dtype: int, data: int, nbytes: int) -> str:
    raw = bytes(buf[data:data + nbytes])
    if dtype in (MI_UTF8, MI_INT8, MI_UINT8):
        return raw.decode("utf-8")
    if dtype in (MI_UINT16, MI_UTF16):
        return raw.decode("utf-16-le")
    if dtype == MI_UTF32:
        return raw.decode("utf-32-le")
    raise MatError(f"unsupported char data type {dtype}")


def parse_matrix(buf, start: int, end: int, *, allow_truncated_payload: bool = False) -> dict:
    """Parse the contents of one miMATRIX element occupying buf[start:end]."""
    node: dict = {}
    if start == end:
        node.update(cls=None, dims=[0, 0], name="", empty=True)
        return node
    dtype, nbytes, data, pos = read_tag(buf, start, end)
    if dtype != MI_UINT32 or nbytes != 8:
        raise MatError(f"bad array-flags subelement type={dtype} nbytes={nbytes}")
    flags, _nzmax = struct.unpack_from("<II", buf, data)
    cls = flags & 0xFF
    node["cls"] = cls
    node["complex"] = bool(flags & 0x800)
    if cls == MX_OPAQUE:
        node.update(dims=None, name="", opaque=True, nbytes=end - start)
        return node
    dtype, nbytes, data, pos = read_tag(buf, pos, end)
    if dtype != MI_INT32 or nbytes % 4 or nbytes < 8:
        raise MatError(f"bad dimensions subelement type={dtype} nbytes={nbytes}")
    dims = list(struct.unpack_from(f"<{nbytes // 4}i", buf, data))
    node["dims"] = dims
    dtype, nbytes, data, pos = read_tag(buf, pos, end)
    if dtype not in (MI_INT8, MI_UINT8):
        raise MatError(f"bad array-name subelement type={dtype}")
    node["name"] = bytes(buf[data:data + nbytes]).decode("ascii")
    count = math.prod(dims)
    if cls == MX_STRUCT:
        dtype, nbytes, data, pos = read_tag(buf, pos, end)
        if dtype != MI_INT32 or nbytes != 4:
            raise MatError("bad field-name-length subelement")
        flen = struct.unpack_from("<i", buf, data)[0]
        dtype, nbytes, data, pos = read_tag(buf, pos, end)
        if dtype not in (MI_INT8, MI_UINT8) or flen <= 0 or nbytes % flen:
            raise MatError("bad field-names subelement")
        names = [
            bytes(buf[data + i:data + i + flen]).split(b"\0", 1)[0].decode("ascii")
            for i in range(0, nbytes, flen)
        ]
        node["field_names"] = names
        if count != 1:
            raise MatError(f"only 1x1 structs are supported, got dims {dims}")
        fields: dict = {}
        for fname in names:
            dtype, nbytes, data, nxt = read_tag(buf, pos, end)
            if dtype != MI_MATRIX:
                raise MatError(f"struct field {fname} is not miMATRIX (type {dtype})")
            if data + nbytes > end and not allow_truncated_payload:
                raise MatError(f"struct field {fname} overruns its parent")
            fields[fname] = parse_matrix(
                buf, data, min(data + nbytes, end) if allow_truncated_payload else data + nbytes,
                allow_truncated_payload=allow_truncated_payload,
            )
            fields[fname]["element_end"] = data + nbytes
            pos = nxt
        node["fields"] = fields
    elif cls == MX_CELL:
        cells = []
        for _ in range(count):
            dtype, nbytes, data, nxt = read_tag(buf, pos, end)
            if dtype != MI_MATRIX or data + nbytes > end:
                raise MatError("bad cell element")
            cells.append(parse_matrix(buf, data, data + nbytes))
            pos = nxt
        node["cells"] = cells
    elif cls == MX_CHAR:
        if count == 0:
            node["text"] = ""
        else:
            dtype, nbytes, data, pos = read_tag(buf, pos, end)
            node["text"] = decode_text(buf, dtype, data, nbytes)
    elif cls in NUMERIC_CLASSES:
        if node["complex"]:
            raise MatError("complex numeric arrays are not supported")
        dtype, nbytes, data, nxt = read_tag(buf, pos, end)
        node.update(data_type=dtype, data_offset=data, data_nbytes=nbytes)
        if data + nbytes > end and not allow_truncated_payload:
            raise MatError("numeric payload overruns its element")
        if nbytes <= 4096 and data + nbytes <= end:
            node["values"] = decode_numbers(buf, dtype, data, nbytes)
    else:
        raise MatError(f"unsupported MATLAB class {cls}")
    return node


def check_header(mat) -> None:
    if len(mat) < 128:
        raise MatError("file shorter than the 128-byte MAT header")
    text = bytes(mat[:116])
    if not text.startswith(b"MATLAB 5.0 MAT-file"):
        raise MatError(f"not a MAT v5 file: {text[:40]!r}")
    version = struct.unpack_from("<H", mat, 124)[0]
    if version != 0x0100 or bytes(mat[126:128]) != b"IM":
        raise MatError("unexpected MAT version or non-little-endian file")


def load_dat(mat: bytes) -> tuple[dict, bytes, list[dict]]:
    """Return (Dat struct node, decompressed Dat element bytes, top-level element summaries)."""
    check_header(mat)
    pos = 128
    end = len(mat)
    top: list[dict] = []
    dat_node = None
    dat_buf = None
    while pos < end:
        dtype, nbytes, data, nxt = read_tag(mat, pos, end)
        if nxt > end:
            raise MatError(f"top-level element at {pos} overruns the file")
        if dtype != MI_COMPRESSED:
            raise MatError(f"unexpected uncompressed top-level element type {dtype} at {pos}")
        dec = zlib.decompressobj()
        inner = dec.decompress(memoryview(mat)[data:data + nbytes])
        inner += dec.flush()
        if not dec.eof or dec.unused_data:
            raise MatError(f"top-level zlib stream at {pos} is incomplete or has trailing data")
        itype, inbytes, idata, inext = read_tag(inner, 0, len(inner))
        if itype != MI_MATRIX or idata + inbytes != len(inner):
            raise MatError(f"top-level element at {pos} is not exactly one miMATRIX")
        node = parse_matrix(inner, idata, idata + inbytes)
        top.append({"offset": pos, "compressed_bytes": nbytes, "name": node.get("name"), "cls": node.get("cls")})
        if node.get("name") == "Dat":
            if dat_node is not None:
                raise MatError("duplicate Dat variable")
            dat_node, dat_buf = node, inner
        pos = nxt
    if pos != end:
        raise MatError("top-level elements do not end at the file end")
    if dat_node is None:
        raise MatError("no Dat variable")
    return dat_node, dat_buf, top


def cell_strings(node: dict) -> list[str]:
    if node.get("cls") != MX_CELL:
        raise MatError("expected a cell array")
    out = []
    for cell in node["cells"]:
        if cell.get("cls") != MX_CHAR:
            raise MatError("expected char cells")
        out.append(cell["text"])
    return out


def validate_dat(node: dict, buf) -> dict:
    """Schema checks shared by check/build/verify; returns decoded metadata."""
    if node.get("cls") != MX_STRUCT or node.get("dims") != [1, 1]:
        raise MatError("Dat is not a 1x1 struct")
    if node["field_names"] != STRUCT_FIELDS:
        raise MatError(f"unexpected Dat fields {node['field_names']}")
    fields = node["fields"]
    if fields["Timestamps"].get("cls") != MX_OPAQUE:
        raise MatError("Timestamps is not an opaque (MCOS) object")
    time_node = fields["Time"]
    # Most files store Time as a 1x23 UTF-8 char start time; the 01_Healthy
    # folder stores it as a second MCOS datetime object (start time unknown
    # without the MCOS subsystem, so it is reported as None).
    if time_node.get("cls") not in (MX_CHAR, MX_OPAQUE):
        raise MatError("Time is neither a char array nor an opaque datetime object")
    fs_node = fields["Fs"]
    if fs_node.get("cls") != MX_DOUBLE or fs_node.get("dims") != [1, 1]:
        raise MatError("Fs is not a 1x1 double")
    fs = float(fs_node["values"][0])
    if abs(fs - EXPECTED_FS) > 1e-9:
        raise MatError(f"unexpected Fs {fs!r}")
    names = cell_strings(fields["ChannelNames"])
    units = cell_strings(fields["ChannelUnits"])
    if len(names) != N_COLUMNS or len(units) != N_COLUMNS:
        raise MatError(f"expected {N_COLUMNS} channel names/units, got {len(names)}/{len(units)}")
    if names[:len(ACCEL_CHANNELS)] != ACCEL_CHANNELS:
        raise MatError(f"unexpected accelerometer channel names {names[:18]}")
    if names[len(ACCEL_CHANNELS):] != EXCLUDED_CHANNELS:
        raise MatError(f"unexpected non-accelerometer channel names {names[18:]}")
    if units[:len(ACCEL_CHANNELS)] != [ACCEL_UNIT] * len(ACCEL_CHANNELS):
        raise MatError(f"unexpected accelerometer units {units[:18]}")
    data = fields["Data"]
    if data.get("cls") != MX_SINGLE or data.get("data_type") != MI_SINGLE:
        raise MatError("Data is not an mxSINGLE matrix with a miSINGLE payload")
    rows, cols = data["dims"]
    if cols != N_COLUMNS or rows <= 0:
        raise MatError(f"unexpected Data dims {data['dims']}")
    if data["data_nbytes"] != rows * cols * 4:
        raise MatError("Data payload size does not match its dims")
    if buf is not None and data["data_offset"] + data["data_nbytes"] > len(buf):
        raise MatError("Data payload truncated")
    expected_rows = fs * 600.0
    if not (0.98 * expected_rows <= rows <= 1.01 * expected_rows):
        raise MatError(f"Data rows {rows} are not a ~10-minute record at {fs} Hz")
    return {
        "time": time_node.get("text"),
        "fs_hz": fs,
        "rows": rows,
        "columns": cols,
        "channel_names": names,
        "channel_units": units,
        "data_offset": data["data_offset"],
    }


def column_bytes(buf, meta: dict, column: int) -> bytes:
    rows = meta["rows"]
    start = meta["data_offset"] + column * rows * 4
    return bytes(buf[start:start + rows * 4])


def float_stats(raw: bytes) -> dict:
    """Finiteness, range and lattice statistics computed from the stored float32 values."""
    hi = raw[3::4]
    suspicious = hi.translate(bytes(1 if (b & 0x7F) == 0x7F else 0 for b in range(256)))
    values = array.array("f")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    non_finite = 0
    if b"\x01" in suspicious:
        non_finite = sum(1 for v in values if not math.isfinite(v))
    if non_finite:
        return {"non_finite": non_finite}
    distinct = sorted(set(values))
    steps = [b - a for a, b in zip(distinct, distinct[1:])]
    return {
        "non_finite": 0,
        "min": min(values),
        "max": max(values),
        "mean": math.fsum(values) / len(values),
        "distinct_values": len(distinct),
        "min_positive_step": min(steps) if steps else None,
    }


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# --------------------------------------------------------------------------
# Synthetic MAT writer (self-test only)
# --------------------------------------------------------------------------

def _elem(dtype: int, payload: bytes, small_ok: bool = True) -> bytes:
    n = len(payload)
    if small_ok and n <= 4 and dtype != MI_MATRIX:
        return struct.pack("<HH", dtype, n) + payload + b"\0" * (4 - n)
    pad = (-n) % 8
    return struct.pack("<II", dtype, n) + payload + b"\0" * pad


def _matrix(cls: int, dims: list[int], name: str, body: bytes, small_name: bool = True) -> bytes:
    flags = _elem(MI_UINT32, struct.pack("<II", cls, 0), small_ok=False)
    dims_el = _elem(MI_INT32, struct.pack(f"<{len(dims)}i", *dims), small_ok=False)
    name_el = _elem(MI_INT8, name.encode("ascii"), small_ok=small_name)
    return _elem(MI_MATRIX, flags + dims_el + name_el + body, small_ok=False)


def _char(text: str, name: str = "", dtype: int = MI_UTF8) -> bytes:
    raw = text.encode("utf-8") if dtype == MI_UTF8 else text.encode("utf-16-le")
    return _matrix(MX_CHAR, [1, len(text)], name, _elem(dtype, raw))


def _cell(strings: list[str], name: str = "") -> bytes:
    return _matrix(MX_CELL, [1, len(strings)], name, b"".join(_char(s) for s in strings))


def _opaque() -> bytes:
    flags = _elem(MI_UINT32, struct.pack("<II", MX_OPAQUE, 0), small_ok=False)
    body = _elem(MI_INT8, b"") + _elem(MI_INT8, b"MCOS") + _elem(MI_INT8, b"datetime", small_ok=False)
    ref = _matrix(13, [6, 1], "", _elem(MI_UINT32, struct.pack("<6I", 0xDD000000, 2, 1, 1, 1, 1), small_ok=False))
    return _elem(MI_MATRIX, flags + body + ref, small_ok=False)


def synthetic_mat(columns: list[list[float]], *, names=None, units=None, fs=EXPECTED_FS,
                  extra_subsystem: bool = True, fs_dtype: int = MI_DOUBLE,
                  opaque_time: bool = False) -> bytes:
    rows = len(columns[0])
    names = names or (ACCEL_CHANNELS + EXCLUDED_CHANNELS)
    units = units or ([ACCEL_UNIT] * 18 + ["m/m"] * 3 + ["degC"])
    flen = 13
    fnames = b"".join(f.encode("ascii").ljust(flen, b"\0") for f in STRUCT_FIELDS)
    fs_payload = struct.pack("<d", fs) if fs_dtype == MI_DOUBLE else struct.pack("<f", fs)
    data_payload = b"".join(struct.pack(f"<{rows}f", *col) for col in columns)
    body = (
        _elem(MI_INT32, struct.pack("<i", flen))
        + _elem(MI_INT8, fnames, small_ok=False)
        + _opaque()
        + (_opaque() if opaque_time else _char("2021-06-16 00:28:16.083"))
        + _matrix(MX_DOUBLE, [1, 1], "", _elem(fs_dtype, fs_payload, small_ok=False))
        + _cell(names)
        + _cell(units)
        + _matrix(MX_SINGLE, [rows, len(columns)], "", _elem(MI_SINGLE, data_payload, small_ok=False))
    )
    dat = _matrix(MX_STRUCT, [1, 1], "Dat", body)
    header = b"MATLAB 5.0 MAT-file, Platform: PCWIN64, synthetic".ljust(116, b" ")
    header += struct.pack("<Q", 0) + struct.pack("<H", 0x0100) + b"IM"
    out = header + _elem(MI_COMPRESSED, zlib.compress(dat), small_ok=False)[:8] + zlib.compress(dat)
    if extra_subsystem:
        sub = _matrix(9, [1, 16], "", _elem(MI_UINT8, bytes(range(16)), small_ok=False), small_name=True)
        comp = zlib.compress(sub)
        out += struct.pack("<II", MI_COMPRESSED, len(comp)) + comp
    return out


def selftest() -> None:
    rows = 990_600
    import random
    rng = random.Random(1234)
    step = 2.0 ** -20
    cols = [[round(rng.gauss(0, 0.002) / step) * step for _ in range(2000)] for _ in range(N_COLUMNS)]
    # scale rows to a valid 10-minute length using a cheap repeating pattern
    full = [(col * (rows // 2000 + 1))[:rows] for col in cols]
    full[5][123] = 1.5
    mat = synthetic_mat(full)
    node, buf, top = load_dat(mat)
    meta = validate_dat(node, buf)
    assert meta["rows"] == rows and meta["columns"] == N_COLUMNS, meta
    assert len(top) == 2 and top[0]["name"] == "Dat", top
    for c in (0, 5, 17, 21):
        raw = column_bytes(buf, meta, c)
        expect = struct.pack(f"<{rows}f", *full[c])
        assert raw == expect, f"column {c} mismatch"
    assert meta["time"] == "2021-06-16 00:28:16.083", meta["time"]
    n3, b3, _ = load_dat(synthetic_mat(full, opaque_time=True))
    m3 = validate_dat(n3, b3)
    assert m3["time"] is None and column_bytes(b3, m3, 17) == column_bytes(buf, meta, 17)
    assert locate_data_independent(buf) == (meta["data_offset"], rows, N_COLUMNS)
    assert locate_data_independent(b3) == (m3["data_offset"], rows, N_COLUMNS)
    st = float_stats(column_bytes(buf, meta, 5))
    assert st["non_finite"] == 0 and st["max"] == 1.5, st
    # non-finite detection
    bad = list(full[0])
    bad[10] = float("nan")
    bad[20] = float("inf")
    st = float_stats(struct.pack(f"<{rows}f", *bad))
    assert st["non_finite"] == 2, st
    # wrong unit, wrong names, wrong Fs, truncated file must fail
    for kwargs in (
        {"units": ["m/s^2"] * 18 + ["m/m"] * 3 + ["degC"]},
        {"names": list(reversed(ACCEL_CHANNELS)) + EXCLUDED_CHANNELS},
        {"fs": 1000.0},
    ):
        try:
            n2, b2, _ = load_dat(synthetic_mat(full, **kwargs))
            validate_dat(n2, b2)
        except MatError:
            pass
        else:
            raise AssertionError(f"accepted invalid synthetic file {list(kwargs)}")
    try:
        load_dat(mat[:-7])
    except (MatError, zlib.error):
        pass
    else:
        raise AssertionError("accepted truncated file")
    # small-element tag handling
    t = read_tag(struct.pack("<HH4s", MI_INT8, 3, b"Dat\0"), 0, 8)
    assert t == (MI_INT8, 3, 4, 8), t
    print("selftest=ok")


# --------------------------------------------------------------------------
# Recipe commands
# --------------------------------------------------------------------------

def _read_tsv(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    header = lines[0].split("\t")
    return [dict(zip(header, l.split("\t"))) for l in lines[1:]]


def read_sources(path: Path) -> list[dict]:
    """Pinned members from sources.tsv joined with the SHA-256 pins in mat_sha256.tsv."""
    rows = _read_tsv(path)
    pins = {r["member"]: r["mat_sha256"] for r in _read_tsv(path.parent / "mat_sha256.tsv")}
    if set(pins) != {r["member"] for r in rows}:
        raise MatError("mat_sha256.tsv members differ from sources.tsv")
    for row in rows:
        row["mat_sha256"] = pins[row["member"]]
    return rows


def check_mat_identity(path: Path, raw_mat: bytes, src: dict) -> None:
    if len(raw_mat) != int(src["usize"]) or f"{zlib.crc32(raw_mat) & 0xFFFFFFFF:08x}" != src["crc32"]:
        raise MatError(f"{path}: size/CRC32 differs from the pinned ZIP central-directory entry")
    if sha256(raw_mat) != src["mat_sha256"]:
        raise MatError(f"{path}: SHA-256 differs from the pin in mat_sha256.tsv")


def mat_path(downloads: Path, src: dict) -> Path:
    return downloads / src["zip_tag"] / src["member"]


def sample_rel(src: dict, channel: str) -> str:
    stem = Path(src["member"]).stem
    folder = src["member"].split("/")[0]
    return f"samples/{DATASET_ID}/{SERIES_ID}/{folder}__{stem}__{channel}.f32"


def cmd_check(args) -> None:
    mat = Path(args.mat).read_bytes()
    node, buf, top = load_dat(mat)
    meta = validate_dat(node, buf)
    print(json.dumps({"mat": args.mat, "time": meta["time"], "rows": meta["rows"],
                      "fs_hz": meta["fs_hz"], "top_level_elements": len(top)}))


def cmd_build(args) -> None:
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID
    sources = read_sources(Path(args.sources))
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.f32"):
        stale.unlink()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    rows_out = []
    files_out = []
    for src in sources:
        path = mat_path(downloads, src)
        raw_mat = path.read_bytes()
        check_mat_identity(path, raw_mat, src)
        node, buf, _top = load_dat(raw_mat)
        meta = validate_dat(node, buf)
        files_out.append({"member": src["member"], "state": src["state"], "time": meta["time"],
                          "rows": meta["rows"], "fs_hz": meta["fs_hz"],
                          "mat_sha256": src["mat_sha256"]})
        for column, channel in enumerate(ACCEL_CHANNELS):
            raw = column_bytes(buf, meta, column)
            st = float_stats(raw)
            if st["non_finite"]:
                raise MatError(f"{src['member']} {channel}: {st['non_finite']} non-finite values")
            if st["min"] == st["max"]:
                raise MatError(f"{src['member']} {channel}: constant channel")
            rel = sample_rel(src, channel)
            (data_root / rel).write_bytes(raw)
            rows_out.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(raw),
                "value_count": len(raw) // 4,
                "source_zip": src["zip_name"],
                "source_member": src["member"],
                "structural_state": src["state"],
                "record_start_time": meta["time"],
                "channel": channel,
                "column_index": column,
                "unit": ACCEL_UNIT,
                "sampling_rate_hz": meta["fs_hz"],
                "sha256": sha256(raw),
                "min": st["min"],
                "max": st["max"],
                "distinct_values": st["distinct_values"],
                "min_positive_step": st["min_positive_step"],
            })
        print(f"built member={src['member']} rows={meta['rows']} time={meta['time']}", flush=True)
        del buf, raw_mat, node
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total_bytes = sum(r["sample_size_bytes"] for r in rows_out)
    total_values = sum(r["value_count"] for r in rows_out)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "files": files_out,
        "sample_count": len(rows_out),
        "total_values": total_values,
        "total_bytes": total_bytes,
        "global_min": min(r["min"] for r in rows_out),
        "global_max": max(r["max"] for r in rows_out),
        "median_distinct_values": sorted(r["distinct_values"] for r in rows_out)[len(rows_out) // 2],
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"build_summary samples={len(rows_out)} values={total_values} bytes={total_bytes}")


def locate_data_independent(inner) -> tuple[int, int, int]:
    """Second, minimal locator for the Data payload used by verify.

    It does not use parse_matrix: it walks the Dat element by raw tag sizes
    (array flags, dims, name, field-name length, field names), skips the first
    five struct fields by their miMATRIX byte counts and reads the sixth
    field's dims and miSINGLE tag directly. Returns (offset, rows, cols).
    """
    def tag(pos):
        a, b = struct.unpack_from("<II", inner, pos)
        if a >> 16:
            return a & 0xFFFF, a >> 16, pos + 4, pos + 8
        return a, b, pos + 8, pos + 8 + ((b + 7) & ~7)

    t, n, d, _ = tag(0)
    if t != MI_MATRIX:
        raise MatError("independent locator: Dat is not miMATRIX")
    pos = d
    for _ in range(4):  # flags, dims, name, field-name length
        pos = tag(pos)[3]
    t, n, d, pos = tag(pos)  # field names
    if t != MI_INT8 or n != 13 * 6 or bytes(inner[d + 13 * 5:d + 13 * 5 + 4]) != b"Data":
        raise MatError("independent locator: unexpected field-name table")
    for _ in range(5):
        t, n, d, pos = tag(pos)
        if t != MI_MATRIX:
            raise MatError("independent locator: non-matrix struct field")
    t, n, d, _ = tag(pos)
    if t != MI_MATRIX:
        raise MatError("independent locator: Data is not miMATRIX")
    flags_pos = d
    if struct.unpack_from("<I", inner, tag(flags_pos)[2])[0] & 0xFF != MX_SINGLE:
        raise MatError("independent locator: Data class is not single")
    dims_pos = tag(flags_pos)[3]
    _, dn, dd, name_pos = tag(dims_pos)
    rows, cols = struct.unpack_from("<2i", inner, dd)
    payload_tag = tag(name_pos)[3]
    t, n, d, _ = tag(payload_tag)
    if t != MI_SINGLE or n != rows * cols * 4 or d + n > len(inner):
        raise MatError("independent locator: Data payload tag mismatch")
    return d, rows, cols


def cmd_verify(args) -> None:
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID
    sources = read_sources(Path(args.sources))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise MatError("manifest must declare exactly one series with the expected id")
    series = series[0]
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in index_rows}
    if len(by_path) != len(index_rows):
        raise MatError("duplicate sample paths in the index")
    expected_paths = set()
    hashes = set()
    total_bytes = total_values = 0
    for src in sources:
        path = mat_path(downloads, src)
        raw_mat = path.read_bytes()
        check_mat_identity(path, raw_mat, src)
        node, buf, _ = load_dat(raw_mat)
        meta = validate_dat(node, buf)
        rows = meta["rows"]
        ind_offset, ind_rows, ind_cols = locate_data_independent(buf)
        if (ind_offset, ind_rows, ind_cols) != (meta["data_offset"], rows, N_COLUMNS):
            raise MatError(f"{src['member']}: independent Data locator disagrees with the parser")
        for column, channel in enumerate(ACCEL_CHANNELS):
            rel = sample_rel(src, channel)
            expected_paths.add(rel)
            row = by_path.get(rel)
            if row is None:
                raise MatError(f"missing index row for {rel}")
            sample = (data_root / rel).read_bytes()
            # Independent re-derivation: unpack the column straight from the
            # Data payload by row offsets instead of slicing a column block.
            base = ind_offset + column * rows * 4
            expect = struct.pack(f"<{rows}f", *struct.unpack_from(f"<{rows}f", buf, base))
            if sample != expect:
                raise MatError(f"{rel}: bytes differ from the re-derived Data column")
            values = array.array("f")
            values.frombytes(sample)
            if sys.byteorder != "little":
                values.byteswap()
            lo, hi = min(values), max(values)
            if not (math.isfinite(lo) and math.isfinite(hi)) or any(v != v for v in values):
                raise MatError(f"{rel}: non-finite values")
            if lo == hi:
                raise MatError(f"{rel}: constant sample")
            if len(set(values[:: max(1, rows // 50000)])) < 16:
                raise MatError(f"{rel}: structurally degenerate (fewer than 16 distinct values)")
            checks = {
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float",
                "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
                "sample_size_bytes": len(sample), "value_count": rows, "channel": channel,
                "unit": ACCEL_UNIT, "source_member": src["member"], "sha256": sha256(sample),
                "min": lo, "max": hi,
            }
            for key, value in checks.items():
                if row.get(key) != value:
                    raise MatError(f"{rel}: index field {key}={row.get(key)!r} expected {value!r}")
            if row["sha256"] in hashes:
                raise MatError(f"{rel}: duplicate sample content")
            hashes.add(row["sha256"])
            total_bytes += len(sample)
            total_values += rows
        print(f"verified member={src['member']} rows={rows}", flush=True)
        del buf, raw_mat, node
    if set(by_path) != expected_paths:
        raise MatError(f"index has unexpected rows: {sorted(set(by_path) - expected_paths)[:5]}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}"
               for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*")}
    if on_disk != expected_paths:
        raise MatError("sample directory contains files not in the index (or misses some)")
    if series["sample_count"] != len(expected_paths) or series["total_size_bytes"] != total_bytes:
        raise MatError(
            f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
            f"!= realized {len(expected_paths)}/{total_bytes}"
        )
    if total_bytes > 1_000_000_000:
        raise MatError("primary output exceeds the 1 GB cap")
    print(f"verify_summary samples={len(expected_paths)} values={total_values} bytes={total_bytes}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check")
    p.add_argument("--mat", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--data-root", required=True)
        p.add_argument("--sources", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.cmd == "selftest":
        selftest()
    elif args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "build":
        cmd_build(args)
    else:
        cmd_verify(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MatError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)
