#!/usr/bin/env bash
# Decode the downloaded ASTER L1T TIR COGs (local files only) into raw
# little-endian uint16 rasters, one sample per scene, in source order:
# rows north->south, columns west->east, 5 band values per pixel (10..14).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_aster_l1t_tir_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1

python3 "$RECIPE_DIR/scripts/aster_tir_cog.py" selftest

python3 - <<'PY'
from __future__ import annotations

import array
import base64
import csv
import hashlib
import json
import math
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
import aster_tir_cog as cog  # noqa: E402

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "aster_l1t_tir_radiance_dn_u16"
BANDS = 5
FILL = 0
MAX_DN = 4095
BAND_NAMES = cog.BAND_NAMES
BAND_CENTER_UM = [8.291, 8.634, 9.075, 10.657, 11.318]
# ASTER User Handbook unit-conversion coefficients (W m-2 sr-1 um-1 per DN);
# radiance = (DN - 1) * UCC. Documentation only, never applied.
UCC = [0.006822, 0.006780, 0.006590, 0.005693, 0.005225]
NATURAL_RECORD_KIND = "complete_aster_l1t_scene_tir_swath_raster"
SOURCE_FORMAT = "planetary_computer_cloud_optimized_geotiff_aster_l1t_v003_tir"
SOURCE_FIELD = "TIR_Swath ImageData10..ImageData14 (asset TIR)"
# Degeneracy / decode-correctness bounds shared with verify.sh.
MIN_SCENES = 40
FILL_FRACTION_RANGE = (0.05, 0.80)
MIN_VALID_PER_BAND = 50_000
MIN_DISTINCT_PER_BAND = 64
MIN_MASK_AGREEMENT = 0.98
MIN_CORR_B13_B14 = 0.5
MAX_COHERENCE_B13 = 0.75

data_root = Path(os.environ["DATA_ROOT"])
download_dir = data_root / "downloads" / DATASET_ID
raster_dir = download_dir / "tir"
plan_path = download_dir / "download_plan.tsv"
receipts_path = download_dir / "download_receipts.tsv"
filter_dir = data_root / "filtered" / DATASET_ID
index_dir = data_root / "index" / DATASET_ID
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def scene_stats(raw: bytes, width: int, height: int) -> dict:
    values = array.array("H")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != width * height * BANDS:
        raise SystemExit("decoded raster length mismatch")
    top = max(values)
    if top > MAX_DN:
        raise SystemExit(f"value {top} above the 12-bit DN range")
    bands = [values[b::BANDS] for b in range(BANDS)]
    per_band = []
    exact_std = []
    for b, arr in enumerate(bands):
        hist = Counter(arr)
        zeros = hist.pop(FILL, 0)
        valid = len(arr) - zeros
        if valid == 0:
            raise SystemExit(f"band {BAND_NAMES[b]} has no valid pixels")
        mean = sum(k * c for k, c in hist.items()) / valid
        var = sum(c * (k - mean) ** 2 for k, c in hist.items()) / valid
        exact_std.append(math.sqrt(var))
        per_band.append({
            "band": BAND_NAMES[b],
            "fill_count": zeros,
            "valid_count": valid,
            "min": min(hist),
            "max": max(hist),
            "mean": round(mean, 4),
            "std": round(math.sqrt(var), 4),
            "distinct": len(hist),
        })
    pixels = width * height
    mixed = sum(1 for p in zip(*bands) if 0 in p and any(p))
    # Pearson correlation of bands 13 and 14 over pixels valid in both.
    n = sx = sy = sxx = syy = sxy = 0
    for x, y in zip(bands[3], bands[4]):
        if x and y:
            n += 1
            sx += x
            sy += y
            sxx += x * x
            syy += y * y
            sxy += x * y
    cov = sxy - sx * sy / n
    corr = cov / math.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n)) if n > 1 else 0.0
    # Spatial coherence of band 13: mean |horizontal neighbour difference| / std.
    b13 = bands[3]
    diff_sum = pairs = 0
    for row in range(height):
        line = b13[row * width:(row + 1) * width]
        for a, c in zip(line, line[1:]):
            if a and c:
                diff_sum += abs(a - c)
                pairs += 1
    std13 = exact_std[3]
    coherence = (diff_sum / pairs) / std13 if pairs and std13 > 0 else float("inf")
    fill_total = sum(b["fill_count"] for b in per_band)
    return {
        "per_band": per_band,
        "fill_count": fill_total,
        "fill_fraction": fill_total / len(values),
        "mixed_fill_pixels": mixed,
        "mask_agreement": 1.0 - mixed / pixels,
        "corr_b13_b14": corr,
        "coherence_b13": coherence,
        "valid_min": min(b["min"] for b in per_band),
        "valid_max": max(b["max"] for b in per_band),
    }


def check_stats(name: str, s: dict) -> None:
    lo, hi = FILL_FRACTION_RANGE
    if not lo <= s["fill_fraction"] <= hi:
        raise SystemExit(f"{name}: fill fraction {s['fill_fraction']:.4f} outside {FILL_FRACTION_RANGE}")
    for b in s["per_band"]:
        if b["valid_count"] < MIN_VALID_PER_BAND:
            raise SystemExit(f"{name}: {b['band']} has only {b['valid_count']} valid pixels")
        if b["distinct"] < MIN_DISTINCT_PER_BAND or b["max"] <= b["min"]:
            raise SystemExit(f"{name}: {b['band']} degenerate ({b['distinct']} distinct DN)")
    if s["mask_agreement"] < MIN_MASK_AGREEMENT:
        raise SystemExit(f"{name}: band fill masks disagree (agreement {s['mask_agreement']:.4f})")
    if s["corr_b13_b14"] < MIN_CORR_B13_B14:
        raise SystemExit(f"{name}: band 13/14 correlation {s['corr_b13_b14']:.3f} too low (bad decode?)")
    if s["coherence_b13"] > MAX_COHERENCE_B13:
        raise SystemExit(f"{name}: band 13 spatial coherence {s['coherence_b13']:.3f} too high (bad decode?)")


for required in (plan_path, receipts_path):
    if not required.is_file():
        raise SystemExit(f"missing {required}; run download.sh first")
# Rights evidence captured by download.sh: the USGS grant page and the MPC
# collection JSON must both have check=ok receipts matching the saved bytes.
rights_receipts_path = download_dir / "rights_receipts.tsv"
if not rights_receipts_path.is_file():
    raise SystemExit(f"missing {rights_receipts_path}; run download.sh (rights evidence)")
with rights_receipts_path.open(encoding="utf-8", newline="") as fh:
    rights_rows = list(csv.DictReader(fh, delimiter="\t"))
rights_by_file = {r["file"]: r for r in rights_rows}
for name in ("usgs_data_policy.html", "mpc_collection_aster-l1t.json"):
    receipt = rights_by_file.get(name)
    if receipt is None or receipt.get("check") != "ok":
        raise SystemExit(f"rights receipt for {name} missing or not ok: {receipt}")
    saved = download_dir / "rights" / name
    if not saved.is_file() or saved.stat().st_size != int(receipt["size_bytes"]) \
            or hashlib.sha256(saved.read_bytes()).hexdigest() != receipt["sha256"]:
        raise SystemExit(f"saved rights file {saved} does not match its receipt")
    print(f"rights ok file={name} effective_url={receipt['effective_url']} sha256={receipt['sha256'][:16]}")

pinned_path = Path(os.environ["RECIPE_DIR"]) / "sources.tsv"
if not pinned_path.is_file() or plan_path.read_bytes() != pinned_path.read_bytes():
    raise SystemExit(f"{plan_path} differs from the pinned {pinned_path}; rerun download.sh")
with plan_path.open(encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
with receipts_path.open(encoding="utf-8", newline="") as fh:
    receipts = {r["item_id"]: r for r in csv.DictReader(fh, delimiter="\t")}
if len(plan) < MIN_SCENES:
    raise SystemExit(f"plan has {len(plan)} scenes, minimum {MIN_SCENES}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict] = []
scene_rows: list[dict] = []
digests: set[str] = set()
gdal_items_example = None
for row in sorted(plan, key=lambda r: (r["region_id"], r["window"])):
    item_id = row["item_id"]
    source = raster_dir / row["url"].rsplit("/", 1)[1]
    if not source.is_file():
        raise SystemExit(f"missing source COG {source}")
    data = source.read_bytes()
    if len(data) != int(row["size_bytes"]):
        raise SystemExit(f"{source.name}: size {len(data)} != plan {row['size_bytes']}")
    if row["content_md5_b64"] != "NA":
        md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
        if md5 != row["content_md5_b64"]:
            raise SystemExit(f"{source.name}: md5 {md5} != plan {row['content_md5_b64']}")
    source_sha = hashlib.sha256(data).hexdigest()
    if receipts.get(item_id, {}).get("sha256") != source_sha:
        raise SystemExit(f"{source.name}: sha256 differs from download receipt")
    try:
        info = cog.structure(data)
        raster = cog.decode(data, info)
    except cog.CogError as exc:
        raise SystemExit(f"{source.name}: {exc}")
    if gdal_items_example is None:
        tags = cog.parse_ifds(data)[0]
        gdal_items_example = {"item_id": item_id, "gdal_metadata_xml": tags.get(42112)}
    del data
    width, height = info["width"], info["height"]
    stats = scene_stats(raster, width, height)
    check_stats(source.name, stats)
    digest = hashlib.sha256(raster).hexdigest()
    if digest in digests:
        raise SystemExit(f"{source.name}: duplicate raster content")
    digests.add(digest)
    out = out_dir / f"{item_id}__{row['region_id']}_{row['window']}.bin"
    out.write_bytes(raster)
    value_count = width * height * BANDS
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(raster),
        "value_count": value_count,
        "sample_format": "raw homogeneous uint16 raster, row-major, pixel-interleaved (source TIFF order)",
        "sample_rank": 3,
        "sample_shape": [height, width, BANDS],
        "sample_axes": ["row_north_to_south", "column_west_to_east", "tir_band"],
        "band_order": BAND_NAMES,
        "band_center_wavelength_um": BAND_CENTER_UM,
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_format": SOURCE_FORMAT,
        "source_field": SOURCE_FIELD,
        "stac_item_id": item_id,
        "datetime": row["datetime"],
        "region_id": row["region_id"],
        "region_label": row["region_label"],
        "window": row["window"],
        "year": int(row["year"]),
        "eo_cloud_cover": float(row["cloud_cover"]),
        "view_sun_elevation": float(row["sun_elevation"]),
        "view_sun_azimuth": None if row["sun_azimuth"] == "NA" else float(row["sun_azimuth"]),
        "source_url": row["url"],
        "source_file": rel(source),
        "source_size_bytes": int(row["size_bytes"]),
        "source_content_md5_b64": row["content_md5_b64"],
        "source_sha256": source_sha,
        "tiff_predictor": info["predictor"],
        "tiff_tile": [info["tile_height"], info["tile_width"]],
        "tiff_sparse_tiles": info["sparse_tiles"],
        "gdal_nodata": info["gdal_nodata"],
        "fill_value": FILL,
        "fill_count": stats["fill_count"],
        "fill_fraction": round(stats["fill_fraction"], 6),
        "valid_dn_range": [1, MAX_DN],
        "per_band": stats["per_band"],
        "valid_min": stats["valid_min"],
        "valid_max": stats["valid_max"],
        "min_value_stored": FILL if stats["fill_count"] else stats["valid_min"],
        "max_value_stored": stats["valid_max"],
        "mixed_fill_pixels": stats["mixed_fill_pixels"],
        "mask_agreement": round(stats["mask_agreement"], 6),
        "corr_b13_b14": round(stats["corr_b13_b14"], 6),
        "coherence_b13": round(stats["coherence_b13"], 6),
        "unit_conversion_coefficients": UCC,
        "radiance_note": "radiance_W_m-2_sr-1_um-1 = (DN - 1) * UCC[band] (ASTER User Handbook); NOT applied",
        "sha256": digest,
    })
    scene_rows.append({k: index_rows[-1][k] for k in (
        "stac_item_id", "region_id", "window", "datetime", "sample_shape", "fill_fraction",
        "valid_min", "valid_max", "corr_b13_b14", "coherence_b13", "mask_agreement", "sha256")})
    bands_txt = " ".join(f"{b['band'][-2:]}:{b['min']}..{b['max']}/{b['distinct']}" for b in stats["per_band"])
    print(f"built {item_id} region={row['region_id']} window={row['window']} shape={height}x{width}x5 "
          f"fill={stats['fill_fraction']:.3f} corr1314={stats['corr_b13_b14']:.3f} coh13={stats['coherence_b13']:.3f} "
          f"mask={stats['mask_agreement']:.4f} bands[min..max/distinct]={bands_txt}")
    del raster

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in index_rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes {total_bytes} exceed 1e9")
stats_doc = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "regions": len({r["region_id"] for r in index_rows}),
    "primary_values": sum(r["value_count"] for r in index_rows),
    "primary_sample_bytes": total_bytes,
    "fill_count_total": sum(r["fill_count"] for r in index_rows),
    "valid_dn_min": min(r["valid_min"] for r in index_rows),
    "valid_dn_max": max(r["valid_max"] for r in index_rows),
    "gdal_metadata_example": gdal_items_example,
    "rights_receipts": rights_rows,
    "scenes": scene_rows,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(index_rows)} regions={stats_doc['regions']} "
      f"values={stats_doc['primary_values']} bytes={total_bytes} dn={stats_doc['valid_dn_min']}..{stats_doc['valid_dn_max']}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
