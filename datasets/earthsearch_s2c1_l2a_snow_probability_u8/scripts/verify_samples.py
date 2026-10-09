#!/usr/bin/env python3
"""Independent check of the built samples.

    python3 -I verify_samples.py RECIPE_DIR DATA_ROOT

Re-decodes every source COG with its own TIFF/Deflate/predictor code (it
does not import snw_cog), compares the result byte-for-byte with the sample,
and re-applies the same value policy as build: values 0..100 only, at least
20 distinct values, mode share <= 0.80, nonzero share and nonzero mean equal
to the producer's GDAL statistics, no duplicate grids, manifest totals match.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import sys
import tomllib
import zlib
from collections import Counter
from itertools import accumulate
from pathlib import Path

DATASET_ID = "earthsearch_s2c1_l2a_snow_probability_u8"
SERIES_ID = "s2c1_l2a_snw_20m_snow_probability_u8"
W = H = 5490
T = 512


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def redecode(data: bytes) -> tuple[bytes, dict]:
    if data[:4] != b"II*\x00":
        fail("not little-endian TIFF")
    ifd = struct.unpack_from("<I", data, 4)[0]
    tags = {}
    for i in range(struct.unpack_from("<H", data, ifd)[0]):
        tag, ft, cnt, val = struct.unpack_from("<HHII", data, ifd + 2 + 12 * i)
        tags[tag] = (ft, cnt, val, ifd + 2 + 12 * i + 8)

    def ints(tag: int) -> list[int]:
        ft, cnt, val, pos = tags[tag]
        fmt = {3: "H", 4: "I"}[ft]
        size = struct.calcsize(fmt) * cnt
        src = data[pos:pos + size] if size <= 4 else data[val:val + size]
        return list(struct.unpack("<%d%s" % (cnt, fmt), src))

    for tag, want in ((256, W), (257, H), (258, 8), (259, 8), (277, 1), (317, 2), (322, T), (323, T)):
        if ints(tag)[0] != want:
            fail(f"tag {tag} != {want}")
    offs, cnts = ints(324), ints(325)
    ft, cnt, val, _ = tags[42112]
    meta = data[val:val + cnt].decode("latin1")
    gstats = {k: float(v) for k, v in re.findall(r'"STATISTICS_(\w+)" sample="0">([^<]+)<', meta)}
    grid = bytearray(W * H)
    per_row = -(-W // T)
    for k, (o, c) in enumerate(zip(offs, cnts)):
        tile = zlib.decompressobj().decompress(data[o:o + c])
        if len(tile) != T * T:
            fail(f"tile {k} size {len(tile)}")
        y0, x0 = (k // per_row) * T, (k % per_row) * T
        w = min(T, W - x0)
        for r in range(min(T, H - y0)):
            line = bytes(accumulate(tile[r * T:r * T + w], lambda a, b: (a + b) & 0xFF))
            grid[(y0 + r) * W + x0:(y0 + r) * W + x0 + w] = line
    return bytes(grid), gstats


def main() -> None:
    recipe, data_root = Path(sys.argv[1]), Path(sys.argv[2])
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
    sources = {r["item_id"]: r for r in csv.DictReader(open(recipe / "sources.tsv", encoding="utf-8", newline=""), delimiter="\t")}
    index = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(x) for x in index.read_text(encoding="utf-8").splitlines() if x.strip()]
    if sorted(r["item_id"] for r in rows) != sorted(sources):
        fail("index items do not match sources.tsv one-to-one")
    seen, total = set(), 0
    for row in rows:
        for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "uint"),
                          ("bit_width", 8), ("endianness", "little"), ("element_size_bytes", 1),
                          ("role", "primary"), ("source_format", series["source_format"]),
                          ("source_field", series["source_field"]), ("natural_record_kind", series["natural_record_kind"])):
            if row.get(key) != want:
                fail(f"{row.get('item_id')}: {key}={row.get(key)!r} != {want!r}")
        sample = (data_root / row["sample_path"]).read_bytes()
        if len(sample) != W * H or row["value_count"] != W * H or row["sample_size_bytes"] != W * H:
            fail(f"{row['item_id']}: size mismatch")
        src_row = sources[row["item_id"]]
        src = (data_root / "downloads" / DATASET_ID / "snw_20m" / f"{row['item_id']}_SNW_20m.tif").read_bytes()
        if hashlib.sha256(src).hexdigest() != src_row["sha256"]:
            fail(f"{row['item_id']}: source SHA-256 mismatch")
        grid, gstats = redecode(src)
        if grid != sample:
            fail(f"{row['item_id']}: sample differs from independent re-decode")
        hist = Counter(sample)
        n = len(sample)
        if max(hist) > 100:
            fail(f"{row['item_id']}: value {max(hist)} outside 0..100")
        if len(hist) < 20:
            fail(f"{row['item_id']}: only {len(hist)} distinct values")
        mode = max(hist.values()) / n
        if mode > 0.80:
            fail(f"{row['item_id']}: mode share {mode:.3f} > 0.80")
        nz = n - hist.get(0, 0)
        if abs(100 * nz / n - gstats["VALID_PERCENT"]) > 0.0051:
            fail(f"{row['item_id']}: nonzero % disagrees with GDAL statistics")
        if abs(sum(k * v for k, v in hist.items()) / nz - gstats["MEAN"]) > 1e-6:
            fail(f"{row['item_id']}: nonzero mean disagrees with GDAL statistics")
        if row["min"] != min(hist) or row["max"] != max(hist):
            fail(f"{row['item_id']}: index min/max mismatch")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != row["sample_sha256"] or digest in seen:
            fail(f"{row['item_id']}: digest mismatch or duplicate grid")
        seen.add(digest)
        total += n
        print(f"ok {row['item_id']} zero={hist.get(0, 0) / n:.3f} hundred={hist.get(100, 0) / n:.3f} "
              f"distinct={len(hist)} mode={mode:.3f}", flush=True)
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != {len(rows)}/{total}")
    if total > 1_000_000_000:
        fail("primary bytes exceed 1 GB cap")
    stats = json.loads((data_root / "filtered" / DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    if stats["samples"] != len(rows) or stats["primary_sample_bytes"] != total:
        fail("ingest_stats disagree with index")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} bytes={total}")


if __name__ == "__main__":
    main()
