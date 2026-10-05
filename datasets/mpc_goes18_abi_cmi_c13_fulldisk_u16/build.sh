#!/usr/bin/env bash
# Decode the twelve pinned GOES-18 CMI_C13 full-disk COGs (local files only)
# into raw little-endian uint16 5424x5424 grids, one per full-disk scan.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_goes18_abi_cmi_c13_fulldisk_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
from __future__ import annotations

import array
import base64
import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
import goes_cog  # noqa: E402

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "goes18_abi_cmi_c13_fulldisk_bt_code_u16"
WIDTH = HEIGHT = 5424
VALUES = WIDTH * HEIGHT
SAMPLE_BYTES = VALUES * 2
EXPECTED_SAMPLES = 12
FILL = 65535
MAX_CODE = 4095
SCALE = 0.06145332
OFFSET = 89.620003
# Degeneracy bounds shared with verify.sh.
FILL_FRACTION_RANGE = (0.15, 0.35)
MIN_DISTINCT_CODES = 1000
MEDIAN_BT_RANGE_K = (200.0, 305.0)
NATURAL_RECORD_KIND = "complete_goes18_abi_mode6_full_disk_band13_scan"
SOURCE_FORMAT = "cloud_optimized_geotiff_export_of_noaa_abi_l2_mcmipf_netcdf4"
SOURCE_FIELD = "CMI_C13"

data_root = Path(os.environ["DATA_ROOT"])
download_dir = data_root / "downloads" / DATASET_ID
cog_dir = download_dir / "cogs"
plan_path = download_dir / "download_plan.tsv"
filter_dir = data_root / "filtered" / DATASET_ID
index_dir = data_root / "index" / DATASET_ID
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def code_stats(raw: bytes) -> dict:
    values = array.array("H")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    hist = Counter(values)
    bad = sorted(v for v in hist if v > MAX_CODE and v != FILL)
    if bad:
        raise SystemExit(f"codes outside 0..{MAX_CODE} and != {FILL}: {bad[:10]}")
    fill = hist.get(FILL, 0)
    valid = VALUES - fill
    codes = sorted(v for v in hist if v != FILL)
    if not codes:
        raise SystemExit("no valid codes")
    half = (valid + 1) // 2
    running = 0
    median_code = codes[-1]
    for code in codes:
        running += hist[code]
        if running >= half:
            median_code = code
            break
    total = sum(code * hist[code] for code in codes)
    corners = [values[0], values[WIDTH - 1], values[(HEIGHT - 1) * WIDTH], values[VALUES - 1]]
    centre = values[(HEIGHT // 2) * WIDTH + WIDTH // 2]
    return {
        "fill_count": fill,
        "valid_count": valid,
        "fill_fraction": fill / VALUES,
        "valid_code_min": codes[0],
        "valid_code_max": codes[-1],
        "valid_code_median": median_code,
        "valid_code_mean": total / valid,
        "distinct_valid_codes": len(codes),
        "corner_codes": corners,
        "centre_code": centre,
        "histogram": {str(code): hist[code] for code in sorted(hist)},
    }


def check_stats(name: str, stats: dict) -> None:
    lo, hi = FILL_FRACTION_RANGE
    if not lo <= stats["fill_fraction"] <= hi:
        raise SystemExit(f"{name}: fill fraction {stats['fill_fraction']:.4f} outside {FILL_FRACTION_RANGE}")
    if any(code != FILL for code in stats["corner_codes"]):
        raise SystemExit(f"{name}: off-disk corners are not fill: {stats['corner_codes']}")
    if stats["centre_code"] == FILL:
        raise SystemExit(f"{name}: sub-satellite centre pixel is fill")
    if stats["distinct_valid_codes"] < MIN_DISTINCT_CODES:
        raise SystemExit(f"{name}: only {stats['distinct_valid_codes']} distinct valid codes")
    median_bt = OFFSET + SCALE * stats["valid_code_median"]
    if not MEDIAN_BT_RANGE_K[0] <= median_bt <= MEDIAN_BT_RANGE_K[1]:
        raise SystemExit(f"{name}: median brightness temperature {median_bt:.2f} K implausible")


if not plan_path.is_file():
    raise SystemExit(f"missing download plan; run download.sh first: {plan_path}")
with plan_path.open(encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
if len(plan) != EXPECTED_SAMPLES:
    raise SystemExit(f"plan rows={len(plan)} expected={EXPECTED_SAMPLES}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict] = []
source_rows: list[dict] = []
seen_digests: set[str] = set()
for row in sorted(plan, key=lambda r: r["scan_start_utc"]):
    netcdf = row["source_netcdf"]
    source = cog_dir / (netcdf[:-3] + "_CMI_C13.tif")
    if not source.is_file():
        raise SystemExit(f"missing source COG: {source}")
    data = source.read_bytes()
    if len(data) != int(row["size_bytes"]):
        raise SystemExit(f"{source.name}: size {len(data)} != pinned {row['size_bytes']}")
    md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
    if md5 != row["content_md5_b64"]:
        raise SystemExit(f"{source.name}: md5 {md5} != pinned {row['content_md5_b64']}")
    try:
        header = goes_cog.validate(data, netcdf)
        raster = goes_cog.decode_primary(data, goes_cog.EXPECTED_PRIMARY, goes_cog.EXPECTED_IFD_COUNT)
    except goes_cog.CogError as exc:
        raise SystemExit(f"{source.name}: {exc}")
    del data
    if len(raster) != SAMPLE_BYTES:
        raise SystemExit(f"{source.name}: decoded {len(raster)} bytes, expected {SAMPLE_BYTES}")
    stats = code_stats(raster)
    check_stats(source.name, stats)
    digest = hashlib.sha256(raster).hexdigest()
    if digest in seen_digests:
        raise SystemExit(f"{source.name}: duplicate raster content")
    seen_digests.add(digest)

    stamp = row["scan_start_utc"][:16].replace(":", "")
    out = out_dir / f"goes18_c13_fulldisk_{stamp}Z_5424x5424.bin"
    out.write_bytes(raster)
    meta = header["metadata"]
    bt = lambda code: round(OFFSET + SCALE * code, 3)  # noqa: E731 (documentation only)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": SAMPLE_BYTES,
        "value_count": VALUES,
        "sample_format": "raw homogeneous uint16 raster, row-major (north row first, west column first)",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["fixed_grid_y", "fixed_grid_x"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_format": SOURCE_FORMAT,
        "source_field": SOURCE_FIELD,
        "month": row["month"],
        "scan_start_utc": row["scan_start_utc"],
        "scan_end_utc": row["scan_end_utc"],
        "stac_item_id": row["item_id"],
        "source_netcdf": netcdf,
        "source_url": row["url"],
        "source_file": rel(source),
        "source_size_bytes": int(row["size_bytes"]),
        "source_content_md5_b64": row["content_md5_b64"],
        "packing_scale_factor": float(meta["scale_factor"]),
        "packing_add_offset": float(meta["add_offset"]),
        "packing_units": meta["units"],
        "packing_note": "brightness_temperature_K = add_offset + scale_factor * code; NOT applied",
        "valid_range": [0, MAX_CODE],
        "fill_value": FILL,
        "fill_count": stats["fill_count"],
        "valid_count": stats["valid_count"],
        "fill_fraction": round(stats["fill_fraction"], 6),
        "valid_code_min": stats["valid_code_min"],
        "valid_code_max": stats["valid_code_max"],
        "valid_code_median": stats["valid_code_median"],
        "distinct_valid_codes": stats["distinct_valid_codes"],
        "min_value_stored": stats["valid_code_min"],
        "max_value_stored": FILL if stats["fill_count"] else stats["valid_code_max"],
        "brightness_temperature_k_min_max_median": [bt(stats["valid_code_min"]), bt(stats["valid_code_max"]), bt(stats["valid_code_median"])],
        "sha256": digest,
    })
    source_rows.append({
        "month": row["month"],
        "stac_item_id": row["item_id"],
        "source_netcdf": netcdf,
        "tiff_structure": header["structure"],
        "gdal_metadata": meta,
        "fill_count": stats["fill_count"],
        "distinct_valid_codes": stats["distinct_valid_codes"],
        "valid_code_mean": round(stats["valid_code_mean"], 4),
        "histogram": stats["histogram"],
        "sha256": digest,
    })
    print(
        f"built month={row['month']} item={row['item_id']} fill={stats['fill_fraction']:.4f} "
        f"codes={stats['valid_code_min']}..{stats['valid_code_max']} median={stats['valid_code_median']} "
        f"distinct={stats['distinct_valid_codes']} bt_median_K={bt(stats['valid_code_median'])} sha256={digest[:16]}"
    )
    del raster

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for index_row in index_rows:
        fh.write(json.dumps(index_row, sort_keys=True) + "\n")
total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
stats_doc = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "primary_values": sum(r["value_count"] for r in index_rows),
    "primary_sample_bytes": total_bytes,
    "fill_count_total": sum(r["fill_count"] for r in index_rows),
    "sources": source_rows,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(index_rows)} values={stats_doc['primary_values']} bytes={total_bytes}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
