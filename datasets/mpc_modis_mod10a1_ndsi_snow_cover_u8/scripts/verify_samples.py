#!/usr/bin/env python3
"""Independent verifier for mpc_modis_mod10a1_ndsi_snow_cover_u8.

Does not import the build decoder. It:
  * re-derives the pinned plan from the probe table with the documented
    selection rule (scripts/select_plan.py) and requires sources.tsv to match;
  * re-checks identity, type, shape, and index bookkeeping of every sample;
  * recomputes the value histogram from the stored uint8 bytes and applies
    the same missing-value policy as the build (every value in 0..100 or one
    of the documented flag codes; valid 0..100 fraction >= 0.40; snow 1..100
    fraction >= 0.02; >= 20 distinct valid values);
  * re-decodes the primary IFD of the local source COG with a separate
    minimal TIFF reader and requires a byte-identical grid;
  * checks realized scope against manifest.toml and the pinned plan, and
    that consecutive observations of the same tile differ materially.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import select_plan  # noqa: E402  (selection rule only; not the decoder)

DATASET_ID = "mpc_modis_mod10a1_ndsi_snow_cover_u8"
SERIES_ID = "modis_mod10a1_daily_ndsi_snow_cover_u8"
PROBE_TABLE = "probe_candidates_20261006.tsv"
SIDE = 2400
VALUES = SIDE * SIDE
FLAGS = {200: "missing_data", 201: "no_decision", 211: "night", 237: "inland_water",
         239: "ocean", 250: "cloud", 254: "detector_saturated", 255: "fill"}
ALLOWED = set(range(101)) | set(FLAGS)
MIN_VALID_FRACTION = 0.40
MIN_SNOW_FRACTION = 0.02
MIN_VALID_DISTINCT = 20
MIN_PAIR_CHANGE_FRACTION = 0.05


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
    shape = tuple(tags.get(t, (default,))[0] for t, default in
                  ((256, None), (257, None), (258, None), (259, 1), (317, 1), (322, None), (323, None), (339, 1)))
    if shape != (SIDE, SIDE, 8, 8, 1, 512, 512, 1):
        fail(f"unexpected source primary IFD {shape}")
    offsets, counts = tags[324], tags[325]
    per_row = -(-SIDE // 512)
    if len(offsets) != per_row * per_row or len(counts) != len(offsets):
        fail("unexpected tile table length")
    grid = bytearray(VALUES)
    for t, (off, n) in enumerate(zip(offsets, counts)):
        d = zlib.decompressobj()
        tile = d.decompress(blob[off:off + n]) + d.flush()
        if not d.eof or d.unused_data or len(tile) != 512 * 512:
            fail(f"bad Deflate tile {t}")
        y0, x0 = (t // per_row) * 512, (t % per_row) * 512
        w, h = min(512, SIDE - x0), min(512, SIDE - y0)
        for r in range(h):
            base = (y0 + r) * SIDE + x0
            grid[base:base + w] = tile[r * 512:r * 512 + w]
    return bytes(grid)


def changed_fraction(a: bytes, b: bytes) -> float:
    x = int.from_bytes(a, "little") ^ int.from_bytes(b, "little")
    return (VALUES - x.to_bytes(VALUES, "little").count(0)) / VALUES


def main() -> None:
    data_root = Path(os.environ["DATA_ROOT"])
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
        plan_rows = list(csv.DictReader(fh, delimiter="\t"))
    derived = select_plan.select(select_plan.read_tsv(str(recipe_dir / "scripts" / PROBE_TABLE)))
    if derived != plan_rows:
        fail("sources.tsv is not the output of the documented selection rule on the probe table")
    plan = {r["item_id"]: r for r in plan_rows}

    rows = [json.loads(x) for x in index_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != len(plan) or len(rows) != int(series["sample_count"]):
        fail(f"index rows={len(rows)} plan={len(plan)} manifest={series['sample_count']}")

    by_tile: dict[str, list[tuple[str, bytes]]] = {}
    hashes: set[str] = set()
    sizes: list[int] = []
    seen_items: set[str] = set()
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
        if src is None or item in seen_items:
            fail(f"index item not in pinned plan or repeated: {item}")
        seen_items.add(item)
        if (row["modis_tile"], row["observation_date"]) != (src["tile"], src["date"]):
            fail(f"tile/date mismatch for {item}")

        sample = data_root / row["sample_path"]
        payload = sample.read_bytes()
        if len(payload) != VALUES:
            fail(f"sample size {len(payload)} for {sample}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["sample_sha256"] or digest in hashes:
            fail(f"sample hash mismatch or duplicate: {sample}")
        hashes.add(digest)

        hist = {v: c for v in range(256) if (c := payload.count(v))}
        outside = sorted(set(hist) - ALLOWED)
        if outside:
            fail(f"values outside the NDSI_Snow_Cover code set in {sample}: {outside[:20]}")
        valid = sum(c for v, c in hist.items() if v <= 100)
        snow = sum(c for v, c in hist.items() if 1 <= v <= 100)
        valid_distinct = sum(1 for v in hist if v <= 100)
        if valid / VALUES < MIN_VALID_FRACTION:
            fail(f"valid fraction {valid / VALUES:.4f} < {MIN_VALID_FRACTION} in {sample}")
        if snow / VALUES < MIN_SNOW_FRACTION:
            fail(f"snow fraction {snow / VALUES:.4f} < {MIN_SNOW_FRACTION} in {sample}")
        if valid_distinct < MIN_VALID_DISTINCT or len(hist) < 3:
            fail(f"degenerate sample {sample} valid_distinct={valid_distinct} distinct={len(hist)}")
        recomputed = {
            "valid_count": valid, "snow_count": snow, "snow_free_count": hist.get(0, 0),
            "valid_distinct": valid_distinct, "distinct_values": len(hist),
            "min": min(hist), "max": max(hist), "sum": sum(v * c for v, c in hist.items()),
            "flag_counts": {name: hist.get(code, 0) for code, name in sorted(FLAGS.items())},
        }
        diff = {k: (row.get(k), v) for k, v in recomputed.items() if row.get(k) != v}
        if diff:
            fail(f"index statistics mismatch {item}: {diff}")

        blob = (raster_dir / f"{item}_NDSI_Snow_Cover.tif").read_bytes()
        if len(blob) != int(src["size_bytes"]) or hashlib.md5(blob).hexdigest() != src["content_md5_hex"]:
            fail(f"local source does not match pinned size/MD5: {item}")
        if redecode(blob) != payload:
            fail(f"independent re-decode differs from sample: {item}")

        by_tile.setdefault(row["modis_tile"], []).append((row["observation_date"], payload))
        sizes.append(len(payload))
        print(f"verified item={item} valid={valid / VALUES:.4f} snow={snow / VALUES:.4f} "
              f"cloud={hist.get(250, 0) / VALUES:.4f} valid_distinct={valid_distinct}")

    if seen_items != set(plan):
        fail("index does not cover every pinned item")
    for tile, obs in sorted(by_tile.items()):
        obs.sort()
        for (d1, a), (d2, b) in zip(obs, obs[1:]):
            frac = changed_fraction(a, b)
            if frac < MIN_PAIR_CHANGE_FRACTION:
                fail(f"tile {tile}: only {frac:.4f} of pixels change between {d1} and {d2}")
            print(f"pair_change tile={tile} {d1}->{d2} changed_fraction={frac:.4f}")

    total = sum(sizes)
    if total != int(series["total_size_bytes"]):
        fail(f"total bytes {total} != manifest {series['total_size_bytes']}")
    if total > 1_000_000_000 or statistics.median(sizes) < 1000:
        fail("primary cap or median floor violated")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(stats["samples"]) != len(rows) or int(stats["primary_sample_bytes"]) != total:
        fail("ingest_stats totals mismatch")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} tiles={len(by_tile)} "
          f"dates={len({r['observation_date'] for r in rows})} bytes={total}")


if __name__ == "__main__":
    main()
