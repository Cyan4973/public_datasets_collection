#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_donki_flr"
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

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import calendar
import json
import os
import re
import shutil
import struct
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_re = re.compile(r"flr_(\d{4})\.json$")
page_paths = sorted(
    [p for p in page_dir.glob("flr_*.json") if page_re.search(p.name)],
    key=lambda p: int(page_re.search(p.name).group(1)),
)
if not page_paths:
    raise SystemExit(f"no downloaded DONKI FLR pages found under {page_dir}")

# series_id -> (numeric_kind, bit_width, struct_code)
meta = {
    "donki_flr_begin_epoch_u32": ("uint", 32, "I"),
    "donki_flr_rise_seconds_u32": ("uint", 32, "I"),
    "donki_flr_decay_seconds_u32": ("uint", 32, "I"),
    "donki_flr_active_region_u32": ("uint", 32, "I"),
    "donki_flr_peak_flux_f32": ("float", 32, "f"),
    "donki_flr_source_lat_f32": ("float", 32, "f"),
    "donki_flr_source_lon_f32": ("float", 32, "f"),
}
vals: dict[str, list] = {sid: [] for sid in meta}
if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in vals:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)

CLASS_BASE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}
CLASS_RE = re.compile(r"^([ABCMX])([0-9]+(?:\.[0-9]+)?)$")
LOC_RE = re.compile(r"^([NS])(\d+)([EW])(\d+)$")


def parse_epoch(value: str) -> int:
    head = str(value).strip().rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(head, fmt)
        except ValueError:
            continue
        return calendar.timegm(dt.utctimetuple())
    raise ValueError(f"unparseable DONKI time {value!r}")


def parse_flux(value: str) -> float:
    m = CLASS_RE.match(str(value).strip())
    if not m:
        raise ValueError(f"unparseable classType {value!r}")
    return float(m.group(2)) * CLASS_BASE[m.group(1)]


def parse_location(value: str) -> tuple[float, float]:
    m = LOC_RE.match(str(value).strip())
    if not m:
        raise ValueError(f"unparseable sourceLocation {value!r}")
    lat = float(m.group(2)) * (1.0 if m.group(1) == "N" else -1.0)
    lon = float(m.group(4)) * (1.0 if m.group(3) == "E" else -1.0)
    return lat, lon


def nonneg_u32(value: int, key: str) -> int:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError(f"{key} out of uint32 range: {value}")
    return value


rows_total = 0
rows_skipped = 0
seen_ids: set[str] = set()
for path in page_paths:
    with path.open(encoding="utf-8") as fh:
        flares = json.load(fh)
    for flare in flares:
        rows_total += 1
        before = len(vals["donki_flr_begin_epoch_u32"])
        try:
            fid = flare.get("flrID")
            if not fid or fid in seen_ids:
                raise ValueError(f"missing or duplicate flrID {fid}")
            seen_ids.add(fid)
            begin = parse_epoch(flare["beginTime"])
            peak = parse_epoch(flare["peakTime"])
            end = parse_epoch(flare["endTime"])
            rise = nonneg_u32(peak - begin, "rise_seconds")
            decay = nonneg_u32(end - peak, "decay_seconds")
            flux = parse_flux(flare["classType"])
            lat, lon = parse_location(flare["sourceLocation"])
            active_region = nonneg_u32(int(flare.get("activeRegionNum") or 0), "active_region")
            vals["donki_flr_begin_epoch_u32"].append(nonneg_u32(begin, "begin_epoch"))
            vals["donki_flr_rise_seconds_u32"].append(rise)
            vals["donki_flr_decay_seconds_u32"].append(decay)
            vals["donki_flr_active_region_u32"].append(active_region)
            vals["donki_flr_peak_flux_f32"].append(flux)
            vals["donki_flr_source_lat_f32"].append(lat)
            vals["donki_flr_source_lon_f32"].append(lon)
        except Exception:
            for series_values in vals.values():
                while len(series_values) > before:
                    series_values.pop()
            rows_skipped += 1

kept_rows = len(vals["donki_flr_begin_epoch_u32"])
if len({len(series_values) for series_values in vals.values()}) != 1:
    raise SystemExit("series length mismatch after filtering")
if kept_rows == 0:
    raise SystemExit("no rows kept")

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": "nasa_donki_flr",
            "series_id": sid,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "table_row_count": kept_rows,
            "table_column_count": len(meta),
            "natural_record_kind": "donki_flr_event",
            "natural_record_count": kept_rows,
            "natural_record_values": len(meta),
        }
    )

primary_bytes = sum(row["sample_size_bytes"] for row in rows)
primary_values = sum(row["value_count"] for row in rows)
stats_out = {
    "dataset_id": "nasa_donki_flr",
    "downloaded_pages": len(page_paths),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_rows,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built rows_kept={kept_rows} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
