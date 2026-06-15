#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_isd_lite"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_isd_lite"
INDEX_ROOT="${DATA_DIR}/index/noaa_isd_lite"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_isd_lite"
LOG_ROOT="${DATA_DIR}/logs/noaa_isd_lite"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  cp "${LOG_FILE}" "${LATEST_LOG}"
}
trap sync_latest_log EXIT

say() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" \
FILTERED_ROOT="${FILTERED_ROOT}" \
INDEX_ROOT="${INDEX_ROOT}" \
SAMPLES_ROOT="${SAMPLES_ROOT}" \
python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import csv
import gzip
import json
import os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
dataset_root = samples_root.parent.parent

years = [2021, 2022, 2023]
stations = [
    ("486980-99999", "singapore"),
    ("967490-99999", "jakarta"),
    ("486470-99999", "kuala_lumpur"),
    ("821110-99999", "manaus"),
    ("637400-99999", "nairobi"),
    ("430030-99999", "mumbai"),
    ("484560-99999", "bangkok"),
    ("652010-99999", "lagos"),
    ("911820-22521", "honolulu"),
    ("941200-99999", "darwin"),
    ("411940-99999", "dubai"),
    ("412170-99999", "abu_dhabi"),
    ("722780-23183", "phoenix"),
    ("623660-99999", "cairo"),
    ("943260-99999", "alice_springs"),
    ("725650-03017", "denver"),
    ("442920-99999", "ulaanbaatar"),
    ("846280-99999", "lima"),
    ("037720-99999", "london"),
    ("071570-99999", "paris"),
    ("476710-99999", "tokyo"),
    ("947670-99999", "sydney"),
    ("875760-99999", "buenos_aires"),
    ("837800-99999", "sao_paulo"),
    ("162420-99999", "rome"),
    ("688160-99999", "cape_town"),
    ("724940-23234", "san_francisco"),
    ("722190-13874", "atlanta"),
    ("583620-99999", "shanghai"),
    ("931190-99999", "auckland"),
    ("725300-94846", "chicago"),
    ("716240-99999", "toronto"),
    ("276120-99999", "moscow"),
    ("545110-99999", "beijing"),
    ("471080-99999", "seoul"),
    ("029740-99999", "helsinki"),
    ("024840-99999", "stockholm"),
    ("726580-14922", "minneapolis"),
    ("123750-99999", "warsaw"),
    ("296340-99999", "novosibirsk"),
    ("474120-99999", "sapporo"),
    ("702730-26451", "anchorage"),
    ("702610-26411", "fairbanks"),
    ("040300-99999", "reykjavik"),
    ("012250-99999", "tromso"),
    ("249590-99999", "yakutsk"),
]

series_defs = {
    "isd_year": {"element_size_bytes": 2, "numeric_kind": "uint", "bit_width": 16, "endianness": "little"},
    "isd_month": {"element_size_bytes": 1, "numeric_kind": "uint", "bit_width": 8, "endianness": "little"},
    "isd_day": {"element_size_bytes": 1, "numeric_kind": "uint", "bit_width": 8, "endianness": "little"},
    "isd_hour": {"element_size_bytes": 1, "numeric_kind": "uint", "bit_width": 8, "endianness": "little"},
    "isd_temp": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_dewp": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_slp": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_wdir": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_wspd": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_sky": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_precip1h": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
    "isd_precip6h": {"element_size_bytes": 2, "numeric_kind": "int", "bit_width": 16, "endianness": "little"},
}

history_path = download_root / "history" / "isd-history.csv"
if not history_path.is_file():
    raise SystemExit(f"missing history file: {history_path}")
if history_path.stat().st_size <= 0:
    raise SystemExit(f"empty history file: {history_path}")

def parse_row(line: str) -> tuple[int, ...] | None:
    parts = line.strip().split()
    if len(parts) != 12:
        return None
    try:
        values = tuple(int(part) for part in parts)
    except ValueError:
        return None
    month, day, hour = values[1], values[2], values[3]
    if not (0 <= month <= 12 and 0 <= day <= 31 and 0 <= hour <= 23):
        return None
    return values

def is_constant(values) -> bool:
    return bool(values) and all(value == values[0] for value in values)

expected_rows: dict[str, int] = {}
expected_skipped_constants: dict[tuple[str, str], dict[str, str]] = {}
series_order = list(series_defs)
for station_id, slug in stations:
    row_count = 0
    arrays = {series_id: [] for series_id in series_defs}
    for year in years:
        gz_path = download_root / "isd-lite" / str(year) / f"{station_id}-{year}.gz"
        if not gz_path.is_file():
            raise SystemExit(f"missing raw file: {gz_path}")
        if gz_path.stat().st_size <= 0:
            raise SystemExit(f"empty raw file: {gz_path}")
        with gzip.open(gz_path, "rt", encoding="ascii", errors="strict") as handle:
            for line in handle:
                parsed = parse_row(line)
                if parsed is None:
                    continue
                for series_id, value in zip(series_order, parsed):
                    arrays[series_id].append(value)
                row_count += 1
    expected_rows[slug] = row_count
    for series_id, values in arrays.items():
        if is_constant(values):
            expected_skipped_constants[(series_id, slug)] = {
                "station_id": station_id,
                "station_slug": slug,
                "series_id": series_id,
                "value_count": str(len(values)),
                "constant_value": str(values[0]),
            }

row_counts_path = filtered_root / "station_row_counts.tsv"
if row_counts_path.is_file():
    with row_counts_path.open("r", encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    seen = {row["station_slug"]: int(row["row_count"]) for row in rows}
    for _, slug in stations:
        if seen.get(slug) != expected_rows[slug]:
            raise SystemExit(
                f"row count mismatch for {slug}: filtered={seen.get(slug)} raw={expected_rows[slug]}"
            )

expected_index_records: dict[tuple[str, str], dict[str, object]] = {}
skipped_constants_path = filtered_root / "skipped_constant_samples.tsv"
if not skipped_constants_path.is_file():
    raise SystemExit(f"missing skipped constants file: {skipped_constants_path}")
with skipped_constants_path.open("r", encoding="ascii", newline="") as handle:
    skipped_constant_rows = list(csv.DictReader(handle, delimiter="\t"))
skipped_constants_by_key = {(row["series_id"], row["station_slug"]): row for row in skipped_constant_rows}

for series_id, meta in series_defs.items():
    series_dir = samples_root / series_id
    if not series_dir.is_dir():
        raise SystemExit(f"missing samples directory: {series_dir}")
    files = sorted(path for path in series_dir.glob("*.bin") if path.is_file())
    expected_slugs = {
        slug
        for _, slug in stations
        if (series_id, slug) not in expected_skipped_constants
    }
    actual_slugs = {path.stem for path in files}
    if actual_slugs != expected_slugs:
        raise SystemExit(
            f"sample files do not match expected non-constant samples in {series_dir}: actual={len(actual_slugs)} expected={len(expected_slugs)}"
        )
    for _, slug in stations:
        sample_path = series_dir / f"{slug}.bin"
        if (series_id, slug) in expected_skipped_constants:
            if sample_path.exists():
                raise SystemExit(f"constant sample was not skipped: {sample_path}")
            continue
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        expected_size = expected_rows[slug] * int(meta["element_size_bytes"])
        actual_size = sample_path.stat().st_size
        if actual_size != expected_size:
            raise SystemExit(
                f"wrong size for {sample_path}: expected {expected_size}, got {actual_size}"
            )
        expected_index_records[(series_id, slug)] = {
            "dataset_id": "noaa_isd_lite",
            "series_id": series_id,
            "sample_path": sample_path.relative_to(dataset_root).as_posix(),
            "numeric_kind": meta["numeric_kind"],
            "bit_width": meta["bit_width"],
            "endianness": meta["endianness"],
            "element_size_bytes": meta["element_size_bytes"],
            "sample_size_bytes": actual_size,
            "value_count": expected_rows[slug],
        }

index_path = index_root / "samples.jsonl"
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        series_id = record.get("series_id")
        sample_relpath = record.get("sample_path")
        sample_name = Path(sample_relpath).name if isinstance(sample_relpath, str) else ""
        slug = Path(sample_name).stem
        key = (series_id, slug)
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record

if set(index_records) != set(expected_index_records):
    raise SystemExit(
        f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_index_records)}"
    )
if set(skipped_constants_by_key) != set(expected_skipped_constants):
    raise SystemExit(
        f"skipped constant keys do not match raw data: skipped={len(skipped_constants_by_key)} expected={len(expected_skipped_constants)}"
    )

for key, expected in expected_index_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(
                f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}"
            )
for key, expected in expected_skipped_constants.items():
    row = skipped_constants_by_key[key]
    for field, expected_value in expected.items():
        if row.get(field) != expected_value:
            raise SystemExit(
                f"skipped constant mismatch for {key} field {field}: {row.get(field)!r} != {expected_value!r}"
            )

print("verified raw inventory and generated sample sizes")
PY

say "verified raw inventory and generated sample sizes"
