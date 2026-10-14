#!/usr/bin/env python3
"""Build SNODAS masked SWE int16 samples from locally downloaded tar members.

Usage: python3 -I build_samples.py RECIPE_DIR DATA_ROOT
"""
from __future__ import annotations

import array
import csv
import gzip
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

DATASET_ID = "nsidc_snodas_masked_swe_i16"
SERIES_ID = "snodas_swe_mm_i16"
COLS, ROWS = 6935, 3351
VALUES = COLS * ROWS
NODATA = -9999
SATURATION = 32767
SOURCE_FORMAT = "nohrsc_gisrs_raster_v1_1_gzip_big_endian_int16"
SOURCE_FIELD = "SNODAS product 1034 snow water equivalent (total of snow layers), meters/1000, us_ssmv11034tS__T0001TTNATS<date>05HP001.dat"
NATURAL_RECORD = "snodas_daily_masked_conus_swe_grid"

recipe_dir = Path(sys.argv[1])
data_root = Path(sys.argv[2])
sys.path.insert(0, str(recipe_dir / "scripts"))
from check_member import check_txt_fields, parse_txt_header  # noqa: E402

member_dir = data_root / "downloads" / DATASET_ID / "members"
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
index_dir = data_root / "index" / DATASET_ID
filter_dir = data_root / "filtered" / DATASET_ID
if sys.byteorder != "little":
    raise SystemExit("this builder assumes a little-endian host")

with (recipe_dir / "plan.tsv").open(encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
if len(plan) != 20:
    raise SystemExit(f"expected 20 plan rows, got {len(plan)}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
mask_hashes = set()
for item in plan:
    date = item["date"]
    txt = member_dir / item["txt_member"]
    dat = member_dir / item["dat_member"]
    if not txt.is_file() or not dat.is_file():
        raise SystemExit(f"missing local member for {date}; run download.sh first")
    with gzip.open(txt, "rb") as fh:
        check_txt_fields(parse_txt_header(fh.read()), date)
    with gzip.open(dat, "rb") as fh:
        raw = fh.read()
    if len(raw) != VALUES * 2:
        raise SystemExit(f"{date}: raster bytes {len(raw)} expected {VALUES * 2}")
    grid = array.array("h")
    grid.frombytes(raw)
    grid.byteswap()  # source is big-endian >i2; host/output little-endian
    hist = Counter(grid)
    bad = [v for v in hist if v < 0 and v != NODATA]
    if bad:
        raise SystemExit(f"{date}: unexpected negative values {sorted(bad)[:10]}")
    nodata = hist.get(NODATA, 0)
    zeros = hist.get(0, 0)
    valid = VALUES - nodata
    positive = valid - zeros
    valid_values = [v for v in hist if v != NODATA]
    if positive < VALUES // 100 or len(hist) < 500 or nodata * 2 >= VALUES:
        raise SystemExit(f"{date}: degenerate grid nodata={nodata} zeros={zeros} distinct={len(hist)}")
    mask_sha = hashlib.sha256(bytes(map(NODATA.__eq__, grid))).hexdigest()
    mask_hashes.add(mask_sha)
    payload = grid.tobytes()
    out = out_dir / f"snodas_swe_{date}_masked_3351x6935.bin"
    out.write_bytes(payload)
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": VALUES,
        "sample_format": "raw homogeneous int16 raster (row-major, north-to-south rows, west-to-east columns)",
        "sample_rank": 2,
        "sample_shape": [ROWS, COLS],
        "natural_record_kind": NATURAL_RECORD,
        "source_format": SOURCE_FORMAT,
        "source_field": SOURCE_FIELD,
        "source_member": item["dat_member"],
        "source_tar_url": item["tar_url"],
        "analysis_date_utc": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "units": "mm (meters/1000)",
        "nodata_value": NODATA,
        "nodata_count": nodata,
        "nodata_fraction": round(nodata / VALUES, 6),
        "zero_count": zeros,
        "zero_fraction": round(zeros / VALUES, 6),
        "zero_fraction_of_valid": round(zeros / valid, 6),
        "positive_count": positive,
        "saturated_32767_count": hist.get(SATURATION, 0),
        "distinct_values": len(hist),
        "min_valid": min(valid_values),
        "max_valid": max(valid_values),
        "nodata_mask_sha256": mask_sha,
        "sha256": hashlib.sha256(payload).hexdigest(),
    })
    print(f"built date={date} nodata={nodata / VALUES:.4f} zero={zeros / VALUES:.4f} "
          f"positive={positive / VALUES:.4f} sat32767={hist.get(SATURATION, 0)} "
          f"distinct={len(hist)} max={max(valid_values)}", flush=True)

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

total_bytes = sum(r["sample_size_bytes"] for r in rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(rows),
    "primary_values": sum(r["value_count"] for r in rows),
    "primary_sample_bytes": total_bytes,
    "distinct_nodata_masks": len(mask_hashes),
    "nodata_mask_constant": len(mask_hashes) == 1,
    "saturated_32767_total": sum(r["saturated_32767_count"] for r in rows),
    "per_date": [{k: r[k] for k in ("analysis_date_utc", "nodata_fraction", "zero_fraction",
                                    "zero_fraction_of_valid", "positive_count",
                                    "saturated_32767_count", "distinct_values", "max_valid")}
                 for r in rows],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(rows)} bytes={total_bytes} "
      f"distinct_nodata_masks={len(mask_hashes)} saturated_32767_total={stats['saturated_32767_total']}")
