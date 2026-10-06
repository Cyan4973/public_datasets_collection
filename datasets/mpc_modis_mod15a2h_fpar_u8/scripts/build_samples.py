#!/usr/bin/env python3
"""Build step for mpc_modis_mod15a2h_fpar_u8 (local files only).

Decodes each pinned MOD15A2H.061 Fpar_500m COG's primary 2400x2400 uint8
grid and writes it unchanged as raw uint8 in row-major order, one sample per
(tile, 8-day composite). Writes the sample index and ingest stats.
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
import mod15a2h_cog as cog  # noqa: E402

DATASET_ID = "mpc_modis_mod15a2h_fpar_u8"
SERIES_ID = "modis_mod15a2h_8day_fpar_u8"
SOURCE_FORMAT = "cloud_optimized_geotiff"
SOURCE_FIELD = "Fpar_500m"
NATURAL_RECORD_KIND = "complete_mod15a2h_8_day_fpar_tile"
SAMPLE_FORMAT = "raw homogeneous uint8 FPAR grid (0..100 = FPAR x 100; 248..255 source fill classes)"
SAMPLE_GEOMETRY = "2400x2400_modis_sinusoidal_tile"
EXPECTED_SAMPLES = 96
EXPECTED_TILES = 24
EXPECTED_DOYS = {"049", "137", "225", "313"}
VALUES = cog.WIDTH * cog.HEIGHT
MIN_VALID_FRACTION = 0.70
MIN_VALID_DISTINCT = 50


def fpar_stats(payload: bytes) -> dict[str, object]:
    if len(payload) != VALUES:
        raise SystemExit(f"decoded value count {len(payload)} != {VALUES}")
    hist = [0] * 256
    for value, count in Counter(payload).items():
        hist[value] = count
    illegal = [v for v in range(cog.VALID_MAX + 1, 256) if hist[v] and v not in cog.FILL_CLASSES]
    if illegal:
        raise SystemExit(f"values outside 0..100 and fill classes 248..255: {illegal[:10]}")
    valid_count = sum(hist[:cog.VALID_MAX + 1])
    if valid_count == 0:
        raise SystemExit("sample has no valid FPAR values")
    valid_values = [v for v in range(cog.VALID_MAX + 1) if hist[v]]
    present = [v for v in range(256) if hist[v]]
    return {
        "valid_count": valid_count,
        "valid_fraction": valid_count / VALUES,
        "valid_min": valid_values[0],
        "valid_max": valid_values[-1],
        "valid_sum": sum(v * hist[v] for v in valid_values),
        "valid_distinct": len(valid_values),
        "fill_count": VALUES - valid_count,
        "fill_class_counts": {str(c): hist[c] for c in cog.FILL_CLASSES},
        "min": present[0],
        "max": present[-1],
        "sum": sum(v * hist[v] for v in present),
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
        raise SystemExit("plan does not cover 24 tiles x DOY 049/137/225/313")
    if {(row["tile"], row["day_of_year"]) for row in plan} != {
            (t, d) for t in {row["tile"] for row in plan} for d in EXPECTED_DOYS}:
        raise SystemExit("plan is not a complete tile x composite grid")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for row in plan:
        item_id = row["item_id"]
        source = raster_dir / f"{item_id}_Fpar_500m.tif"
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
            payload = cog.decode_primary(data, item_id, row["tile"], row["start_date"], row["end_date"])
        except cog.CogError as exc:
            raise SystemExit(f"decode failed item={item_id}: {exc}")
        meta = cog.granule_metadata(data)
        provenance = {
            "ndays_composited": int(meta["NDAYS_COMPOSITED"]),
            "qa_percent_main_method": int(meta.get("QAPERCENTMAINMETHOD", "-1")),
            "qa_percent_good_fpar": int(meta.get("QAPERCENTGOODFPAR", "-1")),
            "production_datetime": meta.get("PRODUCTIONDATETIME", ""),
        }
        stats = fpar_stats(payload)
        if stats["valid_fraction"] < MIN_VALID_FRACTION:
            raise SystemExit(f"valid fraction {stats['valid_fraction']:.4f} < {MIN_VALID_FRACTION} item={item_id}")
        if stats["valid_distinct"] < MIN_VALID_DISTINCT:
            raise SystemExit(f"degenerate FPAR grid item={item_id} distinct={stats['valid_distinct']}")
        sample_sha256 = hashlib.sha256(payload).hexdigest()
        if sample_sha256 in seen_hashes:
            raise SystemExit(f"duplicate decoded grid item={item_id}")
        seen_hashes.add(sample_sha256)

        name = f"{row['tile']}_A2024{row['day_of_year']}_{row['area']}_2400x2400.u8.bin"
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
            "scale_factor": 0.01,
            "fill_value": cog.NODATA,
            "fill_classes": list(cog.FILL_CLASSES),
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
            **provenance,
            **stats,
        })
        classes = " ".join(f"{c}:{stats['fill_class_counts'][str(c)] / VALUES:.4f}" for c in cog.FILL_CLASSES)
        print(
            f"built item={item_id} tile={row['tile']} doy={row['day_of_year']} values={VALUES} "
            f"valid={stats['valid_fraction']:.4f} range=[{stats['valid_min']},{stats['valid_max']}] "
            f"distinct={stats['valid_distinct']} fill_classes {classes}"
        )

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for index_row in index_rows:
            fh.write(json.dumps(index_row, sort_keys=True) + "\n")

    total_bytes = sum(int(r["sample_size_bytes"]) for r in index_rows)
    class_totals = {str(c): sum(int(r["fill_class_counts"][str(c)]) for r in index_rows) for c in cog.FILL_CLASSES}
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "tiles": sorted({str(r["modis_tile"]) for r in index_rows}),
        "continents": dict(Counter(str(r["continent"]) for r in index_rows)),
        "primary_values": VALUES * len(index_rows),
        "primary_sample_bytes": total_bytes,
        "valid_count": sum(int(r["valid_count"]) for r in index_rows),
        "fill_count": sum(int(r["fill_count"]) for r in index_rows),
        "fill_class_totals": class_totals,
        "min_valid_fraction": min(float(r["valid_fraction"]) for r in index_rows),
        "max_valid_fraction": max(float(r["valid_fraction"]) for r in index_rows),
        "valid_min": min(int(r["valid_min"]) for r in index_rows),
        "valid_max": max(int(r["valid_max"]) for r in index_rows),
        "min_valid_distinct": min(int(r["valid_distinct"]) for r in index_rows),
        "samples_detail": [
            {k: r[k] for k in ("item_id", "modis_tile", "day_of_year", "ndays_composited", "qa_percent_main_method",
                               "valid_fraction", "fill_class_counts",
                               "valid_min", "valid_max", "valid_distinct", "sample_sha256", "source_sha256")}
            for r in index_rows
        ],
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built dataset={DATASET_ID} samples={len(index_rows)} bytes={total_bytes} "
          f"valid_fraction=[{summary['min_valid_fraction']:.4f},{summary['max_valid_fraction']:.4f}] "
          f"fill_class_totals={class_totals}")


if __name__ == "__main__":
    main()
