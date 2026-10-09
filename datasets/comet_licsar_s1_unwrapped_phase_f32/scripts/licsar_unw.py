#!/usr/bin/env python3
"""COMET LiCSAR Sentinel-1 geocoded unwrapped interferograms -> raw float32 rasters.

Pure standard-library Python. Subcommands:

  selftest            round-trip synthetic float32 GeoTIFFs (classic and
                      BigTIFF, RowsPerStrip 1 and >1, partial last strip,
                      Compression 8 + Predictor 3 and uncompressed/no
                      predictor) through the encoder/parser/decoder used here
  check FILE          parse one downloaded *.geo.unw.tif, require the pinned
                      product layout and decode every strip (download.sh)
  build               decode the pinned local rasters into samples + index
  verify              independently re-derive every sample and re-check the
                      index, manifest totals and non-degeneracy rules

Decoding (libtiff fpAcc semantics, Predictor=3 floating-point):
  per strip: zlib inflate -> for each row of width*4 bytes: undo the byte-wise
  horizontal differencing (cumulative sum mod 256 along the whole row), then
  the row holds four byte planes of `width` bytes each, MSB plane first;
  value i in big-endian byte order is (p0[i], p1[i], p2[i], p3[i]). The
  little-endian output therefore takes (p3[i], p2[i], p1[i], p0[i]).

Only local files are read by build/verify; network I/O lives in download.sh.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import shutil
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "comet_licsar_s1_unwrapped_phase_f32"
SERIES_ID = "geo_unw_phase_f32"
NODATA = 0.0
MAX_ZERO_FRACTION = 0.5  # a raster that is mostly no-data is rejected
MIN_DISTINCT_SAMPLED = 1000
PIXEL_DEG = 0.001

# TIFF tag ids
T_WIDTH, T_LENGTH, T_BPS, T_COMPRESSION, T_PHOTOMETRIC = 256, 257, 258, 259, 262
T_STRIP_OFFSETS, T_SPP, T_ROWS_PER_STRIP, T_STRIP_BYTE_COUNTS = 273, 277, 278, 279
T_PLANAR, T_PREDICTOR, T_SAMPLE_FORMAT = 284, 317, 339
T_TILE_WIDTH, T_TILE_OFFSETS = 322, 324
T_PIXEL_SCALE, T_TIEPOINT, T_GEOKEYS, T_GDAL_NODATA = 33550, 33922, 34735, 42113

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
              11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d",
            16: "Q", 17: "q", 18: "Q"}


# --------------------------------------------------------------------------
# TIFF / BigTIFF little-endian parsing
# --------------------------------------------------------------------------
def parse_tiff(buf: bytes, name: str) -> dict:
    """Parse the first IFD of a little-endian classic TIFF or BigTIFF."""
    if len(buf) < 16 or buf[:2] != b"II":
        raise ValueError(f"{name}: not a little-endian TIFF (magic {buf[:4]!r})")
    (version,) = struct.unpack_from("<H", buf, 2)
    if version == 42:
        big = False
        (ifd_off,) = struct.unpack_from("<I", buf, 4)
        cnt_fmt, cnt_size, ent_size, val_size = "<H", 2, 12, 4
    elif version == 43:
        big = True
        bytesize, zero, ifd_off = struct.unpack_from("<HHQ", buf, 4)
        if bytesize != 8 or zero != 0:
            raise ValueError(f"{name}: malformed BigTIFF header")
        cnt_fmt, cnt_size, ent_size, val_size = "<Q", 8, 20, 8
    else:
        raise ValueError(f"{name}: unknown TIFF version {version}")
    if ifd_off < 8 or ifd_off + cnt_size > len(buf):
        raise ValueError(f"{name}: IFD offset {ifd_off} out of range")
    (count,) = struct.unpack_from(cnt_fmt, buf, ifd_off)
    if count == 0 or count > 4096:
        raise ValueError(f"{name}: implausible IFD entry count {count}")
    end = ifd_off + cnt_size + ent_size * count
    if end > len(buf):
        raise ValueError(f"{name}: truncated IFD")
    tags: dict[int, tuple] = {}
    for i in range(count):
        base = ifd_off + cnt_size + ent_size * i
        if big:
            tag, typ, n = struct.unpack_from("<HHQ", buf, base)
            raw_off = base + 12
            (ptr,) = struct.unpack_from("<Q", buf, raw_off)
        else:
            tag, typ, n = struct.unpack_from("<HHI", buf, base)
            raw_off = base + 8
            (ptr,) = struct.unpack_from("<I", buf, raw_off)
        if typ not in TYPE_SIZES:
            raise ValueError(f"{name}: tag {tag} has unknown type {typ}")
        nbytes = TYPE_SIZES[typ] * n
        off = raw_off if nbytes <= val_size else ptr
        if off + nbytes > len(buf):
            raise ValueError(f"{name}: tag {tag} data out of range")
        if typ == 2:
            tags[tag] = (buf[off: off + nbytes].rstrip(b"\x00").decode("ascii", "replace"),)
        elif typ in (5, 10):
            fmt = "<" + ("I" if typ == 5 else "i") * (2 * n)
            v = struct.unpack_from(fmt, buf, off)
            tags[tag] = tuple(v[j] / v[j + 1] if v[j + 1] else float("nan") for j in range(0, 2 * n, 2))
        elif typ in TYPE_FMT:
            tags[tag] = struct.unpack_from("<" + TYPE_FMT[typ] * n, buf, off)
        else:
            tags[tag] = (buf[off: off + nbytes],)
    return {"bigtiff": big, "tags": tags}


def raster_layout(buf: bytes, name: str) -> dict:
    """Validate the float32 single-band stripped layout and return geometry."""
    info = parse_tiff(buf, name)
    t = info["tags"]

    def one(tag: int, default=None):
        if tag not in t:
            if default is None:
                raise ValueError(f"{name}: missing TIFF tag {tag}")
            return default
        return t[tag][0]

    width, height = one(T_WIDTH), one(T_LENGTH)
    if T_TILE_WIDTH in t or T_TILE_OFFSETS in t:
        raise ValueError(f"{name}: tiled TIFF not supported (expected strips)")
    checks = {
        "BitsPerSample": (one(T_BPS), 32),
        "SamplesPerPixel": (one(T_SPP, 1), 1),
        "SampleFormat": (one(T_SAMPLE_FORMAT), 3),
        "PlanarConfiguration": (one(T_PLANAR, 1), 1),
    }
    for label, (got, want) in checks.items():
        if got != want:
            raise ValueError(f"{name}: {label}={got}, expected {want}")
    compression = one(T_COMPRESSION, 1)
    predictor = one(T_PREDICTOR, 1)
    if compression not in (1, 8, 32946):
        raise ValueError(f"{name}: unsupported Compression={compression}")
    if predictor not in (1, 3):
        raise ValueError(f"{name}: unsupported Predictor={predictor}")
    rps = one(T_ROWS_PER_STRIP, height)
    rps = min(rps, height)
    offsets = t[T_STRIP_OFFSETS]
    counts = t[T_STRIP_BYTE_COUNTS]
    nstrips = (height + rps - 1) // rps
    if len(offsets) != nstrips or len(counts) != nstrips:
        raise ValueError(f"{name}: {len(offsets)} strip offsets / {len(counts)} counts, expected {nstrips}")
    for o, c in zip(offsets, counts):
        if o + c > len(buf) or c <= 0:
            raise ValueError(f"{name}: strip [{o}, {o + c}) outside file of {len(buf)} bytes")
    geo = {}
    if T_PIXEL_SCALE in t:
        geo["pixel_scale"] = list(t[T_PIXEL_SCALE][:2])
    if T_TIEPOINT in t:
        geo["tiepoint_lonlat"] = list(t[T_TIEPOINT][3:5])
    nodata = None
    if T_GDAL_NODATA in t:
        nodata = t[T_GDAL_NODATA][0]
    return {
        "bigtiff": info["bigtiff"], "width": width, "height": height,
        "compression": compression, "predictor": predictor,
        "rows_per_strip": rps, "offsets": offsets, "counts": counts,
        "gdal_nodata": nodata, **geo,
    }


def _mask_byte(v: int) -> int:
    return v & 0xFF


def undo_fp_predictor_row(row: bytes, width: int) -> bytes:
    """Predictor=3 row (width*4 bytes) -> little-endian float32 bytes."""
    acc = bytes(map(_mask_byte, itertools.accumulate(row)))
    out = bytearray(4 * width)
    out[0::4] = acc[3 * width: 4 * width]
    out[1::4] = acc[2 * width: 3 * width]
    out[2::4] = acc[width: 2 * width]
    out[3::4] = acc[0:width]
    return bytes(out)


def decode_raster(buf: bytes, name: str, layout: dict | None = None) -> tuple[dict, bytes]:
    """Return (layout, little-endian float32 raster bytes in row-major order)."""
    lay = layout or raster_layout(buf, name)
    width, height, rps = lay["width"], lay["height"], lay["rows_per_strip"]
    row_bytes = 4 * width
    out = bytearray()
    for s, (o, c) in enumerate(zip(lay["offsets"], lay["counts"])):
        rows = min(rps, height - s * rps)
        raw = buf[o: o + c]
        if lay["compression"] in (8, 32946):
            d = zlib.decompressobj()
            data = d.decompress(raw)
            if not d.eof:
                raise ValueError(f"{name}: strip {s} zlib stream truncated")
        else:
            data = raw
        if len(data) != rows * row_bytes:
            raise ValueError(f"{name}: strip {s} decoded {len(data)} bytes, expected {rows * row_bytes}")
        if lay["predictor"] == 3:
            for r in range(rows):
                out += undo_fp_predictor_row(data[r * row_bytes: (r + 1) * row_bytes], width)
        else:
            out += data  # file is little-endian ("II"), float32 already LE
    if len(out) != width * height * 4:
        raise ValueError(f"{name}: decoded {len(out)} bytes, expected {width * height * 4}")
    return lay, bytes(out)


def decode_raster_reference(buf: bytes, name: str, lay: dict) -> bytes:
    """Independent decoder used by verify: explicit byte loop for the
    horizontal accumulation, big-endian float reassembly via struct, and
    explicit little-endian re-serialization (no shared helper with build)."""
    w, h, rps = lay["width"], lay["height"], lay["rows_per_strip"]
    out = bytearray()
    for s, (o, c) in enumerate(zip(lay["offsets"], lay["counts"])):
        rows_in = min(rps, h - s * rps)
        d = zlib.decompress(buf[o:o + c]) if lay["compression"] in (8, 32946) else buf[o:o + c]
        if len(d) != rows_in * 4 * w:
            raise ValueError(f"{name}: strip {s} has {len(d)} bytes, expected {rows_in * 4 * w}")
        for r in range(rows_in):
            rb = bytearray(d[r * 4 * w:(r + 1) * 4 * w])
            if lay["predictor"] == 3:
                acc = 0
                for i in range(len(rb)):
                    acc = (acc + rb[i]) & 0xFF
                    rb[i] = acc
                be = bytearray(4 * w)
                for k in range(4):
                    be[k::4] = rb[k * w:(k + 1) * w]
                vals = struct.unpack(f">{w}I", be)
            else:
                vals = struct.unpack(f"<{w}I", rb)
            out += struct.pack(f"<{w}I", *vals)
    return bytes(out)


# --------------------------------------------------------------------------
# Reference encoder (selftest only), libtiff fpDiff semantics
# --------------------------------------------------------------------------
def fp_predict_row(le_row: bytes, width: int) -> bytes:
    planes = bytearray(4 * width)
    planes[0:width] = le_row[3::4]
    planes[width:2 * width] = le_row[2::4]
    planes[2 * width:3 * width] = le_row[1::4]
    planes[3 * width:4 * width] = le_row[0::4]
    diff = bytearray(len(planes))
    prev = 0
    for i, b in enumerate(planes):
        diff[i] = (b - prev) & 0xFF
        prev = b
    return bytes(diff)


def write_tiff(values_le: bytes, width: int, height: int, rps: int, compression: int,
               predictor: int, bigtiff: bool) -> bytes:
    row_bytes = 4 * width
    strips = []
    for s in range(0, height, rps):
        rows = min(rps, height - s)
        chunk = values_le[s * row_bytes: (s + rows) * row_bytes]
        if predictor == 3:
            chunk = b"".join(fp_predict_row(chunk[r * row_bytes: (r + 1) * row_bytes], width) for r in range(rows))
        if compression == 8:
            chunk = zlib.compress(chunk, 6)
        strips.append(chunk)
    header_size = 16 if bigtiff else 8
    data = bytearray()
    offsets = []
    for st in strips:
        offsets.append(header_size + len(data))
        data += st
        if len(data) % 2:
            data += b"\x00"
    counts = [len(s) for s in strips]
    extra = bytearray()
    ifd_base = header_size + len(data)
    entries = [
        (T_WIDTH, 3, [width]), (T_LENGTH, 3, [height]), (T_BPS, 3, [32]),
        (T_COMPRESSION, 3, [compression]), (T_PHOTOMETRIC, 3, [1]),
        (T_STRIP_OFFSETS, 16 if bigtiff else 4, offsets), (T_SPP, 3, [1]),
        (T_ROWS_PER_STRIP, 3, [rps]), (T_STRIP_BYTE_COUNTS, 16 if bigtiff else 4, counts),
        (T_PLANAR, 3, [1]), (T_PREDICTOR, 3, [predictor]), (T_SAMPLE_FORMAT, 3, [3]),
        (T_PIXEL_SCALE, 12, [PIXEL_DEG, PIXEL_DEG, 0.0]),
        (T_GDAL_NODATA, 2, list(b"0\x00")),
    ]
    entries.sort()
    ent_size = 20 if bigtiff else 12
    val_size = 8 if bigtiff else 4
    cnt_size = 8 if bigtiff else 2
    ifd_len = cnt_size + ent_size * len(entries) + val_size
    extra_base = ifd_base + ifd_len
    ifd = bytearray(struct.pack("<Q" if bigtiff else "<H", len(entries)))
    for tag, typ, vals in entries:
        fmt = "B" if typ == 2 else TYPE_FMT[typ]
        payload = struct.pack("<" + fmt * len(vals), *vals)
        if len(payload) <= val_size:
            field = payload.ljust(val_size, b"\x00")
        else:
            field = struct.pack("<Q" if bigtiff else "<I", extra_base + len(extra))
            extra += payload
            if len(extra) % 2:
                extra += b"\x00"
        if bigtiff:
            ifd += struct.pack("<HHQ", tag, typ, len(vals)) + field
        else:
            ifd += struct.pack("<HHI", tag, typ, len(vals)) + field
    ifd += b"\x00" * val_size
    if bigtiff:
        head = b"II" + struct.pack("<HHHQ", 43, 8, 0, ifd_base)
    else:
        head = b"II" + struct.pack("<HI", 42, ifd_base)
    return bytes(head + data + ifd + extra)


def cmd_selftest(_args) -> None:
    rng = random.Random(20261008)
    cases = 0
    for width, height in ((37, 11), (130, 7), (1, 5)):
        vals = []
        for y in range(height):
            for x in range(width):
                r = rng.random()
                if r < 0.15:
                    vals.append(0.0)
                elif r < 0.2:
                    vals.append(rng.choice([-0.0, 1e-38, -3.4e38, float("inf")]))
                else:
                    vals.append(math.sin(x / 7.0) * 12.0 + y * 0.3 + rng.gauss(0, 0.5))
        le = struct.pack(f"<{len(vals)}f", *vals)
        for rps in (1, 3, height, height + 4):
            for comp, pred in ((8, 3), (1, 3), (8, 1), (1, 1)):
                for big in (False, True):
                    tif = write_tiff(le, width, height, rps, comp, pred, big)
                    lay, out = decode_raster(tif, "synthetic")
                    if out != le:
                        raise SystemExit(f"selftest mismatch w={width} h={height} rps={rps} comp={comp} pred={pred} big={big}")
                    if decode_raster_reference(tif, "synthetic", lay) != le:
                        raise SystemExit(f"selftest reference-decoder mismatch rps={rps} comp={comp} pred={pred} big={big}")
                    if lay["bigtiff"] != big:
                        raise SystemExit("selftest: BigTIFF flag mismatch")
                    cases += 1
    # independent cross-check of the de-interleave direction on a known value
    one = struct.pack("<f", 1.5)  # BE bytes 3F C0 00 00
    planes = bytes([0x3F, 0xC0, 0x00, 0x00])
    diff = bytes([planes[0], (planes[1] - planes[0]) & 255, (planes[2] - planes[1]) & 255, (planes[3] - planes[2]) & 255])
    if undo_fp_predictor_row(diff, 1) != one:
        raise SystemExit("selftest: known-value predictor-3 check failed")
    # truncated zlib must be rejected
    tif = bytearray(write_tiff(struct.pack("<4f", 1, 2, 3, 4), 4, 1, 1, 8, 3, False))
    lay = raster_layout(bytes(tif), "trunc")
    o, c = lay["offsets"][0], lay["counts"][0]
    tif[o + c - 3: o + c] = b"\x00\x00\x00"
    try:
        decode_raster(bytes(tif), "trunc")
    except (ValueError, zlib.error):
        pass
    else:
        raise SystemExit("selftest: corrupted strip was not rejected")
    print(f"selftest ok cases={cases + 2}")


# --------------------------------------------------------------------------
# Sources, stats
# --------------------------------------------------------------------------
def read_sources(path: Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip():
                continue
            rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def raster_stats(le: bytes, width: int, height: int) -> dict:
    n = width * height
    arr = memoryview(le).cast("f")
    zero = 0
    nonfinite = 0
    lo = math.inf
    hi = -math.inf
    s = 0.0
    for v in arr:
        if v == 0.0:
            zero += 1
            continue
        if not math.isfinite(v):
            nonfinite += 1
            continue
        if v < lo:
            lo = v
        if v > hi:
            hi = v
        s += v
    valid = n - zero - nonfinite
    # distinct bit patterns over a deterministic stride sample
    step = max(1, n // 200_000)
    distinct = len(set(memoryview(le).cast("I")[::step]))
    return {
        "zero_count": zero, "zero_fraction": zero / n, "nonfinite_count": nonfinite,
        "valid_count": valid, "min": lo if valid else None, "max": hi if valid else None,
        "mean_valid": s / valid if valid else None, "distinct_bitpatterns_sampled": distinct,
    }


def check_stats(name: str, st: dict) -> None:
    if st["nonfinite_count"]:
        raise ValueError(f"{name}: {st['nonfinite_count']} non-finite values")
    if st["zero_fraction"] > MAX_ZERO_FRACTION:
        raise ValueError(f"{name}: zero/no-data fraction {st['zero_fraction']:.3f} > {MAX_ZERO_FRACTION}")
    if st["valid_count"] == 0 or st["min"] == st["max"]:
        raise ValueError(f"{name}: constant raster")
    if st["distinct_bitpatterns_sampled"] < MIN_DISTINCT_SAMPLED:
        raise ValueError(f"{name}: only {st['distinct_bitpatterns_sampled']} distinct sampled values")
    if not (-2000.0 < st["min"] < st["max"] < 2000.0):
        raise ValueError(f"{name}: implausible unwrapped phase range [{st['min']}, {st['max']}] rad")


def cmd_check(args) -> None:
    path = Path(args.file)
    buf = path.read_bytes()
    lay, le = decode_raster(buf, path.name)
    if lay["bigtiff"]:
        print(f"note: {path.name} is BigTIFF")
    if args.width and (lay["width"], lay["height"]) != (args.width, args.height):
        raise SystemExit(f"{path.name}: raster {lay['width']}x{lay['height']}, expected {args.width}x{args.height}")
    st = raster_stats(le, lay["width"], lay["height"])
    check_stats(path.name, st)
    print(f"check ok {path.name} {lay['width']}x{lay['height']} rps={lay['rows_per_strip']} "
          f"comp={lay['compression']} pred={lay['predictor']} zero_fraction={st['zero_fraction']:.4f} "
          f"range=[{st['min']:.3f},{st['max']:.3f}]")


def stored_f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def paths(args):
    root = Path(args.repo_root)
    data = root / args.data_dir
    return root, data


def cmd_build(args) -> None:
    root, data = paths(args)
    sources = read_sources(Path(args.sources))
    dl = data / "downloads" / DATASET_ID / "rasters"
    out_dir = data / "samples" / DATASET_ID / SERIES_ID
    idx_dir = data / "index" / DATASET_ID
    filt = data / "filtered" / DATASET_ID
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    idx_dir.mkdir(parents=True, exist_ok=True)
    filt.mkdir(parents=True, exist_ok=True)
    rows = []
    total = 0
    for src in sources:
        fn = src["filename"]
        p = dl / fn
        buf = p.read_bytes()
        if len(buf) != int(src["size_bytes"]):
            raise SystemExit(f"{fn}: size {len(buf)} != pinned {src['size_bytes']}")
        lay, le = decode_raster(buf, fn)
        st = raster_stats(le, lay["width"], lay["height"])
        check_stats(fn, st)
        stem = f"{src['frame']}__{src['pair']}"
        sp = out_dir / f"{stem}.f32le"
        sp.write_bytes(le)
        total += len(le)
        row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": str(sp.relative_to(data)),
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "sample_size_bytes": len(le),
            "value_count": lay["width"] * lay["height"],
            "shape": [lay["height"], lay["width"]], "axes": ["latitude_row_north_to_south", "longitude_column_west_to_east"],
            "frame": src["frame"], "pair": src["pair"], "source_file": fn,
            "source_size_bytes": len(buf), "source_sha256": hashlib.sha256(buf).hexdigest(),
            "sample_sha256": hashlib.sha256(le).hexdigest(),
            "rows_per_strip": lay["rows_per_strip"], "compression": lay["compression"],
            "predictor": lay["predictor"], "bigtiff": lay["bigtiff"],
            "tiepoint_lonlat": lay.get("tiepoint_lonlat"), "pixel_scale": lay.get("pixel_scale"),
            "zero_count": st["zero_count"], "zero_fraction": round(st["zero_fraction"], 6),
            "min": stored_f32(st["min"]), "max": stored_f32(st["max"]),
            "mean_valid": st["mean_valid"],
        }
        rows.append(row)
        print(f"sample {stem} {lay['width']}x{lay['height']} bytes={len(le)} zero_fraction={st['zero_fraction']:.4f} "
              f"range=[{st['min']:.3f},{st['max']:.3f}] rad")
    with open(idx_dir / "samples.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {
        "sample_count": len(rows), "total_size_bytes": total,
        "total_values": total // 4,
        "zero_fraction_overall": sum(r["zero_count"] for r in rows) / (total // 4),
        "zero_fraction_max": max(r["zero_fraction"] for r in rows),
        "zero_fraction_min": min(r["zero_fraction"] for r in rows),
    }
    (filt / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"build done samples={len(rows)} bytes={total} summary={json.dumps(summary)}")


def cmd_verify(args) -> None:
    root, data = paths(args)
    sources = read_sources(Path(args.sources))
    manifest = tomllib.loads(Path(args.manifest).read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest must declare exactly one geo_unw_phase_f32 series")
    ser = series[0]
    idx_path = data / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(l) for l in idx_path.read_text().splitlines() if l.strip()]
    if len(rows) != len(sources):
        raise SystemExit(f"index has {len(rows)} rows, sources lists {len(sources)}")
    out_dir = data / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.iterdir())
    if len(on_disk) != len(rows):
        raise SystemExit(f"{len(on_disk)} files in {out_dir}, index has {len(rows)}")
    dl = data / "downloads" / DATASET_ID / "rasters"
    total = 0
    hashes = set()
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                "element_size_bytes", "sample_size_bytes", "value_count"]
    for src, row in zip(sources, rows):
        for k in required:
            if k not in row:
                raise SystemExit(f"index row missing {k}")
        if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
            raise SystemExit("index ids mismatch")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            raise SystemExit("index dtype mismatch")
        if row["source_file"] != src["filename"]:
            raise SystemExit(f"index order mismatch at {src['filename']}")
        sp = data / row["sample_path"]
        sample = sp.read_bytes()
        if len(sample) != row["sample_size_bytes"] or row["value_count"] * 4 != len(sample):
            raise SystemExit(f"{sp}: size mismatch")
        buf = (dl / src["filename"]).read_bytes()
        if len(buf) != int(src["size_bytes"]):
            raise SystemExit(f"{src['filename']}: source size changed")
        if src.get("sha256") not in (None, "", "-") and hashlib.sha256(buf).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['filename']}: source sha256 mismatch")
        lay = raster_layout(buf, src["filename"])
        w = lay["width"]
        rederived = decode_raster_reference(buf, src["filename"], lay)
        if rederived != sample:
            raise SystemExit(f"{sp}: sample bytes differ from independent re-derivation")
        if [lay["height"], lay["width"]] != row["shape"]:
            raise SystemExit(f"{sp}: shape mismatch")
        st = raster_stats(sample, w, lay["height"])
        check_stats(sp.name, st)
        if st["zero_count"] != row["zero_count"]:
            raise SystemExit(f"{sp}: zero count mismatch")
        if stored_f32(st["min"]) != row["min"] or stored_f32(st["max"]) != row["max"]:
            raise SystemExit(f"{sp}: min/max mismatch")
        h = hashlib.sha256(sample).hexdigest()
        if h != row["sample_sha256"] or h in hashes:
            raise SystemExit(f"{sp}: hash mismatch or duplicate sample")
        hashes.add(h)
        total += len(sample)
        print(f"verified {sp.name} zero_fraction={st['zero_fraction']:.4f}")
    if ser["sample_count"] != len(rows):
        raise SystemExit(f"manifest sample_count {ser['sample_count']} != {len(rows)}")
    if ser["total_size_bytes"] != total:
        raise SystemExit(f"manifest total_size_bytes {ser['total_size_bytes']} != {total}")
    if total > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    sizes = sorted(r["value_count"] for r in rows)
    if sizes[len(sizes) // 2] < 1000:
        raise SystemExit("median sample below floor")
    print(f"verify ok samples={len(rows)} bytes={total}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    c = sub.add_parser("check")
    c.add_argument("file")
    c.add_argument("--width", type=int, default=0)
    c.add_argument("--height", type=int, default=0)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", required=True)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--sources", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = ap.parse_args()
    {"selftest": cmd_selftest, "check": cmd_check, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
