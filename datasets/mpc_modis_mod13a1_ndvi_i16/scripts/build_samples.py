#!/usr/bin/env python3
"""Build step for mpc_modis_mod13a1_ndvi_i16 (local files only).

Decodes each pinned MOD13A1.061 NDVI COG's primary 2400x2400 int16 grid and
writes it unchanged as raw little-endian int16 in row-major order, one sample
per (tile, 16-day composite). Writes the sample index and ingest stats.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from array import array
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mod13a1_cog as cog  # noqa: E402

DATASET_ID = "mpc_modis_mod13a1_ndvi_i16"
SERIES_ID = "modis_mod13a1_16day_ndvi_i16"
SOURCE_FORMAT = "cloud_optimized_geotiff"
SOURCE_FIELD = "500m_16_days_NDVI"
NATURAL_RECORD_KIND = "complete_mod13a1_16_day_ndvi_tile"
SAMPLE_FORMAT = "raw homogeneous int16 NDVI grid (scale 0.0001, fill -3000)"
SAMPLE_GEOMETRY = "2400x2400_modis_sinusoidal_tile"
EXPECTED_SAMPLES = 48
EXPECTED_TILES = 24
EXPECTED_DOYS = {"017", "193"}
VALUES = cog.WIDTH * cog.HEIGHT
MAX_FILL_FRACTION = 0.15
MIN_VALID_DISTINCT = 1000


def ndvi_stats(payload: bytes) -> dict[str, object]:
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != VALUES:
        raise SystemExit(f"decoded value count {len(values)} != {VALUES}")
    fill = values.count(cog.FILL)
    distinct = set(values)
    valid = distinct - {cog.FILL}
    if not valid:
        raise SystemExit("sample has no valid NDVI values")
    vmin, vmax = min(valid), max(valid)
    if vmin < cog.VALID_MIN or vmax > cog.VALID_MAX:
        bad = sorted(x for x in valid if x < cog.VALID_MIN or x > cog.VALID_MAX)
        raise SystemExit(f"values outside documented domain: {bad[:10]}")
    total = sum(values)
    return {
        "fill_count": fill,
        "fill_fraction": fill / VALUES,
        "valid_count": VALUES - fill,
        "valid_min": vmin,
        "valid_max": vmax,
        "valid_sum": total - fill * cog.FILL,
        "valid_distinct": len(valid),
        "min": min(distinct),
        "max": max(distinct),
    }


def main() -> None:
    repo_root = Path(os.environ["REPO_ROOT"])
    data_root = repo_root / os.environ["DATA_DIR"]
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
    if len(plan) != EXPECTED_SAMPLES:
        raise SystemExit(f"plan rows={len(plan)} expected={EXPECTED_SAMPLES}")
    if {row["day_of_year"] for row in plan} != EXPECTED_DOYS or len({row["tile"] for row in plan}) != EXPECTED_TILES:
        raise SystemExit("plan does not cover 24 tiles x DOY 017/193")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for row in plan:
        item_id = row["item_id"]
        source = raster_dir / f"{item_id}_500m_16_days_NDVI.tif"
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
            payload = cog.decode_primary(data, item_id, row["tile"], row["start_date"])
        except cog.CogError as exc:
            raise SystemExit(f"decode failed item={item_id}: {exc}")
        if len(payload) != VALUES * 2:
            raise SystemExit(f"decoded bytes={len(payload)} item={item_id}")
        stats = ndvi_stats(payload)
        if stats["fill_fraction"] > MAX_FILL_FRACTION:
            raise SystemExit(f"fill fraction {stats['fill_fraction']:.4f} > {MAX_FILL_FRACTION} item={item_id}")
        if stats["valid_distinct"] < MIN_VALID_DISTINCT:
            raise SystemExit(f"degenerate NDVI grid item={item_id} distinct={stats['valid_distinct']}")
        sample_sha256 = hashlib.sha256(payload).hexdigest()
        if sample_sha256 in seen_hashes:
            raise SystemExit(f"duplicate decoded grid item={item_id}")
        seen_hashes.add(sample_sha256)

        name = f"{row['tile']}_A2024{row['day_of_year']}_{row['area']}_2400x2400.i16le.bin"
        output = out_dir / name
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
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
            "scale_factor": 0.0001,
            "fill_value": cog.FILL,
            "valid_range": [cog.VALID_MIN, cog.VALID_MAX],
            "item_id": item_id,
            "modis_tile": row["tile"],
            "continent": row["continent"],
            "area": row["area"],
            "composite_start_date": row["start_date"],
            "composite_end_date": row["end_date"],
            "day_of_year": int(row["day_of_year"]),
            "source_url": row["url"],
            "source_file": source.relative_to(data_root).as_posix(),
            "source_size_bytes": len(data),
            "source_md5": row["content_md5_hex"],
            "source_sha256": source_sha256,
            "sample_sha256": sample_sha256,
            **stats,
        })
        print(
            f"built item={item_id} tile={row['tile']} doy={row['day_of_year']} values={VALUES} "
            f"fill={stats['fill_fraction']:.4f} valid=[{stats['valid_min']},{stats['valid_max']}] "
            f"distinct={stats['valid_distinct']}"
        )

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for index_row in index_rows:
            fh.write(json.dumps(index_row, sort_keys=True) + "\n")

    total_bytes = sum(int(r["sample_size_bytes"]) for r in index_rows)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "tiles": sorted({str(r["modis_tile"]) for r in index_rows}),
        "continents": dict(Counter(str(r["continent"]) for r in index_rows)),
        "primary_values": VALUES * len(index_rows),
        "primary_sample_bytes": total_bytes,
        "fill_count": sum(int(r["fill_count"]) for r in index_rows),
        "max_fill_fraction": max(float(r["fill_fraction"]) for r in index_rows),
        "valid_min": min(int(r["valid_min"]) for r in index_rows),
        "valid_max": max(int(r["valid_max"]) for r in index_rows),
        "min_valid_distinct": min(int(r["valid_distinct"]) for r in index_rows),
        "samples_detail": [
            {k: r[k] for k in ("item_id", "modis_tile", "day_of_year", "fill_fraction", "valid_min",
                               "valid_max", "valid_distinct", "sample_sha256", "source_sha256")}
            for r in index_rows
        ],
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built dataset={DATASET_ID} samples={len(index_rows)} bytes={total_bytes} "
          f"max_fill={summary['max_fill_fraction']:.4f} valid=[{summary['valid_min']},{summary['valid_max']}]")


if __name__ == "__main__":
    main()
