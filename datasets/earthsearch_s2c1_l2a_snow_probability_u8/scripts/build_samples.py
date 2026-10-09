#!/usr/bin/env python3
"""Decode the pinned SNW_20m COGs into raw uint8 5490x5490 snow-probability grids.

    python3 -I build_samples.py SOURCES_TSV DATA_ROOT

Local files only. One sample per Sentinel-2 L2A product (one MGRS tile
acquisition). Values are written exactly as decoded; nothing is remapped.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snw_cog  # noqa: E402

DATASET_ID = "earthsearch_s2c1_l2a_snow_probability_u8"
SERIES_ID = "s2c1_l2a_snw_20m_snow_probability_u8"
SOURCE_FORMAT = "cloud_optimized_geotiff"
SOURCE_FIELD = "SNW_20m.band_1.snow_probability_percent"
RECORD_KIND = "sentinel2_c1_l2a_mgrs_tile_snw_20m_grid"
N_VALUES = snw_cog.WIDTH * snw_cog.HEIGHT
MAX_MODE_SHARE = 0.80
MIN_DISTINCT = 20
MAX_PRIMARY_BYTES = 1_000_000_000


def grid_stats(grid: bytes) -> dict:
    hist = Counter(grid)
    n = len(grid)
    nz = n - hist.get(0, 0)
    mode_value, mode_count = max(hist.items(), key=lambda kv: (kv[1], -kv[0]))
    return {
        "min": min(hist), "max": max(hist), "distinct_values": len(hist),
        "zero_fraction": round(hist.get(0, 0) / n, 6),
        "hundred_fraction": round(hist.get(100, 0) / n, 6),
        "intermediate_fraction": round((nz - hist.get(100, 0)) / n, 6),
        "mode_value": mode_value, "mode_share": round(mode_count / n, 6),
        "nonzero_fraction": nz / n,
        "nonzero_mean": (sum(k * v for k, v in hist.items()) / nz) if nz else 0.0,
    }


def main() -> None:
    sources, data_root = Path(sys.argv[1]), Path(sys.argv[2])
    raster_dir = data_root / "downloads" / DATASET_ID / "snw_20m"
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filter_dir = data_root / "filtered" / DATASET_ID
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filter_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(sources, encoding="utf-8", newline=""), delimiter="\t"))
    index_rows, records, digests = [], [], set()
    for r in rows:
        src = raster_dir / f"{r['item_id']}_SNW_20m.tif"
        data = src.read_bytes()
        if len(data) != int(r["size_bytes"]) or hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise SystemExit(f"{src.name}: size/SHA-256 mismatch against sources.tsv")
        lay = snw_cog.layout(data)
        grid = snw_cog.decode(data)
        if len(grid) != N_VALUES:
            raise SystemExit(f"{src.name}: decoded {len(grid)} values")
        st = grid_stats(grid)
        if st["max"] > 100:
            raise SystemExit(f"{src.name}: value {st['max']} outside 0..100")
        if st["distinct_values"] < MIN_DISTINCT or st["mode_share"] > MAX_MODE_SHARE:
            raise SystemExit(f"{src.name}: degenerate grid distinct={st['distinct_values']} mode_share={st['mode_share']}")
        gs = lay["stats"]
        # cross-check against the producer's own GDAL statistics (nodata=0)
        if abs(st["nonzero_fraction"] * 100 - gs["VALID_PERCENT"]) > 0.0051:
            raise SystemExit(f"{src.name}: nonzero % {st['nonzero_fraction'] * 100:.4f} != header {gs['VALID_PERCENT']}")
        if abs(st["nonzero_mean"] - gs["MEAN"]) > 1e-6:
            raise SystemExit(f"{src.name}: nonzero mean {st['nonzero_mean']:.9f} != header {gs['MEAN']}")
        digest = hashlib.sha256(grid).hexdigest()
        if digest in digests:
            raise SystemExit(f"{src.name}: duplicate decoded grid")
        digests.add(digest)
        out = out_dir / f"{r['item_id']}.u8"
        out.write_bytes(grid)
        row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint", "bit_width": 8, "endianness": "little",
            "element_size_bytes": 1, "sample_size_bytes": len(grid), "value_count": len(grid),
            "shape": [snw_cog.HEIGHT, snw_cog.WIDTH], "axes": ["y", "x"],
            "source_format": SOURCE_FORMAT, "source_field": SOURCE_FIELD, "natural_record_kind": RECORD_KIND,
            "item_id": r["item_id"], "grid_code": r["grid_code"], "datetime": r["datetime"],
            "source_url": r["url"], "source_sha256": r["sha256"], "sample_sha256": digest,
            "min": st["min"], "max": st["max"],
        }
        index_rows.append(row)
        rec = {k: v for k, v in st.items() if k not in ("nonzero_fraction", "nonzero_mean")}
        rec.update(item_id=r["item_id"], grid_code=r["grid_code"], datetime=r["datetime"],
                   cloud_cover=float(r["cloud_cover"]), snow_ice_percentage=float(r["snow_ice_percentage"]))
        records.append(rec)
        print(f"sample {r['item_id']} zero={st['zero_fraction']:.3f} hundred={st['hundred_fraction']:.3f} "
              f"intermediate={st['intermediate_fraction']:.3f} distinct={st['distinct_values']} mode={st['mode_share']:.3f}",
              flush=True)

    total = sum(x["sample_size_bytes"] for x in index_rows)
    if total > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes {total} exceed cap")
    with open(index_dir / "samples.jsonl", "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "samples": len(index_rows),
        "primary_values": total, "primary_sample_bytes": total,
        "median_value_count": statistics.median(x["value_count"] for x in index_rows),
        "mode_share_max": max(x["mode_share"] for x in records),
        "records": records,
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built samples={len(index_rows)} primary_bytes={total} mode_share_max={stats['mode_share_max']}")


if __name__ == "__main__":
    main()
