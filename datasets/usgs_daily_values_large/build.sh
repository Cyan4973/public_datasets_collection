#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_daily_values_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_DAYS="${USGS_MIN_DAYS:-1000}"
MIN_SAMPLES_PER_FAMILY="${USGS_MIN_SAMPLES_PER_FAMILY:-5}"
export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_DAYS MIN_SAMPLES_PER_FAMILY
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_days = int(os.environ["MIN_DAYS"])
min_samples = int(os.environ["MIN_SAMPLES_PER_FAMILY"])

# parameterCd -> family series_id (each a distinct physical quantity / unit)
PARAM_FAMILY = {
    "00060": "usgs_streamflow_cfs_f64",
    "00065": "usgs_gage_height_ft_f64",
    "00010": "usgs_water_temp_c_f64",
}
SENTINEL = -999990.0

pages = sorted(page_dir.glob("usgs_*.json"))
if not pages:
    raise SystemExit(f"no downloaded USGS pages under {page_dir}")

# (param, site) -> longest valid value list
best: dict[tuple, list] = {}
for path in pages:
    with path.open(encoding="utf-8") as fh:
        ts_list = json.load(fh)["value"]["timeSeries"]
    for ts in ts_list:
        param = ts["variable"]["variableCode"][0]["value"]
        if param not in PARAM_FAMILY:
            continue
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        for wrapper in ts.get("values", []):
            rows = wrapper.get("value") or []
            values = []
            for row in rows:
                raw = str(row.get("value", "")).strip()
                if not raw or not str(row.get("dateTime", "")).strip():
                    continue
                try:
                    v = float(raw)
                except ValueError:
                    continue
                if v <= SENTINEL:
                    continue
                values.append(v)
            key = (param, site)
            if len(values) > len(best.get(key, [])):
                best[key] = values

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

# group kept (>= min_days, non-constant) site series by family
by_family: dict[str, list[tuple[str, list]]] = {}
for (param, site), values in best.items():
    if len(values) < min_days:
        continue
    if len(set(values)) <= 1:
        continue
    fam = PARAM_FAMILY[param]
    by_family.setdefault(fam, []).append((site, values))

index_rows = []
fam_summary = {}
for fam, site_series in sorted(by_family.items()):
    if len(site_series) < min_samples:
        print(f"drop_family {fam}: only {len(site_series)} sites (< {min_samples})")
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for site, values in sorted(site_series):
        out = samples_dir / fam / f"{site}_n{len(values):06d}.bin"
        with out.open("wb") as fh:
            fh.write(struct.pack("<" + "d" * len(values), *values))
        index_rows.append({
            "dataset_id": "usgs_daily_values_large",
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "site_no": site,
            "natural_record_kind": "usgs_site_daily_series",
        })
    fam_summary[fam] = len(site_series)

if not index_rows:
    raise SystemExit("no families met the per-family sample floor")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
stats = {
    "dataset_id": "usgs_daily_values_large",
    "families": fam_summary,
    "samples": len(index_rows),
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built families={fam_summary} samples={len(index_rows)} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
