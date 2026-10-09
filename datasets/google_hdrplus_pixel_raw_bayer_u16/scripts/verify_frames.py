"""Independent verification of the HDR+ raw Bayer samples.

* index rows match sources.tsv one-to-one (burst order, model, source MD5)
* every sample is exactly 4048x3036 little-endian uint16; size/value counts agree
* min/max/sha256 recomputed from the stored bytes match the index
* values lie in 0..WhiteLevel (1023); no constant frames; no duplicate frames
* black-level sanity: the 0.1th percentile of a strided subsample is >= 40 and
  the median is >= 60 (Pixel BlackLevel is ~63.5-64; no black subtraction)
* CFA sanity: at least 64 distinct values per frame
* re-decode check: five deterministic tiles per frame (including the
  right-edge, bottom-edge and corner tiles, which exercise the crop) are
  decoded straight from the source DNG with decode_lj92 and placed with
  verify's own tile-geometry arithmetic; every overlapping pixel must match
* manifest sample_count / total_size_bytes and ingest_stats agree

env: DATA_ROOT, RECIPE_DIR
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tomllib
from array import array
from pathlib import Path

RECIPE_DIR = Path(os.environ["RECIPE_DIR"])
sys.path.insert(0, str(RECIPE_DIR / "scripts"))
import hdrplus_dng as hd  # noqa: E402

DATASET_ID = "google_hdrplus_pixel_raw_bayer_u16"
SERIES_ID = "pixel_raw_bayer_cfa_u16"
W, H = 4048, 3036
TW = TL = 256
WHITE = 1023

data_root = Path(os.environ["DATA_ROOT"])
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
dng_dir = data_root / "downloads" / DATASET_ID / "dng"

with open(RECIPE_DIR / "sources.tsv", newline="") as fh:
    sources = list(csv.DictReader(fh, delimiter="\t"))
manifest = tomllib.loads((RECIPE_DIR / "manifest.toml").read_text())
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1:
    raise SystemExit("manifest series missing")
series = series[0]

rows = [json.loads(l) for l in index_path.read_text().splitlines() if l.strip()]
if len(rows) != len(sources):
    raise SystemExit(f"index rows {len(rows)} != sources {len(sources)}")

tiles_across = -(-W // TW)
tiles_down = -(-H // TL)
n_tiles = tiles_across * tiles_down
total_bytes = 0
hashes = set()
for k, (row, src) in enumerate(zip(rows, sources)):
    if row["burst"] != src["burst"] or row["camera_model"] != src["model"] or row["source_md5"] != src["md5_hex"]:
        raise SystemExit(f"row {k} does not match sources.tsv: {row['burst']}")
    for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("role", "primary"),
                      ("numeric_kind", "uint"), ("bit_width", 16), ("endianness", "little"),
                      ("element_size_bytes", 2), ("value_count", W * H), ("sample_size_bytes", 2 * W * H),
                      ("sample_shape", [H, W]), ("cfa_pattern", "BGGR"), ("white_level", WHITE),
                      ("natural_record_kind", series["natural_record_kind"])):
        if row.get(key) != want:
            raise SystemExit(f"{row['burst']}: {key}={row.get(key)!r} want {want!r}")
    p = data_root / row["sample_path"]
    raw = p.read_bytes()
    if len(raw) != 2 * W * H:
        raise SystemExit(f"{p}: size {len(raw)}")
    sha = hashlib.sha256(raw).hexdigest()
    if sha != row["sha256"]:
        raise SystemExit(f"{p}: sha256 mismatch")
    if sha in hashes:
        raise SystemExit(f"{p}: duplicate frame")
    hashes.add(sha)
    a = array("H")
    a.frombytes(raw)
    if sys.byteorder == "big":
        a.byteswap()
    vmin, vmax = min(a), max(a)
    if (vmin, vmax) != (row["min"], row["max"]):
        raise SystemExit(f"{p}: min/max mismatch")
    if vmin == vmax:
        raise SystemExit(f"{p}: constant frame")
    if vmax > WHITE:
        raise SystemExit(f"{p}: value {vmax} > WhiteLevel")
    sub = sorted(a[::101])
    p001 = sub[len(sub) // 1000]
    med = sub[len(sub) // 2]
    if p001 < 40 or med < 60:
        raise SystemExit(f"{p}: black-level sanity failed (p0.1={p001}, median={med})")
    if len(set(sub)) < 64:
        raise SystemExit(f"{p}: degenerate value set ({len(set(sub))} distinct)")

    # independent re-decode of selected tiles
    buf = (dng_dir / f"{src['burst']}__payload_N000.dng").read_bytes()
    if hashlib.md5(buf).hexdigest() != src["md5_hex"]:
        raise SystemExit(f"{src['burst']}: source MD5 mismatch")
    info = hd.dng_raw_info(hd.parse_tiff_ifd0(buf))
    hd.check_pixel_cfa(info)
    picks = sorted({(37 * k + 11) % n_tiles, (53 * k + 90) % n_tiles,
                    tiles_across - 1, n_tiles - tiles_across, n_tiles - 1})
    for t in picks:
        off, cnt = info["tile_offsets"][t], info["tile_byte_counts"][t]
        hdr, vals = hd.decode_lj92(buf[off:off + cnt])
        fr = hdr["frame"]
        if fr["width"] * len(fr["components"]) != TW or fr["height"] != TL:
            raise SystemExit(f"{src['burst']} tile {t}: geometry")
        ty, tx = t // tiles_across, t % tiles_across
        for r in range(TL):
            y = ty * TL + r
            if y >= H:
                break
            x0 = tx * TW
            n = min(TW, W - x0)
            if a[y * W + x0:y * W + x0 + n] != vals[r * TW:r * TW + n]:
                raise SystemExit(f"{src['burst']} tile {t} row {r}: re-decode mismatch")
    total_bytes += len(raw)
    print(f"verified burst={row['burst']} min={vmin} max={vmax} p0.1={p001} median={med} tiles={picks}", flush=True)

if total_bytes > 1_000_000_000:
    raise SystemExit("primary bytes exceed cap")
if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
    raise SystemExit(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
                     f"!= realized {len(rows)}/{total_bytes}")
stats = json.loads(stats_path.read_text())
agg = hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest()
if stats["samples"] != len(rows) or stats["primary_bytes"] != total_bytes or stats["aggregate_sha256"] != agg:
    raise SystemExit("ingest_stats mismatch")
print(f"verify ok samples={len(rows)} primary_bytes={total_bytes} aggregate_sha256={agg}")
