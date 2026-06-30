#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_water_sites_rdb"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export USGS_WATER_SITES_MIN_RETAINED_RECORDS="${USGS_WATER_SITES_MIN_RETAINED_RECORDS:-20000}"
export USGS_WATER_SITES_MIN_PRIMARY_VALUES="${USGS_WATER_SITES_MIN_PRIMARY_VALUES:-100000}"
export USGS_WATER_SITES_MIN_PRIMARY_BYTES="${USGS_WATER_SITES_MIN_PRIMARY_BYTES:-102400}"
export USGS_WATER_SITES_MIN_MEDIAN_VALUES="${USGS_WATER_SITES_MIN_MEDIAN_VALUES:-1000}"
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "usgs_water_sites_rdb"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["USGS_WATER_SITES_MIN_RETAINED_RECORDS"])
min_primary_values = int(os.environ["USGS_WATER_SITES_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["USGS_WATER_SITES_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["USGS_WATER_SITES_MIN_MEDIAN_VALUES"])

inventory_dir = download_dir / "site_inventory"
source_files = sorted(inventory_dir.glob("site_inventory_*.txt"))
if not source_files:
    legacy = download_dir / "usgs_water_sites_rdb.txt"
    if legacy.is_file():
        source_files = [legacy]
if not source_files:
    raise SystemExit(f"missing local USGS RDB files under {inventory_dir}; run download.sh first")

series_meta = {
    "usgs_site_no": ("uint", 64, 8, "Q", "auxiliary", "USGS site number encoded as an unsigned integer."),
    "usgs_dec_lat": ("float", 64, 8, "d", "primary", "Decimal latitude in WGS84 degrees."),
    "usgs_dec_long": ("float", 64, 8, "d", "primary", "Decimal longitude in WGS84 degrees."),
    "usgs_altitude": ("float", 64, 8, "d", "primary", "Site altitude in feet reported by USGS."),
    "usgs_alt_accuracy": ("float", 32, 4, "f", "primary", "Altitude accuracy in feet reported by USGS."),
    "usgs_huc_cd": ("uint", 64, 8, "Q", "primary", "Hydrologic unit code encoded as an unsigned integer."),
}
values: dict[str, list[int | float]] = {series_id: [] for series_id in series_meta}
required_columns = ["agency_cd", "site_no", "site_tp_cd", "dec_lat_va", "dec_long_va", "alt_va", "alt_acy_va", "huc_cd"]
source_rows = 0
retained = 0
skipped = 0
duplicates = 0
seen_sites: set[tuple[str, str]] = set()
skip_reasons: dict[str, int] = {}


def bump(reason: str) -> None:
    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1


def parse_rdb(path: Path):
    header: list[str] | None = None
    indexes: dict[str, int] | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.startswith("#") or not line.strip():
                continue
            columns = line.rstrip("\n").split("\t")
            if header is None:
                header = columns
                missing = set(required_columns).difference(header)
                if missing:
                    raise SystemExit(f"{path}: missing required columns {sorted(missing)}")
                indexes = {name: header.index(name) for name in required_columns}
                continue
            if columns and columns[0].endswith("s"):
                continue
            if len(columns) < len(header):
                columns += [""] * (len(header) - len(columns))
            yield line_number, columns, indexes


for source_file in source_files:
    for _line_number, columns, idx in parse_rdb(source_file):
        source_rows += 1
        agency_cd = columns[idx["agency_cd"]].strip()
        site_no_raw = columns[idx["site_no"]].strip()
        site_tp_cd = columns[idx["site_tp_cd"]].strip()
        if not site_tp_cd.startswith("ST"):
            skipped += 1
            bump("site_type")
            continue
        site_key = (agency_cd, site_no_raw)
        if site_key in seen_sites:
            duplicates += 1
            continue
        seen_sites.add(site_key)
        try:
            site_no = int(site_no_raw)
            dec_lat = float(columns[idx["dec_lat_va"]].strip())
            dec_long = float(columns[idx["dec_long_va"]].strip())
            altitude = float(columns[idx["alt_va"]].strip())
            alt_accuracy = float(columns[idx["alt_acy_va"]].strip())
            huc_cd = int(columns[idx["huc_cd"]].strip())
        except Exception:
            skipped += 1
            bump("parse")
            continue
        if site_no < 0 or site_no > 0xFFFFFFFFFFFFFFFF:
            skipped += 1
            bump("site_no_range")
            continue
        if huc_cd < 0 or huc_cd > 0xFFFFFFFFFFFFFFFF:
            skipped += 1
            bump("huc_cd_range")
            continue
        if not (math.isfinite(dec_lat) and -90.0 <= dec_lat <= 90.0):
            skipped += 1
            bump("latitude_range")
            continue
        if not (math.isfinite(dec_long) and -180.0 <= dec_long <= 180.0):
            skipped += 1
            bump("longitude_range")
            continue
        if not (math.isfinite(altitude) and -1000.0 <= altitude <= 20000.0):
            skipped += 1
            bump("altitude_range")
            continue
        if not (math.isfinite(alt_accuracy) and 0.0 <= alt_accuracy <= 20000.0):
            skipped += 1
            bump("alt_accuracy_range")
            continue

        values["usgs_site_no"].append(site_no)
        values["usgs_dec_lat"].append(dec_lat)
        values["usgs_dec_long"].append(dec_long)
        values["usgs_altitude"].append(altitude)
        values["usgs_alt_accuracy"].append(alt_accuracy)
        values["usgs_huc_cd"].append(huc_cd)
        retained += 1

if retained < min_retained:
    raise SystemExit(
        f"only {retained} retained complete site rows < USGS_WATER_SITES_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh"
    )

lengths = {len(series_values) for series_values in values.values()}
if lengths != {retained}:
    raise SystemExit(f"series length mismatch: {sorted(lengths)}")

for series_id, series_values in values.items():
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant sample after filtering: {series_id}")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
for series_id, (kind, bits, element_size, code, role, description) in series_meta.items():
    series_values = values[series_id]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_{kind}{bits}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": role,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "usgs_stream_site_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["site"],
            "natural_record_kind": "usgs_site_row",
            "natural_record_count": retained,
            "description": description,
            "min": min(series_values),
            "max": max(series_values),
        }
    )

counts = [int(row["value_count"]) for row in rows if row["role"] == "primary"]
byte_counts = [int(row["sample_size_bytes"]) for row in rows if row["role"] == "primary"]
primary_values = sum(counts)
primary_bytes = sum(byte_counts)
median_values = statistics.median(counts)
if primary_values < min_primary_values:
    raise SystemExit(f"repair target not met: primary_values={primary_values} < {min_primary_values}")
if primary_bytes < min_primary_bytes:
    raise SystemExit(f"below aggregate byte floor: primary_bytes={primary_bytes} < {min_primary_bytes}")
if median_values < min_median_values:
    raise SystemExit(f"median sample values below floor: {median_values} < {min_median_values}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_files": [path.name for path in source_files],
            "source_rows": source_rows,
            "retained_records": retained,
            "skipped_records": skipped,
            "duplicate_records": duplicates,
            "skip_reasons": skip_reasons,
            "primary_values": primary_values,
            "primary_sample_bytes": primary_bytes,
            "median_primary_values": median_values,
            "min_retained_records": min_retained,
            "min_primary_values": min_primary_values,
            "min_primary_bytes": min_primary_bytes,
            "min_median_values": min_median_values,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"retained_records={retained} primary_values={primary_values} "
    f"primary_sample_bytes={primary_bytes} median_primary_values={median_values}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
