#!/usr/bin/env python3
"""Build step for mpc_modis_mod10a1_ndsi_snow_cover_u8 (local files only).

Decodes each pinned MOD10A1.061 NDSI_Snow_Cover COG's primary 2400x2400
uint8 grid and writes it unchanged (NDSI snow cover 0..100 and the product's
flag codes, exactly as stored) in row-major order, one sample per
(tile, day). Writes the sample index and ingest stats.
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
import mod10a1_cog as cog  # noqa: E402

DATASET_ID = "mpc_modis_mod10a1_ndsi_snow_cover_u8"
SERIES_ID = "modis_mod10a1_daily_ndsi_snow_cover_u8"
SOURCE_FORMAT = "cloud_optimized_geotiff"
SOURCE_FIELD = "NDSI_Snow_Cover"
NATURAL_RECORD_KIND = "complete_mod10a1_daily_ndsi_snow_cover_tile"
SAMPLE_FORMAT = "raw homogeneous uint8 NDSI snow cover grid (0..100 NDSI x 100; flags 200-255 as stored)"
SAMPLE_GEOMETRY = "2400x2400_modis_sinusoidal_tile"
EXPECTED_SAMPLES = 70
VALUES = cog.WIDTH * cog.HEIGHT
MIN_VALID_FRACTION = 0.40
MIN_SNOW_FRACTION = 0.02
MIN_VALID_DISTINCT = 20


def class_stats(payload: bytes) -> dict[str, object]:
    if len(payload) != VALUES:
        raise SystemExit(f"decoded value count {len(payload)} != {VALUES}")
    counts = [payload.count(v) for v in range(256)]
    bad = [v for v in range(256) if counts[v] and v not in cog.ALLOWED_VALUES]
    if bad:
        raise SystemExit(f"values outside the documented NDSI_Snow_Cover code set: {bad[:20]}")
    valid = sum(counts[0:101])
    snow = sum(counts[1:101])
    present = [v for v in range(256) if counts[v]]
    stats: dict[str, object] = {
        "valid_count": valid,
        "valid_fraction": round(valid / VALUES, 6),
        "snow_count": snow,
        "snow_fraction": round(snow / VALUES, 6),
        "snow_free_count": counts[0],
        "valid_distinct": sum(1 for v in range(101) if counts[v]),
        "distinct_values": len(present),
        "min": present[0],
        "max": present[-1],
        "sum": sum(v * c for v, c in enumerate(counts)),
        "flag_counts": {name: counts[code] for code, name in sorted(cog.FLAG_CODES.items())},
    }
    snow_values = [v for v in range(1, 101) if counts[v]]
    stats["snow_min"] = snow_values[0] if snow_values else None
    stats["snow_max"] = snow_values[-1] if snow_values else None
    return stats


def main() -> None:
    data_root = Path(os.environ["DATA_ROOT"])
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

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for row in plan:
        item_id = row["item_id"]
        source = raster_dir / f"{item_id}_NDSI_Snow_Cover.tif"
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
            payload = cog.decode_primary(data, item_id, row["tile"], row["date"])
        except cog.CogError as exc:
            raise SystemExit(f"decode failed item={item_id}: {exc}")
        stats = class_stats(payload)
        if stats["valid_fraction"] < MIN_VALID_FRACTION:
            raise SystemExit(f"valid 0..100 fraction {stats['valid_fraction']} < {MIN_VALID_FRACTION} item={item_id}")
        if stats["snow_fraction"] < MIN_SNOW_FRACTION:
            raise SystemExit(f"snow 1..100 fraction {stats['snow_fraction']} < {MIN_SNOW_FRACTION} item={item_id}")
        if stats["valid_distinct"] < MIN_VALID_DISTINCT:
            raise SystemExit(f"degenerate NDSI grid item={item_id} valid_distinct={stats['valid_distinct']}")
        sample_sha256 = hashlib.sha256(payload).hexdigest()
        if sample_sha256 in seen_hashes:
            raise SystemExit(f"duplicate decoded grid item={item_id}")
        seen_hashes.add(sample_sha256)

        year_doy = item_id.split(".")[1]  # e.g. A2024046
        name = f"{row['tile']}_{year_doy}_2400x2400.u8.bin"
        output = out_dir / name
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
            "valid_range": [0, 100],
            "flag_codes": {str(k): v for k, v in sorted(cog.FLAG_CODES.items())},
            "item_id": item_id,
            "modis_tile": row["tile"],
            "tile_center_lat": float(row["center_lat"]),
            "tile_center_lon": float(row["center_lon"]),
            "observation_date": row["date"],
            "day_of_year": int(row["doy"]),
            "production_datetime": row["production_datetime"],
            "est_valid_fraction_overview": float(row["est_valid_fraction"]),
            "hdr_snow_cover_percent": int(row["hdr_snow_cover_percent"]),
            "hdr_cloud_percent": int(row["hdr_cloud_percent"]),
            "source_url": row["url"],
            "source_file": source.relative_to(data_root).as_posix(),
            "source_size_bytes": len(data),
            "source_md5": row["content_md5_hex"],
            "source_sha256": source_sha256,
            "sample_sha256": sample_sha256,
            **stats,
        })
        print(
            f"built item={item_id} tile={row['tile']} date={row['date']} values={VALUES} "
            f"valid={stats['valid_fraction']:.4f} snow={stats['snow_fraction']:.4f} "
            f"cloud={stats['flag_counts']['cloud'] / VALUES:.4f} valid_distinct={stats['valid_distinct']}"
        )

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for index_row in index_rows:
            fh.write(json.dumps(index_row, sort_keys=True) + "\n")

    total_bytes = sum(int(r["sample_size_bytes"]) for r in index_rows)
    flag_totals: Counter = Counter()
    for r in index_rows:
        flag_totals.update(r["flag_counts"])
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "tiles": sorted({str(r["modis_tile"]) for r in index_rows}),
        "dates": sorted({str(r["observation_date"]) for r in index_rows}),
        "primary_values": VALUES * len(index_rows),
        "primary_sample_bytes": total_bytes,
        "valid_count": sum(int(r["valid_count"]) for r in index_rows),
        "snow_count": sum(int(r["snow_count"]) for r in index_rows),
        "flag_counts": dict(sorted(flag_totals.items())),
        "min_valid_fraction": min(float(r["valid_fraction"]) for r in index_rows),
        "max_valid_fraction": max(float(r["valid_fraction"]) for r in index_rows),
        "min_snow_fraction": min(float(r["snow_fraction"]) for r in index_rows),
        "max_snow_fraction": max(float(r["snow_fraction"]) for r in index_rows),
        "min_valid_distinct": min(int(r["valid_distinct"]) for r in index_rows),
        "samples_detail": [
            {k: r[k] for k in ("item_id", "modis_tile", "observation_date", "valid_fraction", "snow_fraction",
                               "est_valid_fraction_overview", "hdr_snow_cover_percent", "hdr_cloud_percent", "valid_distinct",
                               "flag_counts", "sample_sha256", "source_sha256")}
            for r in index_rows
        ],
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built dataset={DATASET_ID} samples={len(index_rows)} bytes={total_bytes} "
          f"valid_fraction=[{summary['min_valid_fraction']:.4f},{summary['max_valid_fraction']:.4f}] "
          f"snow_fraction=[{summary['min_snow_fraction']:.4f},{summary['max_snow_fraction']:.4f}]")


if __name__ == "__main__":
    main()
