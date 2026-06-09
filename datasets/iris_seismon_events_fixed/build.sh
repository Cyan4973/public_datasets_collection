#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="iris_seismon_events_fixed"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import json, os, shutil, struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

features = json.load(open(download_dir / "iris_seismon_events.geojson", encoding="utf-8")).get("features", [])
meta = {
    "usgs_event_mag_f64": ("float", 64, "d"),
    "usgs_event_time_u64": ("uint", 64, "Q"),
    "usgs_event_felt_u16": ("uint", 16, "H"),
    "usgs_event_tsunami_u8": ("uint", 8, "B"),
    "usgs_event_sig_u16": ("uint", 16, "H"),
    "usgs_event_nst_u16": ("uint", 16, "H"),
    "usgs_event_dmin_f64": ("float", 64, "d"),
    "usgs_event_rms_f64": ("float", 64, "d"),
    "usgs_event_gap_u16": ("uint", 16, "H"),
}
vals = {sid: [] for sid in meta}
for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

rows_total = len(features)
rows_skipped = 0
for feature in features:
    props = feature.get("properties") or {}
    try:
        mag = props["mag"]
        time = props["time"]
        tsunami = props["tsunami"]
        sig = props["sig"]
        nst = props["nst"]
        dmin = props["dmin"]
        rms = props["rms"]
        gap = props["gap"]
        felt = props.get("felt") or 0
        if None in (mag, time, tsunami, sig, nst, dmin, rms, gap):
            rows_skipped += 1
            continue
        vals["usgs_event_mag_f64"].append(float(mag))
        vals["usgs_event_time_u64"].append(int(time))
        vals["usgs_event_felt_u16"].append(int(felt))
        vals["usgs_event_tsunami_u8"].append(int(tsunami))
        vals["usgs_event_sig_u16"].append(int(sig))
        vals["usgs_event_nst_u16"].append(int(nst))
        vals["usgs_event_dmin_f64"].append(float(dmin))
        vals["usgs_event_rms_f64"].append(float(rms))
        vals["usgs_event_gap_u16"].append(int(gap))
    except Exception:
        rows_skipped += 1

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "iris_seismon_events_fixed",
        "series_id": sid,
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": kind,
        "bit_width": bits,
        "endianness": "little",
        "element_size_bytes": bits // 8,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(values),
    })

(filter_dir / "ingest_stats.json").write_text(
    json.dumps({"dataset_id": "iris_seismon_events_fixed", "rows_total": rows_total, "rows_skipped": rows_skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
