"""Decode the pinned HDR+ Pixel/Pixel XL N000 DNG frames into raw uint16 CFA
mosaics (one sample per burst) and write the sample index.

env: DATA_ROOT, RECIPE_DIR
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

RECIPE_DIR = Path(os.environ["RECIPE_DIR"])
sys.path.insert(0, str(RECIPE_DIR / "scripts"))
import hdrplus_dng as hd  # noqa: E402

DATASET_ID = "google_hdrplus_pixel_raw_bayer_u16"
SERIES_ID = "pixel_raw_bayer_cfa_u16"
NATURAL_RECORD_KIND = "hdrplus_burst_first_input_frame_payload_n000"
EXPECTED_SAMPLES = 29
WIDTH, HEIGHT = 4048, 3036
MAX_PRIMARY_BYTES = 1_000_000_000

data_root = Path(os.environ["DATA_ROOT"])
dng_dir = data_root / "downloads" / DATASET_ID / "dng"
samples_dir = data_root / "samples" / DATASET_ID / SERIES_ID
index_dir = data_root / "index" / DATASET_ID
filtered_dir = data_root / "filtered" / DATASET_ID

with open(RECIPE_DIR / "sources.tsv", newline="") as fh:
    sources = list(csv.DictReader(fh, delimiter="\t"))
if len(sources) != EXPECTED_SAMPLES:
    raise SystemExit(f"sources.tsv has {len(sources)} rows, expected {EXPECTED_SAMPLES}")

shutil.rmtree(samples_dir, ignore_errors=True)
samples_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
filtered_dir.mkdir(parents=True, exist_ok=True)


def cfa_means(frame, width, height):
    out = []
    for dy in (0, 1):
        for dx in (0, 1):
            s = n = 0
            for y in range(dy, height, 2):
                row = frame[y * width + dx:(y + 1) * width:2]
                s += sum(row)
                n += len(row)
            out.append(round(s / n, 4))
    return out


rows = []
total = 0
seen_hashes = set()
for src in sources:
    burst = src["burst"]
    path = dng_dir / f"{burst}__payload_N000.dng"
    if not path.is_file():
        raise SystemExit(f"missing download {path}; run download.sh first")
    buf = path.read_bytes()
    if len(buf) != int(src["size_bytes"]) or hashlib.md5(buf).hexdigest() != src["md5_hex"]:
        raise SystemExit(f"source identity changed: {path}")
    info = hd.dng_raw_info(hd.parse_tiff_ifd0(buf))
    hd.check_pixel_cfa(info)
    t0 = time.time()
    info, frame = hd.decode_dng_cfa(buf, info)
    dt = time.time() - t0
    if len(frame) != WIDTH * HEIGHT:
        raise SystemExit(f"{burst}: decoded {len(frame)} values")
    vmin, vmax = min(frame), max(frame)
    if vmax > info["white_level"]:
        raise SystemExit(f"{burst}: value {vmax} above WhiteLevel {info['white_level']}")
    if vmin == vmax:
        raise SystemExit(f"{burst}: constant frame")
    raw = hd.frame_le_bytes(frame)
    sha = hashlib.sha256(raw).hexdigest()
    if sha in seen_hashes:
        raise SystemExit(f"{burst}: duplicate decoded frame")
    seen_hashes.add(sha)
    out = samples_dir / f"{burst}.u16"
    out.write_bytes(raw)
    total += len(raw)
    if total > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes exceed cap: {total}")
    means = cfa_means(frame, WIDTH, HEIGHT)
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(raw),
        "value_count": len(frame),
        "min": int(vmin),
        "max": int(vmax),
        "sha256": sha,
        "sample_geometry": "2d_raster",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["sensor_row", "sensor_column"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "burst": burst,
        "camera_model": info["model"],
        "cfa_pattern": info["cfa_pattern"],
        "black_level_per_cfa_site": info["black_level"],
        "white_level": info["white_level"],
        "cfa_site_means": means,
        "orientation_tag": info["orientation"],
        "capture_datetime": info["datetime"],
        "source_md5": src["md5_hex"],
        "source_url": src["url"],
    })
    print(f"built burst={burst} model={info['model']} min={vmin} max={vmax} "
          f"cfa_means={means} decode_s={dt:.1f}", flush=True)

with open(index_dir / "samples.jsonl", "w") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
agg = hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest()
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(rows),
    "primary_values": sum(r["value_count"] for r in rows),
    "primary_bytes": total,
    "aggregate_sha256": agg,
    "models": sorted({r["camera_model"] for r in rows}),
    "global_min": min(r["min"] for r in rows),
    "global_max": max(r["max"] for r in rows),
}
(filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
print(json.dumps(stats, sort_keys=True))
