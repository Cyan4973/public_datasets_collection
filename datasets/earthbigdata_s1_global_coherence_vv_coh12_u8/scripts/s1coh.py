#!/usr/bin/env python3
"""Earth Big Data global seasonal Sentinel-1 coherence tiles -> raw uint8 rasters.

Pure standard-library Python. Subcommands:

  selftest              round-trip synthetic TIFF-LZW streams and a synthetic
                        GeoTIFF through the encoder/parser/decoder used here
  check-header FILE TILE
                        validate the classic-TIFF header/IFD of one downloaded
                        tile against the pinned product layout (download.sh)
  build                 decode pinned local tiles into samples + index
  verify                independently re-derive every sample and re-check the
                        index, manifest totals and non-degeneracy rules

Only local files are read by build/verify; network I/O lives in download.sh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "earthbigdata_s1_global_coherence_vv_coh12_u8"
SERIES_ID = "summer_vv_coh12_u8"
WIDTH = 1200
HEIGHT = 1200
ROWS_PER_STRIP = 6
STRIP_COUNT = HEIGHT // ROWS_PER_STRIP  # 200
STRIP_BYTES = WIDTH * ROWS_PER_STRIP  # 7200
VALUES_PER_TILE = WIDTH * HEIGHT  # 1,440,000
NODATA_DN = 0
MAX_DN = 100  # gamma = DN / 100, coherence in [0, 1]
PIXEL_DEG = 1.0 / 1200.0
EXPECTED_TILE_COUNT = 150
EXPECTED_SOURCE_BYTES = 161_185_497
MAX_NODATA_FRACTION = 0.5  # a land-interior tile that is mostly nodata is rejected

# TIFF tag ids
T_WIDTH, T_LENGTH, T_BPS, T_COMPRESSION, T_PHOTOMETRIC = 256, 257, 258, 259, 262
T_STRIP_OFFSETS, T_SPP, T_ROWS_PER_STRIP, T_STRIP_BYTE_COUNTS = 273, 277, 278, 279
T_PLANAR, T_PREDICTOR, T_SAMPLE_FORMAT = 284, 317, 339
T_TILE_WIDTH, T_TILE_OFFSETS = 322, 324
T_PIXEL_SCALE, T_TIEPOINT, T_GEOKEYS, T_GDAL_NODATA = 33550, 33922, 34735, 42113

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


# --------------------------------------------------------------------------
# TIFF-LZW (Compression=5): MSB-first codes, 256=Clear, 257=EOI, first free
# code 258, 9..12-bit codes with "early change" (the code width grows when the
# next free code reaches 2**width - 1).
# --------------------------------------------------------------------------
_BASE_TABLE = [bytes([i]) for i in range(256)] + [b"", b""]


def lzw_decode(data: bytes, expected_len: int) -> bytes:
    """Decode one TIFF-LZW strip. Requires an EOI code and exact output size."""
    table = list(_BASE_TABLE)
    out = bytearray()
    n = len(data)
    pos = 0
    acc = 0
    nbits = 0
    width = 9
    limit = 511  # next free code at which width grows (2**width - 1)
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
    if not saw_eoi:
        raise ValueError("LZW: strip ended without EOI code")
    if len(out) != expected_len:
        raise ValueError(f"LZW: decoded {len(out)} bytes, expected {expected_len}")
    if pos < n - 1:
        # allow at most one trailing padding byte after the EOI code
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

    # The encoder's table runs one entry ahead of the decoder's, so the
    # encoder widens when its next free code reaches 2**width (libtiff:
    # free_ent > maxcode), which is the decoder's 2**width - 1.
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
# Classic little-endian TIFF parsing
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
        elif typ in (7,):
            tags[tag] = tuple(buf[off : off + nbytes])
        else:
            tags[tag] = struct.unpack_from("<" + TYPE_FMT[typ] * n, buf, off)
    (next_ifd,) = struct.unpack_from("<I", buf, end)
    return {"tags": tags, "next_ifd": next_ifd}


def tile_origin(tile: str) -> tuple[float, float]:
    """Upper-left (lon, lat) for an N..W... tile label, e.g. N40W105 -> (-105, 40)."""
    if len(tile) != 7 or tile[0] not in "NS" or tile[3] not in "EW":
        raise ValueError(f"bad tile label {tile!r}")
    lat = int(tile[1:3]) * (1 if tile[0] == "N" else -1)
    lon = int(tile[4:7]) * (1 if tile[3] == "E" else -1)
    return float(lon), float(lat)


def check_layout(buf: bytes, tile: str, name: str) -> dict:
    """Validate the pinned product layout; return strip offsets/counts and geo info."""
    info = parse_tiff(buf, name)
    tags = info["tags"]

    def one(tag: int, label: str, default=None):
        if tag not in tags:
            if default is None:
                raise ValueError(f"{name}: missing {label} tag {tag}")
            return default
        vals = tags[tag]
        if len(vals) != 1:
            raise ValueError(f"{name}: {label} has {len(vals)} values")
        return vals[0]

    expect = [
        (T_WIDTH, "ImageWidth", WIDTH, None),
        (T_LENGTH, "ImageLength", HEIGHT, None),
        (T_BPS, "BitsPerSample", 8, None),
        (T_COMPRESSION, "Compression", 5, None),
        (T_SPP, "SamplesPerPixel", 1, 1),
        (T_ROWS_PER_STRIP, "RowsPerStrip", ROWS_PER_STRIP, None),
        (T_PLANAR, "PlanarConfiguration", 1, 1),
        (T_PREDICTOR, "Predictor", 1, 1),
        (T_SAMPLE_FORMAT, "SampleFormat", 1, 1),
    ]
    for tag, label, want, default in expect:
        got = one(tag, label, default)
        if got != want:
            raise ValueError(f"{name}: {label}={got}, expected {want}")
    if T_TILE_WIDTH in tags or T_TILE_OFFSETS in tags:
        raise ValueError(f"{name}: tiled TIFF layout is not the pinned strip layout")
    offsets = tags.get(T_STRIP_OFFSETS, ())
    counts = tags.get(T_STRIP_BYTE_COUNTS, ())
    if len(offsets) != STRIP_COUNT or len(counts) != STRIP_COUNT:
        raise ValueError(f"{name}: {len(offsets)} strip offsets / {len(counts)} byte counts, expected {STRIP_COUNT}")
    for i, (off, cnt) in enumerate(zip(offsets, counts)):
        if cnt <= 0 or off < 8 or off + cnt > len(buf):
            raise ValueError(f"{name}: strip {i} [{off}, +{cnt}) outside file of {len(buf)} bytes")
    nodata = tags.get(T_GDAL_NODATA, ("",))[0].strip()
    if nodata != "0":
        raise ValueError(f"{name}: GDAL_NODATA={nodata!r}, expected '0'")
    if T_GEOKEYS not in tags:
        raise ValueError(f"{name}: missing GeoKeyDirectory")
    scale = tags.get(T_PIXEL_SCALE)
    tie = tags.get(T_TIEPOINT)
    if not scale or not tie or len(tie) < 6:
        raise ValueError(f"{name}: missing ModelPixelScale/ModelTiepoint")
    if abs(scale[0] - PIXEL_DEG) > 1e-9 or abs(scale[1] - PIXEL_DEG) > 1e-9:
        raise ValueError(f"{name}: pixel scale {scale[:2]} != 3 arcsec")
    lon0, lat0 = tile_origin(tile)
    if tie[0] != 0 or tie[1] != 0 or abs(tie[3] - lon0) > 1e-6 or abs(tie[4] - lat0) > 1e-6:
        raise ValueError(f"{name}: tiepoint {tie[:6]} does not match tile {tile} origin ({lon0}, {lat0})")
    return {"offsets": offsets, "counts": counts, "next_ifd": info["next_ifd"], "tiepoint": tie[:6], "pixel_scale": scale[:2]}


def decode_tile(buf: bytes, tile: str, name: str) -> bytes:
    layout = check_layout(buf, tile, name)
    out = bytearray()
    for i, (off, cnt) in enumerate(zip(layout["offsets"], layout["counts"])):
        try:
            strip = lzw_decode(buf[off : off + cnt], STRIP_BYTES)
        except ValueError as exc:
            raise ValueError(f"{name}: strip {i}: {exc}") from None
        out += strip
    if len(out) != VALUES_PER_TILE:
        raise ValueError(f"{name}: decoded {len(out)} values, expected {VALUES_PER_TILE}")
    return bytes(out)


def raster_stats(raster: bytes) -> dict:
    # bytes.count runs at C speed; 256 passes over 1.44 MB take well under 1 s
    hist = [raster.count(value) for value in range(256)]
    nodata = hist[NODATA_DN]
    valid = [v for v in range(1, 256) if hist[v]]
    return {
        "hist": hist,
        "nodata_count": nodata,
        "valid_count": VALUES_PER_TILE - nodata,
        "valid_min": min(valid) if valid else None,
        "valid_max": max(valid) if valid else None,
        "distinct_values": sum(1 for h in hist if h),
    }


def check_semantics(stats: dict, name: str) -> None:
    if stats["valid_count"] == 0:
        raise ValueError(f"{name}: all pixels are nodata (DN 0)")
    if stats["valid_max"] is not None and stats["valid_max"] > MAX_DN:
        raise ValueError(f"{name}: DN {stats['valid_max']} exceeds documented coherence maximum {MAX_DN}")
    if stats["distinct_values"] < 3:
        raise ValueError(f"{name}: degenerate raster with {stats['distinct_values']} distinct values")
    if stats["nodata_count"] / VALUES_PER_TILE > MAX_NODATA_FRACTION:
        raise ValueError(f"{name}: nodata fraction {stats['nodata_count'] / VALUES_PER_TILE:.3f} > {MAX_NODATA_FRACTION}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def read_sources(path: Path) -> list[dict]:
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != ["tile", "filename", "size_bytes", "md5", "last_modified", "url"]:
        raise ValueError(f"unexpected sources.tsv header {header}")
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        row["size_bytes"] = int(row["size_bytes"])
        rows.append(row)
    tiles = [r["tile"] for r in rows]
    if len(rows) != EXPECTED_TILE_COUNT or len(set(tiles)) != len(tiles):
        raise ValueError(f"sources.tsv has {len(rows)} rows ({len(set(tiles))} unique), expected {EXPECTED_TILE_COUNT}")
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


def load_source(row: dict, download_dir: Path) -> tuple[bytes, str]:
    path = download_dir / "tiles" / row["filename"]
    if not path.is_file():
        raise FileNotFoundError(f"missing local tile {path}")
    if path.stat().st_size != row["size_bytes"]:
        raise ValueError(f"{row['filename']}: size {path.stat().st_size} != pinned {row['size_bytes']}")
    md5, sha = file_digests(path)
    if md5 != row["md5"]:
        raise ValueError(f"{row['filename']}: md5 {md5} != pinned ETag {row['md5']}")
    return path.read_bytes(), sha


def manifest_series(recipe_dir: Path) -> dict:
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    for series in manifest.get("series", []):
        if series.get("id") == SERIES_ID:
            return series
    raise ValueError(f"manifest lacks series {SERIES_ID}")


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
def cmd_check_header(args: argparse.Namespace) -> int:
    path = Path(args.file)
    buf = path.read_bytes()
    layout = check_layout(buf, args.tile, path.name)
    # decode the first strip as a cheap semantic probe of the compressed stream
    first = lzw_decode(buf[layout["offsets"][0] : layout["offsets"][0] + layout["counts"][0]], STRIP_BYTES)
    if max(first) > MAX_DN:
        raise ValueError(f"{path.name}: first strip has DN {max(first)} > {MAX_DN}")
    print(f"header_ok tile={args.tile} strips={STRIP_COUNT} bytes={len(buf)}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    repo = Path(args.repo_root)
    data = repo / args.data_dir
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
    per_tile = []
    total_hist = [0] * 256
    seen_hashes: dict[str, str] = {}
    for n, src in enumerate(sorted(sources, key=lambda r: r["tile"]), 1):
        tile = src["tile"]
        buf, source_sha = load_source(src, download_dir)
        raster = decode_tile(buf, tile, src["filename"])
        stats = raster_stats(raster)
        check_semantics(stats, src["filename"])
        sample_sha = hashlib.sha256(raster).hexdigest()
        if sample_sha in seen_hashes:
            raise ValueError(f"{tile}: decoded raster duplicates {seen_hashes[sample_sha]}")
        seen_hashes[sample_sha] = tile
        out = sample_dir / f"{tile}.bin"
        tmp = out.with_suffix(".bin.tmp")
        tmp.write_bytes(raster)
        os.replace(tmp, out)
        for v in range(256):
            total_hist[v] += stats["hist"][v]
        lon0, lat0 = tile_origin(tile)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(data)),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(raster),
                "value_count": len(raster),
                "sample_shape": [HEIGHT, WIDTH],
                "sample_axes": ["lat_row_north_to_south", "lon_col_west_to_east"],
                "tile": tile,
                "upper_left_lon": lon0,
                "upper_left_lat": lat0,
                "nodata_value": NODATA_DN,
                "nodata_count": stats["nodata_count"],
                "min": 0 if stats["nodata_count"] else stats["valid_min"],
                "max": stats["valid_max"],
                "valid_min": stats["valid_min"],
                "valid_max": stats["valid_max"],
                "distinct_values": stats["distinct_values"],
                "sample_sha256": sample_sha,
                "source_url": src["url"],
                "source_size_bytes": src["size_bytes"],
                "source_md5": src["md5"],
                "source_sha256": source_sha,
            }
        )
        per_tile.append({"tile": tile, "nodata_count": stats["nodata_count"], "valid_min": stats["valid_min"], "valid_max": stats["valid_max"], "distinct_values": stats["distinct_values"]})
        if n % 10 == 0 or n == len(sources):
            print(f"decoded {n}/{len(sources)} tile={tile} nodata={stats['nodata_count']} range={stats['valid_min']}..{stats['valid_max']}", flush=True)

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
        "nodata_fraction": round(total_hist[0] / total_bytes, 6),
        "dn_histogram": {str(v): c for v, c in enumerate(total_hist) if c},
        "aggregate_sample_sha256_of_sha256s": agg.hexdigest(),
        "tiles": per_tile,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")

    series = manifest_series(recipe_dir)
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        raise ValueError(
            f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    print(f"build_ok samples={len(rows)} bytes={total_bytes} nodata_fraction={summary['nodata_fraction']} aggregate={agg.hexdigest()}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo_root)
    data = repo / args.data_dir
    recipe_dir = Path(args.recipe_dir)
    download_dir = data / "downloads" / DATASET_ID
    sample_dir = data / "samples" / DATASET_ID / SERIES_ID
    index_path = data / "index" / DATASET_ID / "samples.jsonl"
    sources = {r["tile"]: r for r in read_sources(recipe_dir / "sources.tsv")}
    series = manifest_series(recipe_dir)

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(sources):
        raise ValueError(f"index has {len(rows)} rows, expected {len(sources)}")
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    expected_names = sorted(f"{t}.bin" for t in sources)
    if on_disk != expected_names:
        raise ValueError("sample directory contents differ from the pinned tile list")

    seen_tiles = set()
    seen_hashes = set()
    total_bytes = 0
    global_hist = [0] * 256
    for n, row in enumerate(rows, 1):
        tile = row.get("tile")
        if tile not in sources or tile in seen_tiles:
            raise ValueError(f"index row {n}: unexpected or duplicate tile {tile!r}")
        seen_tiles.add(tile)
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": VALUES_PER_TILE,
            "value_count": VALUES_PER_TILE,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{tile}.bin",
            "nodata_value": NODATA_DN,
        }
        for key, want in fixed.items():
            if row.get(key) != want:
                raise ValueError(f"index row {n} ({tile}): {key}={row.get(key)!r}, expected {want!r}")
        sample = (data / row["sample_path"]).read_bytes()
        if len(sample) != VALUES_PER_TILE:
            raise ValueError(f"{tile}: sample has {len(sample)} bytes")
        # independent re-derivation from the pinned source tile
        src = sources[tile]
        buf, source_sha = load_source(src, download_dir)
        if row.get("source_sha256") != source_sha or row.get("source_md5") != src["md5"]:
            raise ValueError(f"{tile}: source digest differs from index")
        derived = decode_tile(buf, tile, src["filename"])
        if derived != sample:
            raise ValueError(f"{tile}: sample bytes differ from re-decoded source raster")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != row.get("sample_sha256") or sha in seen_hashes:
            raise ValueError(f"{tile}: sample hash mismatch or duplicate raster")
        seen_hashes.add(sha)
        stats = raster_stats(sample)
        check_semantics(stats, tile)
        for key in ("nodata_count", "valid_min", "valid_max", "distinct_values"):
            if row.get(key) != stats[key]:
                raise ValueError(f"{tile}: index {key}={row.get(key)} but recomputed {stats[key]}")
        for v in range(256):
            global_hist[v] += stats["hist"][v]
        # row-level structure: no row of the raster may be the only varying part
        rows_distinct = len({sample[r * WIDTH : (r + 1) * WIDTH] for r in range(0, HEIGHT, 100)})
        if rows_distinct < 3:
            raise ValueError(f"{tile}: sampled raster rows are near-identical ({rows_distinct} distinct)")
        total_bytes += len(sample)
        if n % 10 == 0 or n == len(rows):
            print(f"verified {n}/{len(rows)} tile={tile}", flush=True)

    if seen_tiles != set(sources):
        raise ValueError("index does not cover every pinned tile")
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        raise ValueError("manifest sample_count/total_size_bytes disagree with verified output")
    if series.get("numeric_kind") != "uint" or series.get("bit_width") != 8 or series.get("role") != "primary":
        raise ValueError("manifest series declaration changed")
    valid_values = [v for v in range(1, 256) if global_hist[v]]
    if len(valid_values) < 20:
        raise ValueError(f"only {len(valid_values)} distinct coherence DNs across the series")
    print(
        f"verify_ok samples={len(rows)} bytes={total_bytes} nodata_fraction={global_hist[0] / total_bytes:.6f} "
        f"dn_range={min(valid_values)}..{max(valid_values)} distinct={len(valid_values)}"
    )
    return 0


def make_synthetic_tiff(raster: bytes, tile: str) -> bytes:
    """Build a strip-organized LZW GeoTIFF mirroring the product layout."""
    strips = [lzw_encode(raster[i * STRIP_BYTES : (i + 1) * STRIP_BYTES], clear_every=(997 if i % 2 else None)) for i in range(STRIP_COUNT)]
    lon0, lat0 = tile_origin(tile)
    extra = bytearray()
    entries = []
    base_ifd = 8
    n_entries = 15
    data_start = base_ifd + 2 + 12 * n_entries + 4

    def add_data(blob: bytes) -> int:
        off = data_start + len(extra)
        extra.extend(blob)
        if len(extra) % 2:
            extra.append(0)
        return off

    strip_payload_offsets = []
    payload = bytearray()
    for s in strips:
        strip_payload_offsets.append(len(payload))
        payload.extend(s)
    scale_off = add_data(struct.pack("<3d", PIXEL_DEG, PIXEL_DEG, 0.0))
    tie_off = add_data(struct.pack("<6d", 0.0, 0.0, 0.0, lon0, lat0, 0.0))
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326]
    geo_off = add_data(struct.pack(f"<{len(geokeys)}H", *geokeys))
    offsets_off = add_data(b"\x00" * (4 * STRIP_COUNT))
    counts_off = add_data(struct.pack(f"<{STRIP_COUNT}I", *[len(s) for s in strips]))
    payload_start = data_start + len(extra)
    struct.pack_into(f"<{STRIP_COUNT}I", extra, offsets_off - data_start, *[payload_start + o for o in strip_payload_offsets])

    def inline(tag: int, typ: int, vals: list[int]) -> bytes:
        fmt = {3: "H", 4: "I"}[typ]
        raw = struct.pack("<" + fmt * len(vals), *vals).ljust(4, b"\x00")
        return struct.pack("<HHI", tag, typ, len(vals)) + raw

    def ref(tag: int, typ: int, count: int, off: int) -> bytes:
        return struct.pack("<HHII", tag, typ, count, off)

    entries = [
        inline(T_WIDTH, 3, [WIDTH]),
        inline(T_LENGTH, 3, [HEIGHT]),
        inline(T_BPS, 3, [8]),
        inline(T_COMPRESSION, 3, [5]),
        inline(T_PHOTOMETRIC, 3, [1]),
        ref(T_STRIP_OFFSETS, 4, STRIP_COUNT, offsets_off),
        inline(T_SPP, 3, [1]),
        inline(T_ROWS_PER_STRIP, 3, [ROWS_PER_STRIP]),
        ref(T_STRIP_BYTE_COUNTS, 4, STRIP_COUNT, counts_off),
        inline(T_PLANAR, 3, [1]),
        inline(T_SAMPLE_FORMAT, 3, [1]),
        ref(T_PIXEL_SCALE, 12, 3, scale_off),
        ref(T_TIEPOINT, 12, 6, tie_off),
        ref(T_GEOKEYS, 3, len(geokeys), geo_off),
        struct.pack("<HHI", T_GDAL_NODATA, 2, 2) + b"0\x00\x00\x00",  # <=4 bytes: inline
    ]
    assert len(entries) == n_entries
    head = b"II*\x00" + struct.pack("<I", base_ifd) + struct.pack("<H", n_entries) + b"".join(entries) + struct.pack("<I", 0)
    assert len(head) == data_start
    return head + bytes(extra) + bytes(payload)


def cmd_selftest(_args: argparse.Namespace) -> int:
    rng = random.Random(20261005)
    cases = [
        b"",
        b"A",
        b"ABABABABABABABAB",  # KwKwK case
        b"\x00" * 50000,  # long runs: deep chains, width growth to 12
        bytes(rng.randrange(256) for _ in range(60000)),  # table fills -> clear codes
        bytes(rng.choice(b"\x00\x01\x02\x03") for _ in range(30000)),
        bytes((i * 7 // 13) & 0xFF for i in range(40000)),
    ]
    for i, case in enumerate(cases):
        for clear_every in (None, 300):
            enc = lzw_encode(case, clear_every)
            dec = lzw_decode(enc, len(case))
            if dec != case:
                raise AssertionError(f"LZW round trip failed for case {i} clear_every={clear_every}")
    # corrupted streams must be rejected, not silently accepted
    good = lzw_encode(b"hello hello hello coherence", None)
    for bad in (good[:-2], good[:3]):
        try:
            lzw_decode(bad, 27)
        except ValueError:
            pass
        else:
            raise AssertionError("truncated LZW stream was accepted")
    try:
        lzw_decode(good, 26)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong expected length was accepted")
    # synthetic GeoTIFF with coherence-like content: smooth field + speckle + nodata block
    pix = bytearray(VALUES_PER_TILE)
    for r in range(HEIGHT):
        base = 20 + (r * 60) // HEIGHT
        row_off = r * WIDTH
        for c in range(WIDTH):
            v = base + ((c * 17 + r * 3) % 23) - 11 + rng.randrange(-4, 5)
            pix[row_off + c] = max(1, min(MAX_DN, v))
    for r in range(100, 160):
        pix[r * WIDTH : r * WIDTH + 300] = b"\x00" * 300
    raster = bytes(pix)
    tiff = make_synthetic_tiff(raster, "N40W105")
    decoded = decode_tile(tiff, "N40W105", "synthetic.tif")
    if decoded != raster:
        raise AssertionError("synthetic GeoTIFF decode mismatch")
    stats = raster_stats(decoded)
    check_semantics(stats, "synthetic.tif")
    try:
        check_layout(tiff, "N41W105", "synthetic.tif")
    except ValueError:
        pass
    else:
        raise AssertionError("tiepoint/tile mismatch was accepted")
    print(f"selftest_ok lzw_cases={len(cases) * 2} synthetic_tiff_bytes={len(tiff)} nodata={stats['nodata_count']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)
    p = sub.add_parser("check-header")
    p.add_argument("file")
    p.add_argument("tile")
    p.set_defaults(func=cmd_check_header)
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
