#!/usr/bin/env python3
"""Independent verifier for mpc_modis_mod13a1_ndvi_i16.

Does not import the build decoder. For every indexed sample it:
  * re-checks identity, type, shape, and index bookkeeping;
  * recomputes value statistics from the stored int16 bytes and applies the
    same missing-value policy as the build (values in [-2000, 10000] or the
    -3000 fill; fill fraction <= 0.15; >= 1000 distinct valid values);
  * re-decodes the primary IFD of the local source COG with a separate
    minimal TIFF reader and requires a byte-identical grid;
  * checks realized scope against manifest.toml and the pinned plan.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import struct
import sys
import tomllib
import zlib
from array import array
from collections import Counter
from pathlib import Path

DATASET_ID = "mpc_modis_mod13a1_ndvi_i16"
SERIES_ID = "modis_mod13a1_16day_ndvi_i16"
SIDE = 2400
VALUES = SIDE * SIDE
FILL = -3000
LO, HI = -2000, 10000
MAX_FILL_FRACTION = 0.15
MIN_VALID_DISTINCT = 1000
MIN_PERIOD_CHANGE_FRACTION = 0.05
EXPECTED_CONTINENT_TILES = {
    "north_america": 5, "south_america": 4, "europe": 2, "africa": 5, "asia": 6, "oceania": 2,
}


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def ifd0_tags(blob: bytes, wanted: set[int]) -> dict[int, tuple[int, ...]]:
    """Read selected numeric tags of the first IFD only (little-endian classic TIFF)."""
    if blob[:4] != b"II*\x00":
        fail("source is not a little-endian classic TIFF")
    (ifd,) = struct.unpack("<I", blob[4:8])
    (count,) = struct.unpack("<H", blob[ifd:ifd + 2])
    sizes = {3: (2, "H"), 4: (4, "I"), 16: (8, "Q")}
    found: dict[int, tuple[int, ...]] = {}
    for k in range(count):
        tag, kind, n, field = struct.unpack("<HHI4s", blob[ifd + 2 + 12 * k: ifd + 14 + 12 * k])
        if tag not in wanted:
            continue
        if kind not in sizes:
            fail(f"tag {tag} has unexpected type {kind}")
        width, code = sizes[kind]
        raw = field[:width * n] if width * n <= 4 else blob[struct.unpack("<I", field)[0]:][:width * n]
        found[tag] = struct.unpack("<" + code * n, raw)
    return found


def redecode(blob: bytes) -> bytes:
    tags = ifd0_tags(blob, {256, 257, 258, 259, 317, 322, 323, 324, 325, 339})
    shape = tuple(tags.get(t, (None,))[0] for t in (256, 257, 258, 259, 317, 322, 323, 339))
    if shape != (SIDE, SIDE, 16, 8, 1, 512, 512, 2):
        fail(f"unexpected source primary IFD {shape}")
    offsets, counts = tags[324], tags[325]
    per_row = -(-SIDE // 512)
    if len(offsets) != per_row * per_row or len(counts) != len(offsets):
        fail("unexpected tile table length")
    grid = array("h", bytes(2 * VALUES))
    for t, (off, n) in enumerate(zip(offsets, counts)):
        d = zlib.decompressobj()
        tile = array("h")
        tile.frombytes(d.decompress(blob[off:off + n]) + d.flush())
        if not d.eof or d.unused_data or len(tile) != 512 * 512:
            fail(f"bad Deflate tile {t}")
        y0, x0 = (t // per_row) * 512, (t % per_row) * 512
        w, h = min(512, SIDE - x0), min(512, SIDE - y0)
        for r in range(h):
            base = (y0 + r) * SIDE + x0
            grid[base:base + w] = tile[r * 512:r * 512 + w]
    if sys.byteorder != "little":
        grid.byteswap()
    return grid.tobytes()


def main() -> None:
    root = Path(os.environ["REPO_ROOT"])
    data_root = root / os.environ["DATA_DIR"]
    recipe_dir = Path(os.environ["RECIPE_DIR"])
    index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
    stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
    raster_dir = Path(os.environ["DOWNLOAD_DIR"]) / "rasters"
    for p in (index_path, stats_path):
        if not p.is_file():
            fail(f"missing {p}")

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest primary series missing")
    series = series[0]
    with (recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as fh:
        plan = {r["item_id"]: r for r in csv.DictReader(fh, delimiter="\t")}

    rows = [json.loads(x) for x in index_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != len(plan) or len(rows) != int(series["sample_count"]):
        fail(f"index rows={len(rows)} plan={len(plan)} manifest={series['sample_count']}")

    by_tile: dict[str, dict[int, array]] = {}
    continents: dict[str, set[str]] = {}
    hashes: set[str] = set()
    sizes: list[int] = []
    for row in rows:
        expect = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "int",
            "bit_width": 16, "endianness": "little", "element_size_bytes": 2, "value_count": VALUES,
            "sample_size_bytes": 2 * VALUES, "sample_shape": [SIDE, SIDE], "sample_rank": 2,
            "source_format": series["source_format"], "source_field": series["source_field"],
            "natural_record_kind": series["natural_record_kind"],
        }
        bad = {k: row.get(k) for k, v in expect.items() if row.get(k) != v}
        if bad:
            fail(f"index row identity mismatch {row.get('item_id')}: {bad}")
        item = row["item_id"]
        src = plan.get(item)
        if src is None:
            fail(f"index item not in pinned plan: {item}")
        if (row["modis_tile"], f"{row['day_of_year']:03d}") != (src["tile"], src["day_of_year"]):
            fail(f"tile/period mismatch for {item}")

        sample = data_root / row["sample_path"]
        payload = sample.read_bytes()
        if len(payload) != 2 * VALUES:
            fail(f"sample size {len(payload)} for {sample}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["sample_sha256"] or digest in hashes:
            fail(f"sample hash mismatch or duplicate: {sample}")
        hashes.add(digest)

        vals = array("h")
        vals.frombytes(payload)
        if sys.byteorder != "little":
            vals.byteswap()
        hist = Counter(vals)
        fill = hist.pop(FILL, 0)
        if not hist:
            fail(f"all-fill sample {sample}")
        lo, hi = min(hist), max(hist)
        if lo < LO or hi > HI:
            fail(f"values outside [{LO},{HI}] U {{{FILL}}} in {sample}: {lo}..{hi}")
        if fill / VALUES > MAX_FILL_FRACTION:
            fail(f"fill fraction {fill / VALUES:.4f} in {sample}")
        if len(hist) < MIN_VALID_DISTINCT or lo == hi:
            fail(f"degenerate sample {sample} distinct={len(hist)}")
        valid_sum = sum(v * c for v, c in hist.items())
        recomputed = {
            "fill_count": fill, "valid_min": lo, "valid_max": hi, "valid_distinct": len(hist),
            "valid_sum": valid_sum, "min": FILL if fill else lo, "max": hi,
        }
        diff = {k: (row.get(k), v) for k, v in recomputed.items() if row.get(k) != v}
        if diff:
            fail(f"index statistics mismatch {item}: {diff}")

        blob = (raster_dir / f"{item}_500m_16_days_NDVI.tif").read_bytes()
        if len(blob) != int(src["size_bytes"]) or hashlib.md5(blob).hexdigest() != src["content_md5_hex"]:
            fail(f"local source does not match pinned size/MD5: {item}")
        if redecode(blob) != payload:
            fail(f"independent re-decode differs from sample: {item}")

        by_tile.setdefault(row["modis_tile"], {})[int(row["day_of_year"])] = vals
        continents.setdefault(row["continent"], set()).add(row["modis_tile"])
        sizes.append(len(payload))
        print(f"verified item={item} fill={fill / VALUES:.4f} valid=[{lo},{hi}] distinct={len(hist)}")

    if {k: len(v) for k, v in continents.items()} != EXPECTED_CONTINENT_TILES:
        fail(f"continent/tile scope mismatch: { {k: len(v) for k, v in continents.items()} }")
    for tile, periods in sorted(by_tile.items()):
        if sorted(periods) != [17, 193]:
            fail(f"tile {tile} lacks the DOY 017/193 pair")
        a, b = periods[17], periods[193]
        changed = sum(1 for x, y in zip(a, b) if x != y) / VALUES
        if changed < MIN_PERIOD_CHANGE_FRACTION:
            fail(f"tile {tile}: only {changed:.4f} of pixels change between periods")
        print(f"period_change tile={tile} changed_fraction={changed:.4f}")

    total = sum(sizes)
    if total != int(series["total_size_bytes"]):
        fail(f"total bytes {total} != manifest {series['total_size_bytes']}")
    if total > 1_000_000_000 or statistics.median(sizes) // 2 < 1000:
        fail("primary cap or median floor violated")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(stats["samples"]) != len(rows) or int(stats["primary_sample_bytes"]) != total:
        fail("ingest_stats totals mismatch")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} tiles={len(by_tile)} bytes={total}")


if __name__ == "__main__":
    main()
