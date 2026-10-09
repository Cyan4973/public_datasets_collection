#!/usr/bin/env python3
"""ambientCG photogrammetry NormalGL maps: extract, strictly decode, build, verify.

Pure standard library. Commands:
  extract   validate one downloaded ZIP local-file-header + STORED member range
            against the pinned table and write the bare PNG
  selftest  decode synthetic 16-bit RGB/RGBA PNGs using all five filter types
            and extract a synthetic STORED zip member; byte-exact comparisons
  build     decode every selected PNG and emit interleaved RGB uint16 LE samples
  verify    independently re-decode, re-derive statistics, and check outputs
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import struct
import sys
import zlib

DATASET_ID = "ambientcg_photogrammetry_normalgl_u16"
SERIES_ID = "normalgl_rgb_u16"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
TSV_COLUMNS = [
    "asset_id", "selected", "release_date", "display_category", "zip_size",
    "member_lho", "member_data_offset", "member_size", "member_crc32",
    "width", "height", "color_type",
]
EXPECTED_SELECTED = 119
# Semantic gates (see README): a genuine 16-bit OpenGL tangent-space normal map.
MIN_DISTINCT_PER_CHANNEL = 256
MAX_MULT257_FRACTION = 0.5     # 8-bit maps upscaled by x257 have hi byte == lo byte
MIN_BLUE_UPPER_HALF = 0.99     # Z = B >= 32768 for outward-facing unit normals


# --------------------------------------------------------------------------- table

def load_table(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines[0].split("\t") != TSV_COLUMNS:
        raise SystemExit(f"unexpected header in {path}")
    rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(TSV_COLUMNS):
            raise SystemExit(f"bad row in {path}: {line!r}")
        row: dict[str, object] = dict(zip(TSV_COLUMNS, parts))
        for key in ("selected", "zip_size", "member_lho", "member_data_offset",
                    "member_size", "width", "height", "color_type"):
            row[key] = int(row[key])  # type: ignore[arg-type]
        rows.append(row)
    ids = [str(r["asset_id"]) for r in rows]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise SystemExit("asset table must be unique and sorted by asset_id")
    for index, row in enumerate(rows):
        if row["selected"] != (1 if index % 3 == 0 else 0):
            raise SystemExit("selection must be every third asset_id in sorted order")
    return rows


def selected_rows(path: Path) -> list[dict[str, object]]:
    rows = [r for r in load_table(path) if r["selected"] == 1]
    if len(rows) != EXPECTED_SELECTED:
        raise SystemExit(f"expected {EXPECTED_SELECTED} selected assets, got {len(rows)}")
    return rows


def member_name(asset: str) -> str:
    return f"{asset}_1K-PNG_NormalGL.png"


# --------------------------------------------------------------------------- extract

def extract_member(row: dict[str, object], range_path: Path, out_path: Path) -> None:
    asset = str(row["asset_id"])
    data = range_path.read_bytes()
    name = member_name(asset).encode()
    header_len = int(row["member_data_offset"]) - int(row["member_lho"])
    size = int(row["member_size"])
    if len(data) != header_len + size:
        raise SystemExit(f"{asset}: range length {len(data)} != {header_len + size}")
    if len(data) < 30:
        raise SystemExit(f"{asset}: truncated local header")
    (sig, _ver, flags, method, _mt, _md, crc, csize, usize, name_len,
     extra_len) = struct.unpack_from("<IHHHHHIIIHH", data, 0)
    if sig != 0x04034B50:
        raise SystemExit(f"{asset}: bad local file header signature")
    if method != 0:
        raise SystemExit(f"{asset}: member is not STORED (method {method})")
    if flags & 0x0009:
        raise SystemExit(f"{asset}: encrypted or data-descriptor member (flags {flags:#x})")
    if 30 + name_len + extra_len != header_len:
        raise SystemExit(f"{asset}: local header length changed")
    if data[30:30 + name_len] != name:
        raise SystemExit(f"{asset}: member name mismatch {data[30:30 + name_len]!r}")
    expected_crc = int(str(row["member_crc32"]), 16)
    if (crc, csize, usize) != (expected_crc, size, size):
        raise SystemExit(f"{asset}: local header crc/size mismatch {(crc, csize, usize)}")
    payload = data[header_len:]
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise SystemExit(f"{asset}: payload CRC32 {actual_crc:08x} != {expected_crc:08x}")
    if payload[:8] != PNG_SIG or payload[12:16] != b"IHDR":
        raise SystemExit(f"{asset}: payload is not a PNG")
    width, height, depth, color = struct.unpack(">IIBB", payload[16:26])
    if (width, height, depth, color) != (row["width"], row["height"], 16, row["color_type"]):
        raise SystemExit(f"{asset}: IHDR {(width, height, depth, color)} differs from pinned table")
    tmp = out_path.with_suffix(".png.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, out_path)


# --------------------------------------------------------------------------- PNG

def parse_png(data: bytes, label: str) -> tuple[int, int, int, bytes]:
    """Return (width, height, color_type, inflated filtered scanlines)."""
    if data[:8] != PNG_SIG:
        raise ValueError(f"{label}: invalid PNG signature")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    saw_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError(f"{label}: truncated chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError(f"{label}: chunk exceeds file")
        payload = data[offset + 8:offset + 8 + length]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != struct.unpack_from(">I", data, offset + 8 + length)[0]:
            raise ValueError(f"{label}: CRC mismatch in {kind!r}")
        chunks.append((kind, payload))
        offset = end
        if kind == b"IEND":
            saw_iend = True
            break
    if not saw_iend or offset != len(data):
        raise ValueError(f"{label}: missing IEND or trailing data")
    if chunks[0][0] != b"IHDR" or sum(k == b"IHDR" for k, _ in chunks) != 1:
        raise ValueError(f"{label}: bad IHDR placement")
    if any(k == b"PLTE" for k, _ in chunks):
        raise ValueError(f"{label}: unexpected PLTE")
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise ValueError(f"{label}: bad IHDR length")
    width, height, depth, color, comp, filt, interlace = struct.unpack(">IIBBBBB", ihdr)
    if depth != 16 or color not in (2, 6) or comp != 0 or filt != 0 or interlace != 0:
        raise ValueError(f"{label}: unsupported IHDR {(depth, color, comp, filt, interlace)}")
    if not (0 < width <= 1024 and 0 < height <= 1024):
        raise ValueError(f"{label}: unexpected geometry {width}x{height}")
    idat = [i for i, (k, _) in enumerate(chunks) if k == b"IDAT"]
    if not idat or idat != list(range(idat[0], idat[-1] + 1)):
        raise ValueError(f"{label}: missing or non-consecutive IDAT")
    compressed = b"".join(chunks[i][1] for i in idat)
    inflater = zlib.decompressobj()
    filtered = inflater.decompress(compressed) + inflater.flush()
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError(f"{label}: malformed or trailing zlib stream")
    channels = 3 if color == 2 else 4
    row_bytes = width * channels * 2
    if len(filtered) != height * (row_bytes + 1):
        raise ValueError(f"{label}: scanline bytes {len(filtered)} != {height * (row_bytes + 1)}")
    return width, height, color, filtered


def unfilter(filtered: bytes, height: int, row_bytes: int, bpp: int, label: str) -> bytearray:
    out = bytearray(height * row_bytes)
    prior = bytearray(row_bytes)
    stride = row_bytes + 1
    for y in range(height):
        start = y * stride
        ftype = filtered[start]
        row = bytearray(filtered[start + 1:start + stride])
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, row_bytes):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:
            row = bytearray((a + b) & 0xFF for a, b in zip(row, prior))
        elif ftype == 3:
            for i in range(bpp):
                row[i] = (row[i] + (prior[i] >> 1)) & 0xFF
            for i in range(bpp, row_bytes):
                row[i] = (row[i] + ((row[i - bpp] + prior[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(bpp):
                row[i] = (row[i] + prior[i]) & 0xFF  # paeth(0, up, 0) == up
            for i in range(bpp, row_bytes):
                a = row[i - bpp]
                b = prior[i]
                c = prior[i - bpp]
                pa = b - c
                pb = a - c
                pc = pa + pb
                if pa < 0:
                    pa = -pa
                if pb < 0:
                    pb = -pb
                if pc < 0:
                    pc = -pc
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                row[i] = (row[i] + pred) & 0xFF
        else:
            raise ValueError(f"{label}: invalid filter type {ftype} on row {y}")
        out[y * row_bytes:(y + 1) * row_bytes] = row
        prior = row
    return out


def decode_png_rgb(data: bytes, label: str) -> tuple[int, int, int, bytes]:
    """Decode to interleaved RGB uint16 little-endian; alpha must be 65535."""
    width, height, color, filtered = parse_png(data, label)
    channels = 3 if color == 2 else 4
    raw = unfilter(filtered, height, width * channels * 2, channels * 2, label)
    pixels = width * height
    if color == 6:
        alpha_hi = raw[6::8]
        alpha_lo = raw[7::8]
        if alpha_hi.count(0xFF) != pixels or alpha_lo.count(0xFF) != pixels:
            raise ValueError(f"{label}: alpha plane is not constant 65535")
        rgb = bytearray(pixels * 6)
        for k in range(6):
            rgb[k::6] = raw[k::8]
        raw = rgb
    out = bytearray(len(raw))
    out[0::2] = raw[1::2]  # PNG is big-endian; corpus samples are little-endian
    out[1::2] = raw[0::2]
    return width, height, color, bytes(out)


# --------------------------------------------------------------------------- stats

def characterize(payload: bytes, width: int, height: int, label: str) -> dict[str, object]:
    pixels = width * height
    if len(payload) != pixels * 6:
        raise ValueError(f"{label}: payload size mismatch")
    values = array("H")
    values.frombytes(payload)
    if sys.byteorder == "big":
        values.byteswap()
    lo = payload[0::2]
    hi = payload[1::2]
    xor = int.from_bytes(lo, "little") ^ int.from_bytes(hi, "little")
    mult257 = xor.to_bytes(len(lo), "little").count(0) / len(lo)
    channels = []
    for k, name in enumerate("RGB"):
        plane = values[k::3]
        channels.append({
            "channel": name,
            "minimum": min(plane),
            "maximum": max(plane),
            "distinct_values": len(set(plane)),
        })
    blue = values[2::3]
    blue_upper = sum(1 for v in blue if v >= 32768) / pixels
    report = {
        "width": width,
        "height": height,
        "value_count": pixels * 3,
        "sample_size_bytes": pixels * 6,
        "minimum": min(values),
        "maximum": max(values),
        "channels": channels,
        "mult257_fraction": round(mult257, 6),
        "blue_upper_half_fraction": round(blue_upper, 6),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    for ch in channels:
        if int(ch["distinct_values"]) < MIN_DISTINCT_PER_CHANNEL:
            raise ValueError(f"{label}: channel {ch['channel']} has only {ch['distinct_values']} distinct values")
    if mult257 > MAX_MULT257_FRACTION:
        raise ValueError(f"{label}: {mult257:.3f} of values are multiples of 257 (8-bit upscaled)")
    if blue_upper < MIN_BLUE_UPPER_HALF:
        raise ValueError(f"{label}: only {blue_upper:.4f} of blue (Z) values >= 32768; not a tangent-space normal map")
    return report


# --------------------------------------------------------------------------- selftest

def encode_png(width: int, height: int, color: int, samples: list[int], filters: list[int]) -> bytes:
    channels = 3 if color == 2 else 4
    bpp = channels * 2
    row_bytes = width * bpp
    raw = b"".join(struct.pack(">H", v) for v in samples)
    rows = [raw[y * row_bytes:(y + 1) * row_bytes] for y in range(height)]
    out = bytearray()
    prior = bytes(row_bytes)
    for y, row in enumerate(rows):
        ftype = filters[y % len(filters)]
        enc = bytearray(row_bytes)
        for i in range(row_bytes):
            a = row[i - bpp] if i >= bpp else 0
            b = prior[i]
            c = prior[i - bpp] if i >= bpp else 0
            if ftype == 0:
                pred = 0
            elif ftype == 1:
                pred = a
            elif ftype == 2:
                pred = b
            elif ftype == 3:
                pred = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            enc[i] = (row[i] - pred) & 0xFF
        out.append(ftype)
        out.extend(enc)
        prior = row

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    comp = zlib.compress(bytes(out), 9)
    half = len(comp) // 2
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, color, 0, 0, 0))
            + chunk(b"tEXt", b"Comment\x00selftest") + chunk(b"IDAT", comp[:half])
            + chunk(b"IDAT", comp[half:]) + chunk(b"IEND", b""))


def selftest(_args: argparse.Namespace) -> None:
    import zipfile
    rng = random.Random(1234)
    cases = 0
    for color in (2, 6):
        for width, height in ((7, 5), (33, 17), (64, 40)):
            channels = 3 if color == 2 else 4
            samples = []
            for _ in range(width * height):
                px = [rng.randrange(65536), rng.randrange(65536), rng.randrange(32768, 65536)]
                if color == 6:
                    px.append(65535)
                samples.extend(px)
            for filters in ([0], [1], [2], [3], [4], [0, 1, 2, 3, 4], [4, 3, 2, 1, 0]):
                png = encode_png(width, height, color, samples, filters)
                w, h, c, payload = decode_png_rgb(png, "synthetic")
                expected = array("H", [v for i, v in enumerate(samples) if not (channels == 4 and i % 4 == 3)])
                if sys.byteorder == "big":
                    expected.byteswap()
                if (w, h, c) != (width, height, color) or payload != expected.tobytes():
                    raise SystemExit(f"selftest decode mismatch color={color} {width}x{height} filters={filters}")
                cases += 1
    # alpha rejection
    bad = [rng.randrange(65536) for _ in range(4 * 9)]
    try:
        decode_png_rgb(encode_png(3, 3, 6, bad, [0]), "synthetic-alpha")
        raise SystemExit("selftest: non-constant alpha was not rejected")
    except ValueError:
        pass
    # corrupted CRC rejection
    good = bytearray(encode_png(7, 5, 2, [rng.randrange(65536) for _ in range(105)], [4]))
    good[40] ^= 0x01
    try:
        decode_png_rgb(bytes(good), "synthetic-crc")
        raise SystemExit("selftest: corrupted chunk was not rejected")
    except ValueError:
        pass
    # 8-bit-upscaled rejection in characterize
    up = []
    for _ in range(32 * 32):
        up.extend([rng.randrange(256) * 257, rng.randrange(256) * 257, rng.randrange(128, 256) * 257])
    up_payload = array("H", up)
    if sys.byteorder == "big":
        up_payload.byteswap()
    try:
        characterize(up_payload.tobytes(), 32, 32, "synthetic-upscaled")
        raise SystemExit("selftest: x257 upscaled map was not rejected")
    except ValueError:
        pass
    # STORED zip member extraction through the pinned-table path
    samples = [rng.randrange(65536) if i % 3 != 2 else rng.randrange(32768, 65536) for i in range(3 * 20 * 10)]
    png = encode_png(20, 10, 2, samples, [0, 1, 2, 3, 4])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("Synth001_1K-PNG_Color.png", b"x" * 1000)
        zf.writestr(member_name("Synth001"), png)
    blob = buf.getvalue()
    info = zipfile.ZipFile(io.BytesIO(blob)).getinfo(member_name("Synth001"))
    lho = info.header_offset
    name_len, extra_len = struct.unpack_from("<HH", blob, lho + 26)
    data_off = lho + 30 + name_len + extra_len
    row = {"asset_id": "Synth001", "member_lho": lho, "member_data_offset": data_off,
           "member_size": len(png), "member_crc32": f"{zlib.crc32(png) & 0xFFFFFFFF:08x}",
           "width": 20, "height": 10, "color_type": 2}
    tmpdir = Path(os.environ.get("TMPDIR", "/tmp")) / f"{DATASET_ID}_selftest_{os.getpid()}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        rng_file = tmpdir / "member.range"
        rng_file.write_bytes(blob[lho:data_off + len(png)])
        out_png = tmpdir / "member.png"
        extract_member(row, rng_file, out_png)
        if out_png.read_bytes() != png:
            raise SystemExit("selftest: extracted member differs")
        cases += 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(json.dumps({"selftest": "ok", "decode_cases": cases}))


# --------------------------------------------------------------------------- build / verify

def png_path(download_dir: Path, asset: str) -> Path:
    return download_dir / member_name(asset)


def check_source(row: dict[str, object], path: Path) -> bytes:
    if not path.is_file():
        raise SystemExit(f"missing source {path}")
    data = path.read_bytes()
    if len(data) != int(row["member_size"]):
        raise SystemExit(f"{path.name}: size {len(data)} != pinned {row['member_size']}")
    if f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != row["member_crc32"]:
        raise SystemExit(f"{path.name}: CRC32 differs from pinned central directory value")
    return data


def sample_name(asset: str, width: int, height: int) -> str:
    return f"{asset}_NormalGL_h{height}_w{width}_c3_u16le.bin"


def build(args: argparse.Namespace) -> None:
    rows = selected_rows(args.table)
    family = args.samples_dir / SERIES_ID
    if family.exists():
        shutil.rmtree(family)
    family.mkdir(parents=True)
    index_rows = []
    reports = []
    aggregate = hashlib.sha256()
    for n, row in enumerate(rows, 1):
        asset = str(row["asset_id"])
        source = png_path(args.download_dir, asset)
        data = check_source(row, source)
        width, height, color, payload = decode_png_rgb(data, asset)
        if (width, height, color) != (row["width"], row["height"], row["color_type"]):
            raise SystemExit(f"{asset}: decoded geometry differs from pinned table")
        report = characterize(payload, width, height, asset)
        out = family / sample_name(asset, width, height)
        out.write_bytes(payload)
        aggregate.update(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": out.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "asset_id": asset,
            "display_category": row["display_category"],
            "release_date": row["release_date"],
            "source_color_type": color,
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "value_count": report["value_count"],
            "sample_size_bytes": report["sample_size_bytes"],
            "sample_geometry": "2d_tangent_space_normal_map_rgb",
            "sample_shape": [height, width, 3],
            "sample_axes": ["texture_y", "texture_x", "normal_xyz"],
            "natural_record_kind": "material_normal_map",
            "minimum": report["minimum"],
            "maximum": report["maximum"],
            "sha256": report["sha256"],
        })
        reports.append({"asset_id": asset, **report})
        print(f"[{n}/{len(rows)}] {asset} {width}x{height} ct={color} "
              f"mult257={report['mult257_fraction']} blue_hi={report['blue_upper_half_fraction']}", flush=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(index_rows),
        "value_count": sum(int(r["value_count"]) for r in index_rows),
        "total_size_bytes": sum(int(r["sample_size_bytes"]) for r in index_rows),
        "aggregate_payload_sha256": aggregate.hexdigest(),
        "samples": reports,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("dataset_id", "sample_count", "value_count",
                                             "total_size_bytes", "aggregate_payload_sha256")}, indent=2))


def verify(args: argparse.Namespace) -> None:
    rows = selected_rows(args.table)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build.sh first")
    index_rows = [json.loads(l) for l in args.index.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(index_rows) != len(rows):
        raise SystemExit(f"index has {len(index_rows)} rows, expected {len(rows)}")
    expected_paths = set()
    aggregate = hashlib.sha256()
    seen_hashes = set()
    total_values = total_bytes = 0
    for n, (row, entry) in enumerate(zip(rows, index_rows), 1):
        asset = str(row["asset_id"])
        if entry.get("asset_id") != asset or entry.get("dataset_id") != DATASET_ID or entry.get("series_id") != SERIES_ID:
            raise SystemExit(f"{asset}: index identity mismatch")
        for key, want in (("numeric_kind", "uint"), ("bit_width", 16), ("endianness", "little"), ("element_size_bytes", 2)):
            if entry.get(key) != want:
                raise SystemExit(f"{asset}: index {key} = {entry.get(key)!r}")
        width, height = int(row["width"]), int(row["height"])
        out = args.data_root / str(entry["sample_path"])
        if out.name != sample_name(asset, width, height) or not out.is_file():
            raise SystemExit(f"{asset}: missing or misnamed sample {out}")
        expected_paths.add(out.resolve())
        stored = out.read_bytes()
        # Independent re-derivation from the pinned source PNG.
        data = check_source(row, png_path(args.download_dir, asset))
        w, h, color, payload = decode_png_rgb(data, asset)
        if (w, h, color) != (width, height, row["color_type"]) or stored != payload:
            raise SystemExit(f"{asset}: stored sample differs from re-decoded source")
        # Statistics recomputed from the stored file, not trusted from build.
        report = characterize(stored, width, height, asset)
        for key in ("value_count", "sample_size_bytes", "minimum", "maximum", "sha256"):
            if entry.get(key) != report[key]:
                raise SystemExit(f"{asset}: index {key} {entry.get(key)!r} != recomputed {report[key]!r}")
        if entry.get("sample_shape") != [height, width, 3]:
            raise SystemExit(f"{asset}: index sample_shape mismatch")
        if report["minimum"] == report["maximum"]:
            raise SystemExit(f"{asset}: constant sample")
        if report["sha256"] in seen_hashes:
            raise SystemExit(f"{asset}: duplicate sample payload")
        seen_hashes.add(report["sha256"])
        aggregate.update(stored)
        total_values += int(report["value_count"])
        total_bytes += int(report["sample_size_bytes"])
        print(f"[{n}/{len(rows)}] verified {asset}", flush=True)
    actual = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).glob("*/*")}
    if actual != expected_paths:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if (stats.get("sample_count") != len(rows) or stats.get("value_count") != total_values
            or stats.get("total_size_bytes") != total_bytes
            or stats.get("aggregate_payload_sha256") != aggregate.hexdigest()):
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({"dataset_id": DATASET_ID, "verified_samples": len(rows),
                      "verified_values": total_values, "verified_bytes": total_bytes,
                      "aggregate_payload_sha256": aggregate.hexdigest()}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--table", type=Path, required=True)
    p.add_argument("--asset", required=True)
    p.add_argument("--range-file", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check")
    p.add_argument("--table", type=Path, required=True)
    p.add_argument("--asset", required=True)
    p.add_argument("--png", type=Path, required=True)
    p = sub.add_parser("list")
    p.add_argument("--table", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--table", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if name == "build":
            p.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        rows = {str(r["asset_id"]): r for r in selected_rows(args.table)}
        if args.asset not in rows:
            raise SystemExit(f"{args.asset} is not a selected asset")
        extract_member(rows[args.asset], args.range_file, args.out)
    elif args.command == "check":
        rows = {str(r["asset_id"]): r for r in selected_rows(args.table)}
        check_source(rows[args.asset], args.png)
    elif args.command == "list":
        for r in selected_rows(args.table):
            start = int(r["member_lho"])
            end = int(r["member_data_offset"]) + int(r["member_size"]) - 1
            print(f"{r['asset_id']}\t{r['zip_size']}\t{start}\t{end}\t{end - start + 1}")
    elif args.command == "selftest":
        selftest(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
