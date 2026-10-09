#!/usr/bin/env python3
"""Build step for mpc_usda_cdl_confidence_u8 (local files only).

Decodes each pinned CDL 2021 confidence COG's primary 3000x3000 uint8 grid
and writes it unchanged as raw uint8 in row-major order, one sample per
Planetary Computer tile. Writes the sample index and ingest stats.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdl_cog as cog  # noqa: E402

DATASET_ID = "mpc_usda_cdl_confidence_u8"
SERIES_ID = "usda_cdl_2021_confidence_u8"
SOURCE_FORMAT = "cloud_optimized_geotiff"
SOURCE_FIELD = "confidence"
NATURAL_RECORD_KIND = "complete_cdl_2021_confidence_tile"
SAMPLE_FORMAT = "raw homogeneous uint8 per-pixel classification confidence grid (1..100 percent; 0 = nodata/background)"
SAMPLE_GEOMETRY = "3000x3000_epsg5070_30m_tile"
EXPECTED_SAMPLES = 51
VALUES = cog.WIDTH * cog.HEIGHT
MAX_ZERO_SHARE = 0.10
MAX_MODE_SHARE = 0.78
MIN_DISTINCT = 40


def grid_stats(payload: bytes) -> dict[str, object]:
    if len(payload) != VALUES:
        raise SystemExit(f"decoded value count {len(payload)} != {VALUES}")
    hist = [0] * 256
    for value, count in Counter(payload).items():
        hist[value] = count
    illegal = [v for v in range(cog.VALID_MAX + 1, 256) if hist[v]]
    if illegal:
        raise SystemExit(f"values outside 0..100: {illegal[:10]}")
    present = [v for v in range(256) if hist[v]]
    nonzero = VALUES - hist[0]
    if nonzero == 0:
        raise SystemExit("sample has no nonzero confidence values")
    mode_value = max(range(256), key=lambda v: hist[v])
    return {
        "min": present[0],
        "max": present[-1],
        "sum": sum(v * hist[v] for v in present),
        "distinct": len(present),
        "zero_count": hist[0],
        "zero_share": hist[0] / VALUES,
        "count_100": hist[100],
        "share_100": hist[100] / VALUES,
        "mode_value": mode_value,
        "mode_share": hist[mode_value] / VALUES,
        "nonzero_min": min(v for v in present if v),
        "nonzero_mean": sum(v * hist[v] for v in present) / nonzero,
    }


def main() -> None:
    repo_root = Path(os.environ["REPO_ROOT"])
    data_dir = Path(os.environ["DATA_DIR"])
    data_root = data_dir if data_dir.is_absolute() else repo_root / data_dir
    recipe_dir = Path(os.environ["RECIPE_DIR"])
    download_dir = Path(os.environ["DOWNLOAD_DIR"])
    filter_dir = Path(os.environ["FILTER_DIR"])
    index_dir = Path(os.environ["INDEX_DIR"])
    samples_dir = Path(os.environ["SAMPLES_DIR"])
    raster_dir = download_dir / "rasters"
    out_dir = samples_dir / SERIES_ID

    with (recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as fh:
        plan = list(csv.DictReader(fh, delimiter="\t"))
    receipts_path = download_dir / "download_receipts.tsv"
    if not receipts_path.is_file():
        raise SystemExit(f"missing download receipts; run download.sh first: {receipts_path}")
    with receipts_path.open(encoding="utf-8", newline="") as fh:
        receipts = {row["item_id"]: row for row in csv.DictReader(fh, delimiter="\t")}
    if len(plan) != EXPECTED_SAMPLES or len({r["item_id"] for r in plan}) != EXPECTED_SAMPLES:
        raise SystemExit(f"plan rows={len(plan)} expected={EXPECTED_SAMPLES} unique item IDs")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for row in plan:
        item_id = row["item_id"]
        source = raster_dir / os.path.basename(row["url"])
        if not source.is_file():
            raise SystemExit(f"missing source raster: {source}")
        data = source.read_bytes()
        if len(data) != int(row["size_bytes"]):
            raise SystemExit(f"source size mismatch item={item_id} bytes={len(data)} expected={row['size_bytes']}")
        if hashlib.md5(data).hexdigest() != row["content_md5_hex"]:
            raise SystemExit(f"source MD5 mismatch item={item_id}")
        source_sha256 = hashlib.sha256(data).hexdigest()
        receipt = receipts.get(item_id)
        if receipt is None or receipt["sha256"] != source_sha256:
            raise SystemExit(f"download receipt missing or SHA-256 mismatch item={item_id}")
        try:
            primary = cog.check_file(data)
            origin = cog.tie_point_origin(primary)
            payload = bytes(cog.decode_primary(data))
        except cog.CogError as exc:
            raise SystemExit(f"decode failed item={item_id}: {exc}")
        stats = grid_stats(payload)
        if stats["zero_share"] > MAX_ZERO_SHARE:
            raise SystemExit(f"nodata share {stats['zero_share']:.4f} > {MAX_ZERO_SHARE} item={item_id}")
        if stats["mode_share"] > MAX_MODE_SHARE:
            raise SystemExit(f"mode share {stats['mode_share']:.4f} (value {stats['mode_value']}) > {MAX_MODE_SHARE} item={item_id}")
        if stats["distinct"] < MIN_DISTINCT:
            raise SystemExit(f"degenerate grid item={item_id} distinct={stats['distinct']}")
        sample_sha256 = hashlib.sha256(payload).hexdigest()
        if sample_sha256 in seen_hashes:
            raise SystemExit(f"duplicate decoded grid item={item_id}")
        seen_hashes.add(sample_sha256)

        output = out_dir / f"{item_id}_3000x3000.u8.bin"
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(payload),
            "value_count": VALUES,
            "sample_format": SAMPLE_FORMAT,
            "sample_geometry": SAMPLE_GEOMETRY,
            "sample_rank": 2,
            "sample_shape": [cog.HEIGHT, cog.WIDTH],
            "sample_axes": ["y", "x"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_format": SOURCE_FORMAT,
            "source_field": SOURCE_FIELD,
            "nodata_value": cog.NODATA,
            "valid_range": [cog.VALID_MIN, cog.VALID_MAX],
            "units": "percent",
            "item_id": item_id,
            "region": row["region"],
            "bbox_lonlat": [float(row["lon_min"]), float(row["lat_min"]), float(row["lon_max"]), float(row["lat_max"])],
            "epsg": 5070,
            "origin_xy_m": list(origin),
            "pixel_size_m": 30,
            "source_url": row["url"],
            "source_file": source.relative_to(data_root).as_posix(),
            "source_size_bytes": len(data),
            "source_md5": row["content_md5_hex"],
            "source_sha256": source_sha256,
            "sample_sha256": sample_sha256,
            **stats,
        })
        print(
            f"built item={item_id} region={row['region']} values={VALUES} range=[{stats['min']},{stats['max']}] "
            f"distinct={stats['distinct']} zero={stats['zero_share']:.4f} share100={stats['share_100']:.4f} "
            f"mode={stats['mode_value']}:{stats['mode_share']:.4f} mean_nonzero={stats['nonzero_mean']:.2f}"
        )

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for index_row in index_rows:
            fh.write(json.dumps(index_row, sort_keys=True) + "\n")

    total_bytes = sum(int(r["sample_size_bytes"]) for r in index_rows)
    total_zero = sum(int(r["zero_count"]) for r in index_rows)
    total_100 = sum(int(r["count_100"]) for r in index_rows)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "regions": dict(Counter(str(r["region"]) for r in index_rows)),
        "primary_values": VALUES * len(index_rows),
        "primary_sample_bytes": total_bytes,
        "zero_share_overall": total_zero / (VALUES * len(index_rows)),
        "share_100_overall": total_100 / (VALUES * len(index_rows)),
        "max_zero_share": max(float(r["zero_share"]) for r in index_rows),
        "max_mode_share": max(float(r["mode_share"]) for r in index_rows),
        "min_distinct": min(int(r["distinct"]) for r in index_rows),
        "samples_detail": [
            {k: r[k] for k in ("item_id", "region", "zero_share", "share_100", "mode_value", "mode_share",
                               "distinct", "nonzero_min", "nonzero_mean", "sample_sha256", "source_sha256")}
            for r in index_rows
        ],
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built dataset={DATASET_ID} samples={len(index_rows)} bytes={total_bytes} "
          f"zero_share_overall={summary['zero_share_overall']:.4f} share_100_overall={summary['share_100_overall']:.4f} "
          f"max_mode_share={summary['max_mode_share']:.4f}")


if __name__ == "__main__":
    main()
