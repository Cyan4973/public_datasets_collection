#!/usr/bin/env bash
# Decode the 31 pinned GWA v4 country wind-speed-at-100-m GeoTIFFs (local
# files only) into raw little-endian float32 rasters, one per country (the
# complete full-resolution IFD0 grid; overviews are ignored).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwa_v4_country_wind_speed_100m_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
command -v "${ZSTD_BIN:-zstd}" >/dev/null || { echo "FATAL: zstd CLI not found" >&2; exit 1; }
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/gwa_tiff.py" selftest
python3 - <<'PY'
from __future__ import annotations

import array
import csv
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
import gwa_tiff  # noqa: E402

if sys.byteorder != "little":
    raise SystemExit("this build assumes a little-endian host")

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "gwa_v4_wind_speed_100m_f32"
EXPECTED_SAMPLES = 31
NAN_BITS = 0x7FC00000  # GDAL float32 nodata NaN as stored in the source
# Degeneracy / plausibility bounds shared with verify.sh.
VALID_SHARE_RANGE = (0.30, 0.90)
VALUE_RANGE = (0.0, 40.0)  # m/s, long-term mean wind speed
MIN_DISTINCT_VALID = 10_000
MIN_VALID_SPAN = 0.5  # m/s between min and max valid value
NATURAL_RECORD_KIND = "complete_gwa_v4_country_raster_full_resolution_ifd0"
SOURCE_FORMAT = "gdal_cloud_optimized_bigtiff_zstd_floating_point_predictor_float32"
SOURCE_FIELD = "band_1_mean_wind_speed_100m_agl_m_per_s"

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
tif_dir = data_root / "downloads" / DATASET_ID / "country_tifs_v4"
filter_dir = data_root / "filtered" / DATASET_ID
index_dir = data_root / "index" / DATASET_ID
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def file_digests(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def raster_stats(raw: bytes) -> dict:
    bits = array.array("I")
    bits.frombytes(raw)
    vals = array.array("f")
    vals.frombytes(raw)
    nan_count = bits.count(NAN_BITS)
    valid = [v for v in vals if v == v]
    other_nan = len(vals) - nan_count - len(valid)
    if other_nan:
        raise SystemExit(f"{other_nan} NaN values with a bit pattern other than 0x{NAN_BITS:08x}")
    if not valid:
        raise SystemExit("raster has no valid values")
    lo, hi = min(valid), max(valid)
    if lo != lo or hi in (float("inf"), float("-inf")) or lo in (float("inf"), float("-inf")):
        raise SystemExit("non-finite valid values")
    valid.sort()
    n = len(valid)
    median = valid[n // 2] if n % 2 else (valid[n // 2 - 1] + valid[n // 2]) / 2
    distinct = len({b for b in bits if b != NAN_BITS})
    return {
        "value_count": len(vals),
        "nan_count": nan_count,
        "valid_count": n,
        "valid_share": n / len(vals),
        "min_value_stored": lo,
        "max_value_stored": hi,
        "mean_valid": sum(valid) / n,
        "median_valid": median,
        "p01_valid": valid[int(0.01 * (n - 1))],
        "p99_valid": valid[int(0.99 * (n - 1))],
        "distinct_valid_values": distinct,
    }


def check_stats(name: str, s: dict) -> None:
    if not VALID_SHARE_RANGE[0] <= s["valid_share"] <= VALID_SHARE_RANGE[1]:
        raise SystemExit(f"{name}: valid share {s['valid_share']:.4f} outside {VALID_SHARE_RANGE}")
    if s["min_value_stored"] < VALUE_RANGE[0] or s["max_value_stored"] > VALUE_RANGE[1]:
        raise SystemExit(f"{name}: values {s['min_value_stored']}..{s['max_value_stored']} outside {VALUE_RANGE} m/s")
    if s["distinct_valid_values"] < MIN_DISTINCT_VALID:
        raise SystemExit(f"{name}: only {s['distinct_valid_values']} distinct valid values (degenerate)")
    if s["max_value_stored"] - s["min_value_stored"] < MIN_VALID_SPAN:
        raise SystemExit(f"{name}: valid span below {MIN_VALID_SPAN} m/s (degenerate)")


countries = list(csv.DictReader((recipe_dir / "countries.tsv").open(encoding="utf-8"), delimiter="\t"))
if len(countries) != EXPECTED_SAMPLES:
    raise SystemExit(f"countries.tsv rows={len(countries)} expected={EXPECTED_SAMPLES}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict] = []
source_rows: list[dict] = []
seen: set[str] = set()
for row in countries:
    iso = row["iso3"]
    src = tif_dir / f"{iso}_wind-speed_100m.tif"
    if not src.is_file():
        raise SystemExit(f"missing source file (run download.sh first): {src}")
    if src.stat().st_size != int(row["size_bytes"]):
        raise SystemExit(f"{src.name}: size {src.stat().st_size} != pinned {row['size_bytes']}")
    md5, sha = file_digests(src)
    if md5 != row["etag_md5"]:
        raise SystemExit(f"{src.name}: md5 {md5} != pinned ETag {row['etag_md5']}")
    if row["sha256"] and sha != row["sha256"]:
        raise SystemExit(f"{src.name}: sha256 {sha} != pinned {row['sha256']}")
    width, height = int(row["width"]), int(row["height"])
    with src.open("rb") as fh:
        try:
            info = gwa_tiff.structure(fh)
            gwa_tiff.validate_encoding(info)
            if (info["width"], info["height"], info["tile_count"]) != (width, height, int(row["tile_count"])):
                raise gwa_tiff.TiffError(f"geometry {info['width']}x{info['height']} != pinned {width}x{height}")
            lon, lat = info["tiepoint_lon_lat"]
            if f"{lon:.6f}" != row["upper_left_lon"] or f"{lat:.6f}" != row["upper_left_lat"]:
                raise gwa_tiff.TiffError(f"tiepoint {lon},{lat} != pinned {row['upper_left_lon']},{row['upper_left_lat']}")
            raster = gwa_tiff.decode_ifd0(fh, info)
        except gwa_tiff.TiffError as exc:
            raise SystemExit(f"{src.name}: {exc}")
    if len(raster) != width * height * 4:
        raise SystemExit(f"{src.name}: decoded {len(raster)} bytes, expected {width * height * 4}")
    stats = raster_stats(raster)
    check_stats(src.name, stats)
    digest = hashlib.sha256(raster).hexdigest()
    if digest in seen:
        raise SystemExit(f"{src.name}: duplicate raster content")
    seen.add(digest)

    out = out_dir / f"gwa4_ws100m_{iso}_{height}x{width}_f32le.bin"
    out.write_bytes(raster)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": len(raster),
        "value_count": stats["value_count"],
        "sample_format": "raw homogeneous float32 raster, row-major (north row first, west column first)",
        "sample_rank": 2,
        "sample_shape": [height, width],
        "sample_axes": ["latitude_north_to_south", "longitude_west_to_east"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_format": SOURCE_FORMAT,
        "source_field": SOURCE_FIELD,
        "units": "m/s",
        "height_above_ground_m": 100,
        "iso3": iso,
        "country": row["country"],
        "region": row["region"],
        "crs": "EPSG:4326",
        "pixel_size_deg": 0.0025,
        "upper_left_lon": float(row["upper_left_lon"]),
        "upper_left_lat": float(row["upper_left_lat"]),
        "source_url": row["url"],
        "source_file": rel(src),
        "source_size_bytes": int(row["size_bytes"]),
        "source_md5": md5,
        "source_sha256": sha,
        "source_last_modified": row["last_modified"],
        "missing_value": "NaN (bit pattern 0x7fc00000, GDAL_NODATA nan) outside the GWA country + EEZ mask",
        "nan_count": stats["nan_count"],
        "valid_count": stats["valid_count"],
        "valid_share": round(stats["valid_share"], 6),
        "min_value_stored": stats["min_value_stored"],
        "max_value_stored": stats["max_value_stored"],
        "mean_valid": round(stats["mean_valid"], 6),
        "median_valid": stats["median_valid"],
        "p01_valid": stats["p01_valid"],
        "p99_valid": stats["p99_valid"],
        "distinct_valid_values": stats["distinct_valid_values"],
        "sha256": digest,
    })
    source_rows.append({
        "iso3": iso,
        "source_file": rel(src),
        "source_md5": md5,
        "source_sha256": sha,
        "ifd_count": info["ifd_count"],
        "overview_sizes": info["overview_sizes"],
        "tile_count": info["tile_count"],
        "tile_bytes_total": sum(info["tile_byte_counts"]),
        "pixel_scale": info["pixel_scale"],
        "tiepoint_lon_lat": info["tiepoint_lon_lat"],
    })
    print(f"built iso3={iso} shape={height}x{width} valid_share={stats['valid_share']:.4f} "
          f"range={stats['min_value_stored']:.3f}..{stats['max_value_stored']:.3f} "
          f"median={stats['median_valid']:.3f} distinct={stats['distinct_valid_values']} sha256={digest[:16]}")
    del raster

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for index_row in index_rows:
        fh.write(json.dumps(index_row, sort_keys=True) + "\n")
total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
total_values = sum(r["value_count"] for r in index_rows)
total_valid = sum(r["valid_count"] for r in index_rows)
summary = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "primary_values": total_values,
    "primary_sample_bytes": total_bytes,
    "valid_values": total_valid,
    "nan_values": total_values - total_valid,
    "valid_share": round(total_valid / total_values, 6),
    "min_value_stored": min(r["min_value_stored"] for r in index_rows),
    "max_value_stored": max(r["max_value_stored"] for r in index_rows),
    "sources": source_rows,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(index_rows)} values={total_values} bytes={total_bytes} "
      f"valid_share={summary['valid_share']:.4f}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
