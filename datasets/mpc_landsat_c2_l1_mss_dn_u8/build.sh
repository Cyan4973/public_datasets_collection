#!/usr/bin/env bash
# Decode the downloaded Landsat-5 MSS C2 L1TP band COGs (local files only)
# into raw uint8 rasters, one sample per scene band (B1..B4), in source order:
# rows north->south, columns west->east. Zero fill is kept in place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_landsat_c2_l1_mss_dn_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1

python3 "$RECIPE_DIR/scripts/mss_cog.py" selftest

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
import mss_cog as cog  # noqa: E402
import mtl_check  # noqa: E402

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "landsat5_mss_l1tp_dn_u8"
BANDS = [("B1", "green", 0.55), ("B2", "red", 0.65), ("B3", "nir08", 0.75), ("B4", "nir09", 0.95)]
FILL = 0
NATURAL_RECORD_KIND = "landsat_c2_l1_mss_scene_band_raster"
SOURCE_FORMAT = "planetary_computer_cloud_optimized_geotiff_landsat_c2_l1_mss"
SOURCE_FIELD = "MSS band DN, assets green/red/nir08/nir09 (Landsat-5 bands B1..B4)"
# Degeneracy / decode-correctness bounds, mirrored in verify.sh.
EXPECTED_SCENES = 13
FILL_FRACTION_RANGE = (0.05, 0.70)
MIN_VALID_PER_BAND = 1_000_000
MIN_DISTINCT_PER_BAND = 16
MIN_MASK_AGREEMENT = 0.99
MIN_BAND_PAIR_CORR = 0.5      # corr(B1,B2) and corr(B3,B4) over jointly valid pixels
MAX_COHERENCE = 0.6           # mean |horizontal neighbour diff| / std, per band
MAX_SATURATED_FRACTION = 0.6  # DN 255 pixels / valid pixels, per band (bright-desert sanity cap)

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
download_dir = data_root / "downloads" / DATASET_ID
scene_dir = download_dir / "scenes"
plan_path = download_dir / "download_plan.tsv"
receipts_path = download_dir / "download_receipts.tsv"
filter_dir = data_root / "filtered" / DATASET_ID
index_dir = data_root / "index" / DATASET_ID
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def band_stats(raster: bytes, width: int, height: int) -> dict:
    hist = Counter(raster)
    fill = hist.pop(FILL, 0)
    valid = len(raster) - fill
    if valid == 0:
        return {"fill_count": fill, "valid_count": 0}
    mean = sum(k * c for k, c in hist.items()) / valid
    var = sum(c * (k - mean) ** 2 for k, c in hist.items()) / valid
    std = math.sqrt(var)
    total = len(raster)
    entropy = -sum((c / total) * math.log2(c / total) for c in list(hist.values()) + [fill] if c)
    # Horizontal neighbour pairs via a joint histogram of (x[i], x[i+1]) over the
    # flattened raster, minus the height-1 pairs that straddle a row boundary.
    pairs = bytearray(2 * (total - 1))
    pairs[0::2] = raster[:-1]
    pairs[1::2] = raster[1:]
    codes = array.array("H")
    codes.frombytes(bytes(pairs))
    if sys.byteorder != "little":
        codes.byteswap()
    joint = Counter(codes)
    for r in range(1, height):
        a, b = raster[r * width - 1], raster[r * width]
        joint[a | (b << 8)] -= 1
    dsum = dpairs = 0
    for code, c in joint.items():
        a, b = code & 0xFF, code >> 8
        if a and b and c:
            dsum += abs(a - b) * c
            dpairs += c
    coherence = (dsum / dpairs) / std if dpairs and std > 0 else float("inf")
    return {
        "fill_count": fill,
        "valid_count": valid,
        "fill_fraction": fill / total,
        "valid_min": min(hist),
        "valid_max": max(hist),
        "distinct_valid": len(hist),
        "mean": mean,
        "std": std,
        "saturated_255_count": hist.get(255, 0),
        "entropy_bits": entropy,
        "coherence": coherence,
        "neighbour_pairs": dpairs,
    }


def pair_corr(a: bytes, b: bytes) -> float:
    """Pearson correlation of two bands over pixels valid (non-zero) in both."""
    buf = bytearray(2 * len(a))
    buf[0::2] = a
    buf[1::2] = b
    codes = array.array("H")
    codes.frombytes(bytes(buf))
    if sys.byteorder != "little":
        codes.byteswap()
    n = sx = sy = sxx = syy = sxy = 0
    for code, c in Counter(codes).items():
        x, y = code & 0xFF, code >> 8
        if x and y:
            n += c
            sx += x * c
            sy += y * c
            sxx += x * x * c
            syy += y * y * c
            sxy += x * y * c
    if n < 2:
        return 0.0
    den = math.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n))
    return (sxy - sx * sy / n) / den if den > 0 else 0.0


def mask_agreement(rasters: list[bytes]) -> tuple[int, float]:
    """Pixels where some but not all four bands are fill; returns (count, agreement)."""
    combined = 0
    for bit, raster in enumerate(rasters):
        table = bytes([0] + [1 << bit] * 255)
        combined |= int.from_bytes(raster.translate(table), "little")
    n = len(rasters[0])
    mask = combined.to_bytes(n, "little")
    mixed = n - mask.count(0) - mask.count(15)
    return mixed, 1.0 - mixed / n


def check_band(name: str, s: dict) -> None:
    lo, hi = FILL_FRACTION_RANGE
    if s["valid_count"] < MIN_VALID_PER_BAND:
        raise SystemExit(f"{name}: only {s['valid_count']} valid pixels")
    if not lo <= s["fill_fraction"] <= hi:
        raise SystemExit(f"{name}: fill fraction {s['fill_fraction']:.4f} outside {FILL_FRACTION_RANGE}")
    if s["distinct_valid"] < MIN_DISTINCT_PER_BAND or s["valid_max"] <= s["valid_min"]:
        raise SystemExit(f"{name}: degenerate ({s['distinct_valid']} distinct valid DN)")
    if s["coherence"] > MAX_COHERENCE:
        raise SystemExit(f"{name}: spatial coherence {s['coherence']:.3f} > {MAX_COHERENCE} (bad decode?)")
    if s["saturated_255_count"] > MAX_SATURATED_FRACTION * s["valid_count"]:
        raise SystemExit(f"{name}: {s['saturated_255_count']} of {s['valid_count']} valid pixels saturated (> {MAX_SATURATED_FRACTION})")


for required in (plan_path, receipts_path):
    if not required.is_file():
        raise SystemExit(f"missing {required}; run download.sh first")

# Rights evidence captured by download.sh: the MPC collection JSON plus at
# least one grant document must have check=ok receipts matching saved bytes.
rights_receipts_path = download_dir / "rights_receipts.tsv"
if not rights_receipts_path.is_file():
    raise SystemExit(f"missing {rights_receipts_path}; run download.sh (rights evidence)")
with rights_receipts_path.open(encoding="utf-8", newline="") as fh:
    rights_rows = list(csv.DictReader(fh, delimiter="\t"))
for receipt in rights_rows:
    saved = download_dir / "rights" / receipt["file"]
    if receipt.get("check") != "ok" or not saved.is_file() or saved.stat().st_size != int(receipt["size_bytes"]) \
            or hashlib.sha256(saved.read_bytes()).hexdigest() != receipt["sha256"]:
        raise SystemExit(f"rights evidence {receipt['file']} missing, not ok, or changed since download")
    print(f"rights ok file={receipt['file']} kind={receipt['kind']} effective_url={receipt['effective_url']}")
kinds = {r["kind"] for r in rights_rows}
if "mpc" not in kinds or not kinds & {"usgs", "aws"}:
    raise SystemExit(f"rights receipts need mpc plus usgs or aws; have {sorted(kinds)}")

pinned_path = recipe_dir / "sources.tsv"
if not pinned_path.is_file() or plan_path.read_bytes() != pinned_path.read_bytes():
    raise SystemExit(f"{plan_path} differs from the pinned {pinned_path}; rerun download.sh")
with plan_path.open(encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
with receipts_path.open(encoding="utf-8", newline="") as fh:
    receipts = {(r["product_id"], r["band"]): r for r in csv.DictReader(fh, delimiter="\t")}
scenes: dict[str, dict[str, dict]] = {}
for row in plan:
    scenes.setdefault(row["item_id"], {})[row["band"]] = row
if len(scenes) != EXPECTED_SCENES:
    raise SystemExit(f"plan has {len(scenes)} scenes, expected {EXPECTED_SCENES}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)


def read_checked(row: dict) -> tuple[Path, bytes, str]:
    source = scene_dir / row["url"].rsplit("/", 1)[1]
    if not source.is_file():
        raise SystemExit(f"missing source file {source}")
    data = source.read_bytes()
    if len(data) != int(row["size_bytes"]):
        raise SystemExit(f"{source.name}: size {len(data)} != plan {row['size_bytes']}")
    md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
    if md5 != row["content_md5_b64"]:
        raise SystemExit(f"{source.name}: md5 {md5} != plan {row['content_md5_b64']}")
    sha = hashlib.sha256(data).hexdigest()
    if receipts.get((row["product_id"], row["band"]), {}).get("sha256") != sha:
        raise SystemExit(f"{source.name}: sha256 differs from download receipt")
    return source, data, sha


index_rows: list[dict] = []
scene_rows: list[dict] = []
digests: set[str] = set()
for item_id, files in sorted(scenes.items(), key=lambda kv: kv[1]["B1"]["region_id"]):
    head = files["B1"]
    product = head["product_id"]
    rows_px, cols_px = int(head["proj_rows"]), int(head["proj_cols"])
    mtl_path, _, mtl_sha = read_checked(files["MTL"])
    try:
        mtl = mtl_check.summarize(str(mtl_path), product, head["wrs_path"], head["wrs_row"], rows_px, cols_px)
    except ValueError as exc:
        raise SystemExit(f"{mtl_path.name}: {exc}")
    rasters: list[bytes] = []
    pending: list[dict] = []
    for band, common, wavelength in BANDS:
        row = files[band]
        source, data, sha = read_checked(row)
        try:
            info = cog.structure(data)
            raster = cog.decode(data, info)
        except cog.CogError as exc:
            raise SystemExit(f"{source.name}: {exc}")
        del data
        width, height = info["width"], info["height"]
        if (width, height) != (cols_px, rows_px):
            raise SystemExit(f"{source.name}: IFD0 {width}x{height} != pinned {cols_px}x{rows_px}")
        stats = band_stats(raster, width, height)
        check_band(f"{source.name}", stats)
        digest = hashlib.sha256(raster).hexdigest()
        if digest in digests:
            raise SystemExit(f"{source.name}: duplicate raster content")
        digests.add(digest)
        out = out_dir / f"{item_id}__{head['region_id']}__{band}_{common}.bin"
        out.write_bytes(raster)
        rasters.append(raster)
        mtl_band = mtl["bands"][band]
        pending.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": rel(out),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(raster),
            "value_count": len(raster),
            "sample_format": "raw homogeneous uint8 raster, row-major (source TIFF order)",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["row_north_to_south", "column_west_to_east"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_format": SOURCE_FORMAT,
            "source_field": SOURCE_FIELD,
            "band": band,
            "band_common_name": common,
            "band_center_wavelength_um": wavelength,
            "stac_item_id": item_id,
            "landsat_product_id": product,
            "landsat_scene_id": mtl["landsat_scene_id"],
            "region_id": head["region_id"],
            "region_label": head["region_label"],
            "wrs_path": head["wrs_path"],
            "wrs_row": head["wrs_row"],
            "datetime": head["datetime"],
            "eo_cloud_cover": float(head["cloud_cover"]),
            "view_sun_elevation": float(head["sun_elevation"]),
            "view_sun_azimuth": None if head["sun_azimuth"] == "NA" else float(head["sun_azimuth"]),
            "station_id": mtl["station_id"],
            "utm_zone": mtl["utm_zone"],
            "pixel_size_m": 60,
            "source_url": row["url"],
            "source_file": rel(source),
            "source_size_bytes": int(row["size_bytes"]),
            "source_content_md5_b64": row["content_md5_b64"],
            "source_sha256": sha,
            "mtl_file": rel(mtl_path),
            "mtl_sha256": mtl_sha,
            "tiff_compression": info["compression"],
            "tiff_predictor": info["predictor"],
            "tiff_tile": [info["tile_height"], info["tile_width"]],
            "tiff_sparse_tiles": info["sparse_tiles"],
            "gdal_nodata": info["gdal_nodata"],
            "fill_value": FILL,
            "fill_count": stats["fill_count"],
            "fill_fraction": round(stats["fill_fraction"], 6),
            "valid_count": stats["valid_count"],
            "valid_dn_range": [mtl_band["quantize_cal_min"], mtl_band["quantize_cal_max"]],
            "valid_min": stats["valid_min"],
            "valid_max": stats["valid_max"],
            "distinct_valid": stats["distinct_valid"],
            "valid_mean": round(stats["mean"], 4),
            "valid_std": round(stats["std"], 4),
            "saturated_255_count": stats["saturated_255_count"],
            "mtl_saturation_flag": mtl_band["saturation_flag"],
            "entropy_bits": round(stats["entropy_bits"], 4),
            "coherence": round(stats["coherence"], 6),
            "min_value_stored": FILL if stats["fill_count"] else stats["valid_min"],
            "max_value_stored": stats["valid_max"],
            "radiance_mult": mtl_band["radiance_mult"],
            "radiance_add": mtl_band["radiance_add"],
            "radiance_note": "TOA radiance W m-2 sr-1 um-1 = radiance_mult * DN + radiance_add (MTL); NOT applied",
            "sha256": digest,
        })
        print(f"decoded {source.name} shape={height}x{width} fill={stats['fill_fraction']:.3f} "
              f"dn={stats['valid_min']}..{stats['valid_max']} distinct={stats['distinct_valid']} "
              f"mean={stats['mean']:.1f} std={stats['std']:.1f} sat255={stats['saturated_255_count']} "
              f"H={stats['entropy_bits']:.2f}b coh={stats['coherence']:.3f}")
        del raster
    mixed, agreement = mask_agreement(rasters)
    corr12 = pair_corr(rasters[0], rasters[1])
    corr34 = pair_corr(rasters[2], rasters[3])
    del rasters
    if agreement < MIN_MASK_AGREEMENT:
        raise SystemExit(f"{item_id}: band fill masks disagree (agreement {agreement:.4f})")
    if corr12 < MIN_BAND_PAIR_CORR or corr34 < MIN_BAND_PAIR_CORR:
        raise SystemExit(f"{item_id}: band correlations B1/B2={corr12:.3f} B3/B4={corr34:.3f} too low (bad decode?)")
    for entry in pending:
        entry.update({
            "scene_mixed_fill_pixels": mixed,
            "scene_mask_agreement": round(agreement, 6),
            "scene_corr_b1_b2": round(corr12, 6),
            "scene_corr_b3_b4": round(corr34, 6),
        })
    index_rows.extend(pending)
    scene_rows.append({
        "stac_item_id": item_id, "landsat_product_id": product, "region_id": head["region_id"],
        "wrs": f"{head['wrs_path']}/{head['wrs_row']}", "datetime": head["datetime"],
        "sample_shape": [rows_px, cols_px], "mask_agreement": round(agreement, 6),
        "corr_b1_b2": round(corr12, 6), "corr_b3_b4": round(corr34, 6),
        "fill_fraction_by_band": [e["fill_fraction"] for e in pending],
        "valid_range_by_band": [[e["valid_min"], e["valid_max"]] for e in pending],
        "distinct_by_band": [e["distinct_valid"] for e in pending],
        "processing": {k: mtl[k] for k in ("date_product_generated", "processing_software_version", "cpf",
                                           "station_id", "geometric_rmse_model")},
    })
    print(f"scene {item_id} region={head['region_id']} mask_agreement={agreement:.5f} "
          f"corr12={corr12:.3f} corr34={corr34:.3f}")

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in index_rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes {total_bytes} exceed 1e9")
fill_total = sum(r["fill_count"] for r in index_rows)
stats_doc = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "scenes": len(scene_rows),
    "primary_values": sum(r["value_count"] for r in index_rows),
    "primary_sample_bytes": total_bytes,
    "fill_count_total": fill_total,
    "fill_fraction_total": round(fill_total / total_bytes, 6),
    "fill_fraction_range": [min(r["fill_fraction"] for r in index_rows), max(r["fill_fraction"] for r in index_rows)],
    "valid_dn_min": min(r["valid_min"] for r in index_rows),
    "valid_dn_max": max(r["valid_max"] for r in index_rows),
    "rights_receipts": rights_rows,
    "scene_summaries": scene_rows,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(index_rows)} scenes={len(scene_rows)} values={stats_doc['primary_values']} "
      f"bytes={total_bytes} fill_fraction={stats_doc['fill_fraction_total']} dn={stats_doc['valid_dn_min']}..{stats_doc['valid_dn_max']}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
