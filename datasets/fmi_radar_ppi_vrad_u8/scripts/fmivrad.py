#!/usr/bin/env python3
"""FMI fikor ppi_0.5_vrad_qc GeoTIFF scans -> raw uint8 radial-velocity rasters.

Pure standard-library Python. Subcommands:

  selftest              round-trip synthetic TIFF-LZW streams and a synthetic
                        tiled product GeoTIFF through the parser/decoder, and
                        check that layout/metadata drift is rejected
  check-header FILE KEY [--header-only]
                        validate the classic-TIFF IFD of one object against the
                        pinned product layout and GDAL metadata (discover.sh
                        with --header-only on a 4 KiB range; download.sh on the
                        full file, which also decodes every tile)
  rank / select         discovery helpers used only by discover.sh
  build                 decode pinned local scans into samples + index
  verify                independently re-derive every sample and re-check the
                        index, manifest totals and the missing-value and
                        non-degeneracy rules

Only local files are read by build/verify; network I/O lives in download.sh
and discover.sh.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "fmi_radar_ppi_vrad_u8"
SERIES_ID = "fikor_ppi_0p5_vrad_qc_u8"
SITE = "fikor"
PRODUCT_SUFFIX = "_fikor_ppi_0.5_vrad_qc.tif"
WIDTH = 2003
HEIGHT = 2003
TILE = 512
TILES_ACROSS = (WIDTH + TILE - 1) // TILE  # 4
TILES_DOWN = (HEIGHT + TILE - 1) // TILE  # 4
TILE_COUNT = TILES_ACROSS * TILES_DOWN  # 16
TILE_BYTES = TILE * TILE  # GDAL writes full (padded) edge tiles
VALUES_PER_SCAN = WIDTH * HEIGHT  # 4,012,009

NODATA_CODE = 255  # GDAL_NODATA: outside the radar's coverage disc
UNDETECT_CODE = 0  # inside coverage, no echo detected (ODIM 'undetect' convention)
VEL_CODE_MIN = 112  # 0.5*112 - 64 = -8.0 m/s
VEL_CODE_MAX = 143  # 0.5*143 - 64 = +7.5 m/s  (32 codes = the folded Nyquist interval)
ALLOWED_CODES = bytes([UNDETECT_CODE, NODATA_CODE] + list(range(VEL_CODE_MIN, VEL_CODE_MAX + 1)))

SOFTWARE = "Rack_fmi.fi 10.7"
DESCRIPTION = "COMP:VRADH:PPI:elangles(0.5)"
GDAL_ITEMS = {
    "IMAGETYPE": "Weather Radar,fikor",
    "TITLE": "PPI:",
    "UNITS": "VRADH",
    "OFFSET": "-64",
    "SCALE": "0.5",
}
GDAL_NODATA_TEXT = "255"
PIXEL_SCALE = (250.0, 250.0, 0.0)
TIEPOINT = (0.0, 0.0, 0.0, -48000.0, 6928250.0, 0.0)
EPSG_PROJECTED = 3067  # ETRS89 / TM35FIN(E,N)

MIN_ECHO_FRACTION = 0.05  # velocity pixels / all pixels; below this a scan is near-empty
NODATA_FRACTION_RANGE = (0.20, 0.30)  # the out-of-coverage corners are ~21.6% of the square
MIN_DISTINCT_VEL_CODES = 16
MIN_DAY_GAP = 2  # selected scans are at least two calendar days apart

EXPECTED_SCANS = 75
EXPECTED_SOURCE_BYTES = 31_677_353  # sum of pinned object sizes in sources.tsv

SOURCES_HEADER = ["scan_time", "key", "size_bytes", "md5", "last_modified", "version_id", "software", "url"]

# TIFF tag ids
T_WIDTH, T_LENGTH, T_BPS, T_COMPRESSION, T_PHOTOMETRIC = 256, 257, 258, 259, 262
T_DESCRIPTION, T_STRIP_OFFSETS, T_SPP, T_STRIP_BYTE_COUNTS = 270, 273, 277, 279
T_PLANAR, T_SOFTWARE, T_DATETIME, T_PREDICTOR = 284, 305, 306, 317
T_TILE_WIDTH, T_TILE_LENGTH, T_TILE_OFFSETS, T_TILE_BYTE_COUNTS, T_SAMPLE_FORMAT = 322, 323, 324, 325, 339
T_PIXEL_SCALE, T_TIEPOINT, T_GEOKEYS, T_GEOASCII = 33550, 33922, 34735, 34737
T_GDAL_METADATA, T_GDAL_NODATA = 42112, 42113

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


# --------------------------------------------------------------------------
# TIFF-LZW (Compression=5): MSB-first codes, 256=Clear, 257=EOI, first free
# code 258, 9..12-bit codes with "early change" (the code width grows when the
# next free code reaches 2**width - 1). Adapted from the accepted recipe
# earthbigdata_s1_global_coherence_vv_coh12_u8 (scripts/s1coh.py).
# --------------------------------------------------------------------------
_BASE_TABLE = [bytes([i]) for i in range(256)] + [b"", b""]


def lzw_decode(data: bytes, expected_len: int) -> bytes:
    """Decode one TIFF-LZW segment. Requires an EOI code and exact output size."""
    table = list(_BASE_TABLE)
    out = bytearray()
    n = len(data)
    pos = 0
    acc = 0
    nbits = 0
    width = 9
    limit = 511
    prev = b""
    saw_eoi = False
    while True:
        while nbits < width:
            if pos >= n:
                break
            acc = (acc << 8) | data[pos]
            pos += 1
            nbits += 8
        if nbits < width:
            break  # ran out of input without EOI
        nbits -= width
        code = acc >> nbits
        acc &= (1 << nbits) - 1
        if code == 256:
            table = list(_BASE_TABLE)
            width = 9
            limit = 511
            prev = b""
            continue
        if code == 257:
            saw_eoi = True
            break
        size = len(table)
        if not prev:
            if code >= 256:
                raise ValueError(f"LZW: first code after clear is {code}")
            entry = table[code]
        elif code < size:
            entry = table[code]
            if size < 4096:
                table.append(prev + entry[:1])
        elif code == size and size < 4096:
            entry = prev + prev[:1]
            table.append(entry)
        else:
            raise ValueError(f"LZW: invalid code {code} with table size {size}")
        out += entry
        prev = entry
        if len(table) >= limit and width < 12:
            width += 1
            limit = (1 << width) - 1
        if len(out) > expected_len:
            raise ValueError(f"LZW: output exceeds expected {expected_len} bytes")
    if not saw_eoi:
        raise ValueError("LZW: segment ended without EOI code")
    if len(out) != expected_len:
        raise ValueError(f"LZW: decoded {len(out)} bytes, expected {expected_len}")
    if pos < n - 1:
        raise ValueError(f"LZW: {n - pos} unused bytes after EOI")
    return bytes(out)


def lzw_encode(data: bytes, clear_every: int | None = None) -> bytes:
    """Reference TIFF-LZW encoder (early change), used only by selftest."""
    out = bytearray()
    acc = 0
    nbits = 0

    def emit(code: int, width: int) -> None:
        nonlocal acc, nbits
        acc = (acc << width) | code
        nbits += width
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
        acc &= (1 << nbits) - 1

    def reset() -> tuple[dict, int, int]:
        return {bytes([i]): i for i in range(256)}, 258, 9

    table, next_code, width = reset()
    emit(256, width)
    if data:
        w = data[0:1]
        emitted = 0
        for byte in data[1:]:
            wc = w + bytes([byte])
            if wc in table:
                w = wc
                continue
            emit(table[w], width)
            emitted += 1
            table[wc] = next_code
            next_code += 1
            if next_code >= (1 << width) and width < 12:
                width += 1
            w = bytes([byte])
            if next_code >= 4094 or (clear_every and emitted % clear_every == 0):
                emit(256, width)
                table, next_code, width = reset()
        emit(table[w], width)
        next_code += 1
        if next_code >= (1 << width) and width < 12:
            width += 1
    emit(257, width)
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    return bytes(out)


# --------------------------------------------------------------------------
# Classic little-endian TIFF parsing and product layout checks
# --------------------------------------------------------------------------
def parse_tiff(buf: bytes, name: str) -> dict:
    if len(buf) < 8 or buf[:4] != b"II*\x00":
        raise ValueError(f"{name}: not a classic little-endian TIFF (magic {buf[:4]!r})")
    (ifd_off,) = struct.unpack_from("<I", buf, 4)
    if ifd_off < 8 or ifd_off + 2 > len(buf):
        raise ValueError(f"{name}: IFD offset {ifd_off} out of range")
    (count,) = struct.unpack_from("<H", buf, ifd_off)
    end = ifd_off + 2 + 12 * count
    if end + 4 > len(buf):
        raise ValueError(f"{name}: truncated IFD")
    tags: dict[int, tuple] = {}
    for i in range(count):
        tag, typ, n, raw = struct.unpack_from("<HHII", buf, ifd_off + 2 + 12 * i)
        if typ not in TYPE_SIZES:
            raise ValueError(f"{name}: tag {tag} has unknown type {typ}")
        nbytes = TYPE_SIZES[typ] * n
        off = ifd_off + 2 + 12 * i + 8 if nbytes <= 4 else raw
        if off + nbytes > len(buf):
            raise ValueError(f"{name}: tag {tag} data out of range")
        if typ == 2:
            tags[tag] = (buf[off : off + nbytes].rstrip(b"\x00").decode("ascii", "replace"),)
        elif typ in (5, 10):
            fmt = "<" + ("II" if typ == 5 else "ii") * n
            vals = struct.unpack_from(fmt, buf, off)
            tags[tag] = tuple(vals[j] / vals[j + 1] if vals[j + 1] else 0.0 for j in range(0, len(vals), 2))
        elif typ == 7:
            tags[tag] = tuple(buf[off : off + nbytes])
        else:
            tags[tag] = struct.unpack_from("<" + TYPE_FMT[typ] * n, buf, off)
    (next_ifd,) = struct.unpack_from("<I", buf, end)
    return {"tags": tags, "next_ifd": next_ifd}


def parse_gdal_metadata(text: str) -> dict[str, str]:
    items = re.findall(r'<Item name="([^"]+)"[^>]*>([^<]*)</Item>', text)
    return {k: v for k, v in items}


def scan_time_of(key: str) -> str:
    base = key.rsplit("/", 1)[-1]
    m = re.fullmatch(r"(\d{12})" + re.escape(PRODUCT_SUFFIX), base)
    if not m:
        raise ValueError(f"unexpected object name {base!r}")
    stamp = m.group(1)
    parts = key.split("/")
    if len(parts) != 5 or parts[0] + parts[1] + parts[2] != stamp[:8] or parts[3] != SITE:
        raise ValueError(f"object key {key!r} does not match its date prefix / site")
    return stamp


def check_layout(buf: bytes, key: str, name: str, header_only: bool = False) -> dict:
    """Validate the pinned product layout and metadata; return tile offsets/counts."""
    info = parse_tiff(buf, name)
    tags = info["tags"]

    def one(tag: int, label: str):
        if tag not in tags:
            raise ValueError(f"{name}: missing {label} tag {tag}")
        vals = tags[tag]
        if len(vals) != 1:
            raise ValueError(f"{name}: {label} has {len(vals)} values")
        return vals[0]

    expect = [
        (T_WIDTH, "ImageWidth", WIDTH),
        (T_LENGTH, "ImageLength", HEIGHT),
        (T_BPS, "BitsPerSample", 8),
        (T_COMPRESSION, "Compression", 5),
        (T_PHOTOMETRIC, "Photometric", 1),
        (T_SPP, "SamplesPerPixel", 1),
        (T_PLANAR, "PlanarConfiguration", 1),
        (T_PREDICTOR, "Predictor", 1),
        (T_SAMPLE_FORMAT, "SampleFormat", 1),
        (T_TILE_WIDTH, "TileWidth", TILE),
        (T_TILE_LENGTH, "TileLength", TILE),
        (T_DESCRIPTION, "ImageDescription", DESCRIPTION),
        (T_SOFTWARE, "Software", SOFTWARE),
        (T_GDAL_NODATA, "GDAL_NODATA", GDAL_NODATA_TEXT),
    ]
    for tag, label, want in expect:
        got = one(tag, label)
        if isinstance(got, str):
            got = got.strip()
        if got != want:
            raise ValueError(f"{name}: {label}={got!r}, expected {want!r}")
    if T_STRIP_OFFSETS in tags or T_STRIP_BYTE_COUNTS in tags:
        raise ValueError(f"{name}: strip layout tags present; expected the pinned tiled layout")
    if info["next_ifd"] != 0:
        raise ValueError(f"{name}: extra IFD (overview/mask) at {info['next_ifd']}")
    stamp = scan_time_of(key)
    want_dt = f"{stamp[0:4]}:{stamp[4:6]}:{stamp[6:8]} {stamp[8:10]}:{stamp[10:12]}:00"
    if one(T_DATETIME, "DateTime").strip() != want_dt:
        raise ValueError(f"{name}: DateTime {one(T_DATETIME, 'DateTime')!r} != {want_dt!r} from object key")
    gdal = parse_gdal_metadata(one(T_GDAL_METADATA, "GDAL_METADATA"))
    if gdal != GDAL_ITEMS:
        raise ValueError(f"{name}: GDAL metadata {gdal} differs from pinned {GDAL_ITEMS}")
    scale = tags.get(T_PIXEL_SCALE)
    tie = tags.get(T_TIEPOINT)
    if scale != PIXEL_SCALE or tie != TIEPOINT:
        raise ValueError(f"{name}: georeference scale={scale} tiepoint={tie} differs from pinned grid")
    geokeys = tags.get(T_GEOKEYS, ())
    keyset = {geokeys[i]: geokeys[i + 3] for i in range(4, len(geokeys) - 3, 4)}
    if keyset.get(3072) != EPSG_PROJECTED:
        raise ValueError(f"{name}: ProjectedCSTypeGeoKey={keyset.get(3072)}, expected EPSG:{EPSG_PROJECTED}")
    offsets = tags.get(T_TILE_OFFSETS, ())
    counts = tags.get(T_TILE_BYTE_COUNTS, ())
    if len(offsets) != TILE_COUNT or len(counts) != TILE_COUNT:
        raise ValueError(f"{name}: {len(offsets)} tile offsets / {len(counts)} byte counts, expected {TILE_COUNT}")
    if not header_only:
        for i, (off, cnt) in enumerate(zip(offsets, counts)):
            if cnt <= 0 or off < 8 or off + cnt > len(buf):
                raise ValueError(f"{name}: tile {i} [{off}, +{cnt}) outside file of {len(buf)} bytes")
    return {"offsets": offsets, "counts": counts, "software": one(T_SOFTWARE, "Software").strip(), "scan_time": stamp}


def decode_scan(buf: bytes, key: str, name: str) -> bytes:
    layout = check_layout(buf, key, name)
    img = bytearray(VALUES_PER_SCAN)
    for t, (off, cnt) in enumerate(zip(layout["offsets"], layout["counts"])):
        try:
            tile = lzw_decode(buf[off : off + cnt], TILE_BYTES)
        except ValueError as exc:
            raise ValueError(f"{name}: tile {t}: {exc}") from None
        ty, tx = divmod(t, TILES_ACROSS)
        x0 = tx * TILE
        w = min(TILE, WIDTH - x0)
        for r in range(TILE):
            y = ty * TILE + r
            if y >= HEIGHT:
                break
            img[y * WIDTH + x0 : y * WIDTH + x0 + w] = tile[r * TILE : r * TILE + w]
    return bytes(img)


def raster_stats(raster: bytes) -> dict:
    unexpected = raster.translate(None, ALLOWED_CODES)
    hist = {v: raster.count(v) for v in ALLOWED_CODES}
    vel = [v for v in range(VEL_CODE_MIN, VEL_CODE_MAX + 1) if hist[v]]
    echo = sum(hist[v] for v in range(VEL_CODE_MIN, VEL_CODE_MAX + 1))
    return {
        "unexpected_count": len(unexpected),
        "unexpected_examples": sorted(set(unexpected[:1000])),
        "hist": hist,
        "nodata_count": hist[NODATA_CODE],
        "undetect_count": hist[UNDETECT_CODE],
        "echo_count": echo,
        "vel_code_min": min(vel) if vel else None,
        "vel_code_max": max(vel) if vel else None,
        "distinct_vel_codes": len(vel),
        "min": min(v for v in ALLOWED_CODES if hist[v]),
        "max": max(v for v in ALLOWED_CODES if hist[v]),
    }


def check_semantics(stats: dict, raster: bytes, name: str) -> None:
    if stats["unexpected_count"]:
        raise ValueError(
            f"{name}: {stats['unexpected_count']} pixels outside {{0, 112..143, 255}} "
            f"(e.g. {stats['unexpected_examples'][:10]}); Nyquist interval or coding drifted"
        )
    frac_nd = stats["nodata_count"] / VALUES_PER_SCAN
    if not (NODATA_FRACTION_RANGE[0] <= frac_nd <= NODATA_FRACTION_RANGE[1]):
        raise ValueError(f"{name}: NoData(255) fraction {frac_nd:.4f} outside {NODATA_FRACTION_RANGE}")
    frac_echo = stats["echo_count"] / VALUES_PER_SCAN
    if frac_echo < MIN_ECHO_FRACTION:
        raise ValueError(f"{name}: near-empty scan, echo fraction {frac_echo:.4f} < {MIN_ECHO_FRACTION}")
    if stats["distinct_vel_codes"] < MIN_DISTINCT_VEL_CODES:
        raise ValueError(f"{name}: only {stats['distinct_vel_codes']} distinct velocity codes")
    rows_distinct = len({raster[r * WIDTH : (r + 1) * WIDTH] for r in range(200, HEIGHT - 200, 100)})
    if rows_distinct < 5:
        raise ValueError(f"{name}: sampled raster rows are near-identical ({rows_distinct} distinct)")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != SOURCES_HEADER:
        raise ValueError(f"unexpected sources.tsv header {header}")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        row["size_bytes"] = int(row["size_bytes"])
        if scan_time_of(row["key"]) != row["scan_time"] or row["software"] != SOFTWARE:
            raise ValueError(f"sources.tsv row inconsistent: {row['key']}")
        if not re.fullmatch(r"[0-9a-f]{32}", row["md5"]):
            raise ValueError(f"sources.tsv row has non-MD5 ETag: {row['key']}")
        rows.append(row)
    times = [r["scan_time"] for r in rows]
    if len(rows) != EXPECTED_SCANS or len(set(times)) != len(times):
        raise ValueError(f"sources.tsv has {len(rows)} rows ({len(set(times))} unique), expected {EXPECTED_SCANS}")
    if times != sorted(times):
        raise ValueError("sources.tsv is not sorted by scan time")
    days = [day_number(t) for t in times]
    if any(b - a < MIN_DAY_GAP for a, b in zip(days, days[1:])):
        raise ValueError(f"sources.tsv has scans fewer than {MIN_DAY_GAP} calendar days apart")
    if sum(r["size_bytes"] for r in rows) != EXPECTED_SOURCE_BYTES:
        raise ValueError("sources.tsv byte total changed")
    return rows


def file_digests(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def local_scan_path(download_dir: Path, row: dict) -> Path:
    return download_dir / "scans" / row["key"].rsplit("/", 1)[-1]


def load_source(row: dict, download_dir: Path) -> tuple[bytes, str]:
    path = local_scan_path(download_dir, row)
    if not path.is_file():
        raise FileNotFoundError(f"missing local scan {path}")
    if path.stat().st_size != row["size_bytes"]:
        raise ValueError(f"{path.name}: size {path.stat().st_size} != pinned {row['size_bytes']}")
    md5, sha = file_digests(path)
    if md5 != row["md5"]:
        raise ValueError(f"{path.name}: md5 {md5} != pinned ETag {row['md5']}")
    return path.read_bytes(), sha


def manifest_series(recipe_dir: Path) -> dict:
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    for series in manifest.get("series", []):
        if series.get("id") == SERIES_ID:
            return series
    raise ValueError(f"manifest lacks series {SERIES_ID}")


def data_root(args: argparse.Namespace) -> Path:
    d = Path(args.data_dir)
    return d if d.is_absolute() else Path(args.repo_root) / d


# --------------------------------------------------------------------------
# discovery helpers (discover.sh only)
# --------------------------------------------------------------------------
def cmd_rank(args: argparse.Namespace) -> int:
    lines = Path(args.inventory).read_text(encoding="utf-8").splitlines()
    best: dict[str, tuple] = {}
    for line in lines[1:]:
        key, status, size, etag, lm, vid = (line.split("\t") + [""] * 6)[:6]
        if status != "200" or not size.isdigit() or not re.fullmatch(r"[0-9a-f]{32}", etag) or not vid:
            continue
        stamp = scan_time_of(key)
        day = stamp[:8]
        cand = (int(size), stamp, key, etag, lm, vid)
        cur = best.get(day)
        # largest file of the day; ties -> earliest hour
        if cur is None or cand[0] > cur[0] or (cand[0] == cur[0] and cand[1] < cur[1]):
            best[day] = cand
    months: dict[str, list] = {}
    for day, cand in best.items():
        if cand[0] >= args.min_size:
            months.setdefault(day[:6], []).append(cand)
    print("month\trank\tkey\tsize_bytes\tetag\tlast_modified\tversion_id")
    for month in sorted(months):
        ranked = sorted(months[month], key=lambda c: (-c[0], c[1]))[: args.depth]
        for i, (size, stamp, key, etag, lm, vid) in enumerate(ranked, 1):
            print(f"{month}\t{i}\t{key}\t{size}\t{etag}\t{lm}\t{vid}")
    return 0


def day_number(stamp: str) -> int:
    return datetime.date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8])).toordinal()


def cmd_select(args: argparse.Namespace) -> int:
    rows = [line.split("\t") for line in Path(args.checked).read_text(encoding="utf-8").splitlines() if line.strip()]
    chosen = []
    chosen_days: list[int] = []
    per: dict[str, int] = {}
    for month, rank, key, size, etag, lm, vid, status, software in sorted(rows, key=lambda r: (r[0], int(r[1]))):
        if status != "ok" or per.get(month, 0) >= args.per_month:
            continue
        day = day_number(scan_time_of(key))
        if any(abs(day - d) < MIN_DAY_GAP for d in chosen_days):
            continue  # same or adjacent day as an already chosen scan: likely the same weather system
        chosen_days.append(day)
        per[month] = per.get(month, 0) + 1
        url = f"{args.base}/{key}?versionId={vid}"
        chosen.append([scan_time_of(key), key, size, etag, lm, vid, software, url])
    for month in sorted({r[0] for r in rows}):
        if per.get(month, 0) < args.per_month:
            print(f"warning: month {month} has only {per.get(month, 0)} passing scans", file=sys.stderr)
    print("\t".join(SOURCES_HEADER))
    for row in sorted(chosen):
        print("\t".join(row))
    return 0


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
def cmd_check_header(args: argparse.Namespace) -> int:
    path = Path(args.file)
    buf = path.read_bytes()
    layout = check_layout(buf, args.key, path.name, header_only=args.header_only)
    if not args.header_only:
        # full payload check (download.sh): decode every tile, then apply the
        # same code-set, NoData-geometry and near-empty rules as build/verify
        raster = decode_scan(buf, args.key, path.name)
        check_semantics(raster_stats(raster), raster, path.name)
    print(layout["software"])
    return 0


def index_row(data: Path, out: Path, src: dict, stats: dict, sample_sha: str, source_sha: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": str(out.relative_to(data)),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": VALUES_PER_SCAN,
        "value_count": VALUES_PER_SCAN,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["northing_row_north_to_south", "easting_col_west_to_east"],
        "scan_time_utc": src["scan_time"],
        "site": SITE,
        "velocity_scale_m_s": 0.5,
        "velocity_offset_m_s": -64.0,
        "nodata_value": NODATA_CODE,
        "undetect_value": UNDETECT_CODE,
        "nodata_count": stats["nodata_count"],
        "undetect_count": stats["undetect_count"],
        "echo_count": stats["echo_count"],
        "min": stats["min"],
        "max": stats["max"],
        "velocity_code_min": stats["vel_code_min"],
        "velocity_code_max": stats["vel_code_max"],
        "distinct_velocity_codes": stats["distinct_vel_codes"],
        "sample_sha256": sample_sha,
        "source_key": src["key"],
        "source_url": src["url"],
        "source_version_id": src["version_id"],
        "source_size_bytes": src["size_bytes"],
        "source_md5": src["md5"],
        "source_sha256": source_sha,
        "source_software": src["software"],
    }


def cmd_build(args: argparse.Namespace) -> int:
    data = data_root(args)
    recipe_dir = Path(args.recipe_dir)
    download_dir = data / "downloads" / DATASET_ID
    sample_dir = data / "samples" / DATASET_ID / SERIES_ID
    index_dir = data / "index" / DATASET_ID
    filtered_dir = data / "filtered" / DATASET_ID
    sources = read_sources(recipe_dir / "sources.tsv")

    for d in (sample_dir, index_dir, filtered_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    rows = []
    per_scan = []
    total_hist = {v: 0 for v in ALLOWED_CODES}
    seen_hashes: dict[str, str] = {}
    for n, src in enumerate(sources, 1):
        buf, source_sha = load_source(src, download_dir)
        name = src["key"].rsplit("/", 1)[-1]
        raster = decode_scan(buf, src["key"], name)
        stats = raster_stats(raster)
        check_semantics(stats, raster, name)
        sample_sha = hashlib.sha256(raster).hexdigest()
        if sample_sha in seen_hashes:
            raise ValueError(f"{name}: decoded raster duplicates {seen_hashes[sample_sha]}")
        seen_hashes[sample_sha] = name
        out = sample_dir / f"{src['scan_time']}.bin"
        tmp = out.with_suffix(".bin.tmp")
        tmp.write_bytes(raster)
        os.replace(tmp, out)
        for v in ALLOWED_CODES:
            total_hist[v] += stats["hist"][v]
        rows.append(index_row(data, out, src, stats, sample_sha, source_sha))
        per_scan.append(
            {
                "scan_time": src["scan_time"],
                "source_bytes": src["size_bytes"],
                "echo_fraction": round(stats["echo_count"] / VALUES_PER_SCAN, 4),
                "undetect_fraction": round(stats["undetect_count"] / VALUES_PER_SCAN, 4),
                "nodata_fraction": round(stats["nodata_count"] / VALUES_PER_SCAN, 4),
                "distinct_velocity_codes": stats["distinct_vel_codes"],
            }
        )
        if n % 10 == 0 or n == len(sources):
            print(
                f"decoded {n}/{len(sources)} scan={src['scan_time']} echo={stats['echo_count'] / VALUES_PER_SCAN:.3f} "
                f"undetect={stats['undetect_count'] / VALUES_PER_SCAN:.3f} nodata={stats['nodata_count'] / VALUES_PER_SCAN:.3f}",
                flush=True,
            )

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    agg = hashlib.sha256()
    for row in rows:
        agg.update(bytes.fromhex(row["sample_sha256"]))
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(rows),
        "total_values": total_bytes,
        "total_bytes": total_bytes,
        "source_bytes": sum(r["source_size_bytes"] for r in rows),
        "echo_fraction": round(sum(total_hist[v] for v in range(VEL_CODE_MIN, VEL_CODE_MAX + 1)) / total_bytes, 6),
        "undetect_fraction": round(total_hist[UNDETECT_CODE] / total_bytes, 6),
        "nodata_fraction": round(total_hist[NODATA_CODE] / total_bytes, 6),
        "code_histogram": {str(v): c for v, c in sorted(total_hist.items()) if c},
        "aggregate_sample_sha256_of_sha256s": agg.hexdigest(),
        "scans": per_scan,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")

    series = manifest_series(recipe_dir)
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        raise ValueError(
            f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    print(
        f"build_ok samples={len(rows)} bytes={total_bytes} echo_fraction={summary['echo_fraction']} "
        f"undetect_fraction={summary['undetect_fraction']} nodata_fraction={summary['nodata_fraction']} aggregate={agg.hexdigest()}"
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    data = data_root(args)
    recipe_dir = Path(args.recipe_dir)
    download_dir = data / "downloads" / DATASET_ID
    sample_dir = data / "samples" / DATASET_ID / SERIES_ID
    index_path = data / "index" / DATASET_ID / "samples.jsonl"
    sources = {r["scan_time"]: r for r in read_sources(recipe_dir / "sources.tsv")}
    series = manifest_series(recipe_dir)

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(sources):
        raise ValueError(f"index has {len(rows)} rows, expected {len(sources)}")
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(f"{t}.bin" for t in sources):
        raise ValueError("sample directory contents differ from the pinned scan list")

    seen = set()
    seen_hashes = set()
    total_bytes = 0
    global_hist = {v: 0 for v in ALLOWED_CODES}
    for n, row in enumerate(rows, 1):
        stamp = row.get("scan_time_utc")
        if stamp not in sources or stamp in seen:
            raise ValueError(f"index row {n}: unexpected or duplicate scan {stamp!r}")
        seen.add(stamp)
        src = sources[stamp]
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": VALUES_PER_SCAN,
            "value_count": VALUES_PER_SCAN,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{stamp}.bin",
            "nodata_value": NODATA_CODE,
            "undetect_value": UNDETECT_CODE,
            "source_key": src["key"],
            "source_md5": src["md5"],
            "source_version_id": src["version_id"],
        }
        for key, want in fixed.items():
            if row.get(key) != want:
                raise ValueError(f"index row {n} ({stamp}): {key}={row.get(key)!r}, expected {want!r}")
        sample = (data / row["sample_path"]).read_bytes()
        if len(sample) != VALUES_PER_SCAN:
            raise ValueError(f"{stamp}: sample has {len(sample)} bytes")
        buf, source_sha = load_source(src, download_dir)
        if row.get("source_sha256") != source_sha:
            raise ValueError(f"{stamp}: source digest differs from index")
        derived = decode_scan(buf, src["key"], src["key"].rsplit("/", 1)[-1])
        if derived != sample:
            raise ValueError(f"{stamp}: sample bytes differ from re-decoded source raster")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != row.get("sample_sha256") or sha in seen_hashes:
            raise ValueError(f"{stamp}: sample hash mismatch or duplicate raster")
        seen_hashes.add(sha)
        stats = raster_stats(sample)
        check_semantics(stats, sample, stamp)
        for key, skey in (
            ("nodata_count", "nodata_count"),
            ("undetect_count", "undetect_count"),
            ("echo_count", "echo_count"),
            ("min", "min"),
            ("max", "max"),
            ("velocity_code_min", "vel_code_min"),
            ("velocity_code_max", "vel_code_max"),
            ("distinct_velocity_codes", "distinct_vel_codes"),
        ):
            if row.get(key) != stats[skey]:
                raise ValueError(f"{stamp}: index {key}={row.get(key)} but recomputed {stats[skey]}")
        for v in ALLOWED_CODES:
            global_hist[v] += stats["hist"][v]
        total_bytes += len(sample)
        if n % 10 == 0 or n == len(rows):
            print(f"verified {n}/{len(rows)} scan={stamp}", flush=True)

    if seen != set(sources):
        raise ValueError("index does not cover every pinned scan")
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        raise ValueError("manifest sample_count/total_size_bytes disagree with verified output")
    if series.get("numeric_kind") != "uint" or series.get("bit_width") != 8 or series.get("role") != "primary":
        raise ValueError("manifest series declaration changed")
    vel_codes = [v for v in range(VEL_CODE_MIN, VEL_CODE_MAX + 1) if global_hist[v]]
    if len(vel_codes) != VEL_CODE_MAX - VEL_CODE_MIN + 1:
        raise ValueError(f"only {len(vel_codes)} of 32 velocity codes occur across the series")
    months = {t[:6] for t in sources}
    if len(months) < 12:
        raise ValueError(f"scans cover only {len(months)} calendar months")
    echo = sum(global_hist[v] for v in vel_codes)
    print(
        f"verify_ok samples={len(rows)} bytes={total_bytes} months={len(months)} echo_fraction={echo / total_bytes:.4f} "
        f"undetect_fraction={global_hist[UNDETECT_CODE] / total_bytes:.4f} nodata_fraction={global_hist[NODATA_CODE] / total_bytes:.4f}"
    )
    return 0


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------
def make_synthetic_tiff(raster: bytes, key: str, *, software: str = SOFTWARE, gdal_items: dict | None = None,
                        width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """Build a tiled LZW GeoTIFF mirroring the product layout (padded edge tiles)."""
    across = (width + TILE - 1) // TILE
    down = (height + TILE - 1) // TILE
    tiles = []
    for ty in range(down):
        for tx in range(across):
            t = bytearray(TILE_BYTES)
            for r in range(TILE):
                y = ty * TILE + r
                if y >= height:
                    break
                x0 = tx * TILE
                w = min(TILE, width - x0)
                t[r * TILE : r * TILE + w] = raster[y * width + x0 : y * width + x0 + w]
            tiles.append(lzw_encode(bytes(t), clear_every=(997 if (ty + tx) % 2 else None)))
    stamp = scan_time_of(key)
    items = GDAL_ITEMS if gdal_items is None else gdal_items
    gdal_xml = "<GDALMetadata>\n" + "".join(
        f'  <Item name="{k}"' + (' sample="0" role="offset"' if k == "OFFSET" else ' sample="0" role="scale"' if k == "SCALE" else "") + f">{v}</Item>\n"
        for k, v in items.items()
    ) + "</GDALMetadata>\n"
    geokeys = [1, 1, 0, 7, 1024, 0, 1, 1, 1025, 0, 1, 1, 1026, 34737, 22, 0, 2049, 34737, 7, 22, 2054, 0, 1, 9102,
               3072, 0, 1, EPSG_PROJECTED, 3076, 0, 1, 9001]
    entries_spec = [
        (T_WIDTH, 3, [width]),
        (T_LENGTH, 3, [height]),
        (T_BPS, 3, [8]),
        (T_COMPRESSION, 3, [5]),
        (T_PHOTOMETRIC, 3, [1]),
        (T_DESCRIPTION, 2, DESCRIPTION),
        (T_SPP, 3, [1]),
        (T_PLANAR, 3, [1]),
        (T_SOFTWARE, 2, software),
        (T_DATETIME, 2, f"{stamp[0:4]}:{stamp[4:6]}:{stamp[6:8]} {stamp[8:10]}:{stamp[10:12]}:00"),
        (T_PREDICTOR, 3, [1]),
        (T_TILE_WIDTH, 3, [TILE]),
        (T_TILE_LENGTH, 3, [TILE]),
        (T_TILE_OFFSETS, 4, [0] * len(tiles)),
        (T_TILE_BYTE_COUNTS, 4, [len(t) for t in tiles]),
        (T_SAMPLE_FORMAT, 3, [1]),
        (T_PIXEL_SCALE, 12, list(PIXEL_SCALE)),
        (T_TIEPOINT, 12, list(TIEPOINT)),
        (T_GEOKEYS, 3, geokeys),
        (T_GEOASCII, 2, "ETRS89 / TM35FIN(E,N)|ETRS89|"),
        (T_GDAL_METADATA, 2, gdal_xml),
        (T_GDAL_NODATA, 2, GDAL_NODATA_TEXT),
    ]
    n_entries = len(entries_spec)
    data_start = 8 + 2 + 12 * n_entries + 4
    extra = bytearray()
    entries = []
    offsets_pos = None
    for tag, typ, vals in entries_spec:
        if typ == 2:
            blob = vals.encode("ascii") + b"\x00"
            count = len(blob)
        else:
            fmt = {3: "H", 4: "I", 12: "d"}[typ]
            blob = struct.pack("<" + fmt * len(vals), *vals)
            count = len(vals)
        if len(blob) <= 4:
            entries.append(struct.pack("<HHI", tag, typ, count) + blob.ljust(4, b"\x00"))
        else:
            off = data_start + len(extra)
            if tag == T_TILE_OFFSETS:
                offsets_pos = len(extra)
            extra.extend(blob)
            if len(extra) % 2:
                extra.append(0)
            entries.append(struct.pack("<HHII", tag, typ, count, off))
    payload_start = data_start + len(extra)
    tile_offsets = []
    pos = payload_start
    for t in tiles:
        tile_offsets.append(pos)
        pos += len(t)
    struct.pack_into(f"<{len(tiles)}I", extra, offsets_pos, *tile_offsets)
    head = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", n_entries) + b"".join(entries) + struct.pack("<I", 0)
    assert len(head) == data_start
    return head + bytes(extra) + b"".join(tiles)


def synthetic_raster(rng: random.Random) -> bytes:
    """Radar-like field: coverage disc, undetect background, folded velocity patches."""
    c = (WIDTH - 1) / 2.0
    r_max2 = (WIDTH / 2.0 - 3) ** 2
    pix = bytearray(VALUES_PER_SCAN)
    for y in range(HEIGHT):
        dy2 = (y - c) ** 2
        row = y * WIDTH
        for x in range(0, WIDTH):
            d2 = (x - c) ** 2 + dy2
            if d2 > r_max2:
                pix[row + x] = NODATA_CODE
            elif (x // 97 + y // 61) % 3 == 0:
                pix[row + x] = UNDETECT_CODE
            else:
                v = ((x - y) // 23 + rng.randrange(-1, 2)) % 32  # folded ramp
                pix[row + x] = VEL_CODE_MIN + v
    return bytes(pix)


def expect_reject(fn, label: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"selftest: {label} was accepted")


def cmd_selftest(_args: argparse.Namespace) -> int:
    rng = random.Random(20261005)
    cases = [
        b"",
        b"A",
        b"ABABABABABABABAB",  # KwKwK case
        b"\x00" * 50000,  # long runs: width growth to 12
        bytes(rng.randrange(256) for _ in range(60000)),  # table fills -> clear codes
        bytes(rng.choice(b"\x00\x70\x8f\xff") for _ in range(30000)),
        bytes((i * 7 // 13) & 0xFF for i in range(40000)),
    ]
    for i, case in enumerate(cases):
        for clear_every in (None, 300):
            enc = lzw_encode(case, clear_every)
            if lzw_decode(enc, len(case)) != case:
                raise AssertionError(f"LZW round trip failed for case {i} clear_every={clear_every}")
    good = lzw_encode(b"radial velocity radial velocity radial", None)
    for bad in (good[:-2], good[:3]):
        expect_reject(lambda b=bad: lzw_decode(b, 38), "truncated LZW stream")
    expect_reject(lambda: lzw_decode(good, 37), "wrong expected LZW length")

    key = "2025/06/15/fikor/202506151200_fikor_ppi_0.5_vrad_qc.tif"
    raster = synthetic_raster(rng)
    tiff = make_synthetic_tiff(raster, key)
    decoded = decode_scan(tiff, key, "synthetic.tif")
    if decoded != raster:
        raise AssertionError("synthetic GeoTIFF decode mismatch")
    stats = raster_stats(decoded)
    check_semantics(stats, decoded, "synthetic.tif")
    hdr = check_layout(tiff[:4096], key, "synthetic-header", header_only=True)
    if hdr["software"] != SOFTWARE:
        raise AssertionError("header-only check returned wrong software")
    # drift must be rejected
    expect_reject(lambda: check_layout(tiff, "2025/06/15/fikor/202506151205_fikor_ppi_0.5_vrad_qc.tif", "x"),
                  "DateTime / key mismatch")
    expect_reject(lambda: check_layout(make_synthetic_tiff(raster[: 2003 * 2003], key, software="Rack_fmi.fi 16.4"), key, "x"),
                  "different Rack software version")
    bad_items = dict(GDAL_ITEMS, SCALE="0.375")
    expect_reject(lambda: check_layout(make_synthetic_tiff(raster, key, gdal_items=bad_items), key, "x"),
                  "different GDAL SCALE")
    expect_reject(lambda: decode_scan(tiff[:-50], key, "x"), "truncated file")
    drifted = bytearray(raster)
    drifted[1001 * WIDTH + 1001] = 150  # a code outside the folded interval
    expect_reject(lambda: check_semantics(raster_stats(bytes(drifted)), bytes(drifted), "x"), "out-of-interval code")
    empty = bytes(b if b == NODATA_CODE else UNDETECT_CODE for b in raster)
    expect_reject(lambda: check_semantics(raster_stats(empty), empty, "x"), "near-empty scan")
    print(
        f"selftest_ok lzw_cases={len(cases) * 2} synthetic_tiff_bytes={len(tiff)} "
        f"echo={stats['echo_count']} undetect={stats['undetect_count']} nodata={stats['nodata_count']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)
    p = sub.add_parser("check-header")
    p.add_argument("file")
    p.add_argument("key")
    p.add_argument("--header-only", action="store_true")
    p.set_defaults(func=cmd_check_header)
    p = sub.add_parser("rank")
    p.add_argument("--inventory", required=True)
    p.add_argument("--min-size", type=int, required=True)
    p.add_argument("--depth", type=int, required=True)
    p.set_defaults(func=cmd_rank)
    p = sub.add_parser("select")
    p.add_argument("--checked", required=True)
    p.add_argument("--per-month", type=int, required=True)
    p.add_argument("--base", required=True)
    p.set_defaults(func=cmd_select)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", required=True)
        p.add_argument("--data-dir", default=".data")
        p.add_argument("--recipe-dir", required=True)
        p.set_defaults(func=func)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
