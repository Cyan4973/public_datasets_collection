#!/usr/bin/env python3
"""Independent verifier for mpc_usda_cdl_confidence_u8.

Does not import the build decoder (scripts/cdl_cog.py). For every indexed
sample it:
  * re-checks identity, type, shape, and index bookkeeping;
  * recomputes value statistics from the stored uint8 bytes and applies the
    same missing-value policy as the build (0 = nodata kept in place, every
    other value in 1..100; zero share <= 0.10; largest single-value share
    <= 0.78; >= 40 distinct values);
  * re-decodes IFD0 of the local source COG with a separate minimal TIFF
    reader (including the GeoTIFF tie point vs. the item ID) and requires a
    byte-identical grid;
  * checks realized scope against manifest.toml and the pinned plan
    (51 tiles, per-region counts), and that no two grids are duplicates.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import struct
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "mpc_usda_cdl_confidence_u8"
SERIES_ID = "usda_cdl_2021_confidence_u8"
SIDE = 3000
TILE = 512
VALUES = SIDE * SIDE
VALID_HI = 100
MAX_ZERO_SHARE = 0.10
MAX_MODE_SHARE = 0.78
MIN_DISTINCT = 40
EXPECTED_REGIONS = {
    "corn_belt": 8, "plains_wheat": 8, "northern_plains": 8, "delta": 8,
    "central_valley": 8, "palouse_columbia": 3, "southeast": 8,
}


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def ifd0(blob: bytes) -> dict[int, tuple]:
    """Read numeric tags of the first IFD only (little-endian classic TIFF)."""
    if blob[:4] != b"II*\x00":
        fail("source is not a little-endian classic TIFF")
    (ifd,) = struct.unpack("<I", blob[4:8])
    (count,) = struct.unpack("<H", blob[ifd:ifd + 2])
    sizes = {3: (2, "H"), 4: (4, "I"), 12: (8, "d"), 16: (8, "Q")}
    found: dict[int, tuple] = {}
    for k in range(count):
        tag, kind, n, field = struct.unpack("<HHI4s", blob[ifd + 2 + 12 * k: ifd + 14 + 12 * k])
        if kind not in sizes:
            continue
        width, code = sizes[kind]
        raw = field[:width * n] if width * n <= 4 else blob[struct.unpack("<I", field)[0]:][:width * n]
        found[tag] = struct.unpack("<" + code * n, raw)
    return found


def redecode(blob: bytes) -> tuple[bytes, tuple[int, int]]:
    tags = ifd0(blob)
    shape = tuple(tags.get(t, (d,))[0] for t, d in
                  ((256, None), (257, None), (258, None), (259, 1), (277, 1), (317, 1), (322, None), (323, None), (339, 1)))
    if shape != (SIDE, SIDE, 8, 8, 1, 1, TILE, TILE, 1):
        fail(f"unexpected source primary IFD {shape}")
    tie = tags.get(33922)
    scale = tags.get(33550)
    if not tie or not scale or scale[:2] != (30.0, 30.0):
        fail("missing/unexpected GeoTIFF tie point or pixel scale")
    offsets, counts = tags[324], tags[325]
    per_row = -(-SIDE // TILE)
    if len(offsets) != per_row * per_row or len(counts) != len(offsets):
        fail("unexpected tile table length")
    grid = bytearray(VALUES)
    for t, (off, n) in enumerate(zip(offsets, counts)):
        d = zlib.decompressobj()
        try:
            tile = d.decompress(blob[off:off + n]) + d.flush()
        except zlib.error as exc:
            fail(f"corrupt Deflate tile {t}: {exc}")
        if not d.eof or d.unused_data or len(tile) != TILE * TILE:
            fail(f"bad Deflate tile {t}")
        y0, x0 = (t // per_row) * TILE, (t % per_row) * TILE
        w, h = min(TILE, SIDE - x0), min(TILE, SIDE - y0)
        for r in range(h):
            base = (y0 + r) * SIDE + x0
            grid[base:base + w] = tile[r * TILE:r * TILE + w]
    return bytes(grid), (int(round(tie[3])), int(round(tie[4])))


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

    regions: dict[str, int] = {}
    hashes: set[str] = set()
    sizes: list[int] = []
    total_zero = total_100 = 0
    for row in rows:
        expect = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "uint",
            "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "value_count": VALUES,
            "sample_size_bytes": VALUES, "sample_shape": [SIDE, SIDE], "sample_rank": 2,
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
        if row["region"] != src["region"]:
            fail(f"region mismatch for {item}")

        sample = data_root / row["sample_path"]
        payload = sample.read_bytes()
        if len(payload) != VALUES:
            fail(f"sample size {len(payload)} for {sample}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["sample_sha256"] or digest in hashes:
            fail(f"sample hash mismatch or duplicate: {sample}")
        hashes.add(digest)

        counts = {v: payload.count(bytes([v])) for v in range(256)}
        counts = {v: c for v, c in counts.items() if c}
        if sum(counts.values()) != VALUES:
            fail(f"histogram does not cover sample {sample}")
        illegal = sorted(v for v in counts if v > VALID_HI)
        if illegal:
            fail(f"values outside 0..100 in {sample}: {illegal[:10]}")
        zero = counts.get(0, 0)
        if zero / VALUES > MAX_ZERO_SHARE:
            fail(f"nodata share {zero / VALUES:.4f} in {sample}")
        mode_value, mode_count = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
        if mode_count / VALUES > MAX_MODE_SHARE:
            fail(f"mode share {mode_count / VALUES:.4f} (value {mode_value}) in {sample}")
        if len(counts) < MIN_DISTINCT:
            fail(f"degenerate sample {sample} distinct={len(counts)}")
        nonzero = VALUES - zero
        recomputed = {
            "min": min(counts), "max": max(counts), "sum": sum(v * c for v, c in counts.items()),
            "distinct": len(counts), "zero_count": zero, "count_100": counts.get(100, 0),
            "mode_value": mode_value, "nonzero_min": min(v for v in counts if v),
        }
        diff = {k: (row.get(k), v) for k, v in recomputed.items() if row.get(k) != v}
        if diff:
            fail(f"index statistics mismatch {item}: {diff}")
        if abs(float(row["nonzero_mean"]) - recomputed["sum"] / nonzero) > 1e-9:
            fail(f"nonzero_mean mismatch {item}")

        blob = (raster_dir / os.path.basename(src["url"])).read_bytes()
        if len(blob) != int(src["size_bytes"]) or hashlib.md5(blob).hexdigest() != src["content_md5_hex"]:
            fail(f"local source does not match pinned size/MD5: {item}")
        grid, origin = redecode(blob)
        if grid != payload:
            fail(f"independent re-decode differs from sample: {item}")
        _, _, x, y, _ = item.split("_")
        if origin != (int(x), int(y) + 30) or list(origin) != row["origin_xy_m"]:
            fail(f"GeoTIFF origin {origin} does not match item {item}")

        regions[row["region"]] = regions.get(row["region"], 0) + 1
        sizes.append(len(payload))
        total_zero += zero
        total_100 += counts.get(100, 0)
        print(f"verified item={item} region={row['region']} zero={zero / VALUES:.4f} "
              f"share100={counts.get(100, 0) / VALUES:.4f} mode={mode_value}:{mode_count / VALUES:.4f} distinct={len(counts)}")

    if regions != EXPECTED_REGIONS:
        fail(f"region scope mismatch: {regions}")
    total = sum(sizes)
    if total != int(series["total_size_bytes"]):
        fail(f"total bytes {total} != manifest {series['total_size_bytes']}")
    if total > 1_000_000_000 or statistics.median(sizes) < 1000:
        fail("primary cap or median floor violated")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(stats["samples"]) != len(rows) or int(stats["primary_sample_bytes"]) != total:
        fail("ingest_stats totals mismatch")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} bytes={total} "
          f"zero_share_overall={total_zero / total:.4f} share_100_overall={total_100 / total:.4f}")


if __name__ == "__main__":
    main()
