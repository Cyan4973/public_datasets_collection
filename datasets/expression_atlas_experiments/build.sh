#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="expression_atlas_experiments"
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
import calendar, json, os, shutil, struct
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

rows_in = json.load(open(download_dir / "expression_atlas_experiments.json", encoding="utf-8")).get("experiments", [])
meta = {
    "atlas_experiment_accession_length_u16": ("uint", 16, "H"),
    "atlas_experiment_description_length_u32": ("uint", 32, "I"),
    "atlas_species_length_u16": ("uint", 16, "H"),
    "atlas_kingdom_length_u8": ("uint", 8, "B"),
    "atlas_number_of_assays_u16": ("uint", 16, "H"),
    "atlas_factor_count_u16": ("uint", 16, "H"),
    "atlas_project_count_u16": ("uint", 16, "H"),
    "atlas_raw_type_length_u16": ("uint", 16, "H"),
    "atlas_experiment_type_length_u16": ("uint", 16, "H"),
    "atlas_load_date_u32": ("uint", 32, "I"),
}
vals = {sid: [] for sid in meta}
for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

rows_total = len(rows_in)
rows_skipped = 0

def day_ts(s: str) -> int:
    return calendar.timegm(datetime.strptime(s, "%d-%m-%Y").utctimetuple())

for row in rows_in:
    try:
        vals["atlas_experiment_accession_length_u16"].append(len(row.get("experimentAccession") or ""))
        vals["atlas_experiment_description_length_u32"].append(len(row.get("experimentDescription") or ""))
        vals["atlas_species_length_u16"].append(len(row.get("species") or ""))
        vals["atlas_kingdom_length_u8"].append(len(row.get("kingdom") or ""))
        vals["atlas_number_of_assays_u16"].append(int(row.get("numberOfAssays") or 0))
        vals["atlas_factor_count_u16"].append(len(row.get("experimentalFactors") or []))
        vals["atlas_project_count_u16"].append(len(row.get("experimentProjects") or []))
        vals["atlas_raw_type_length_u16"].append(len(row.get("rawExperimentType") or ""))
        vals["atlas_experiment_type_length_u16"].append(len(row.get("experimentType") or ""))
        vals["atlas_load_date_u32"].append(day_ts(row.get("loadDate") or "01-01-1970"))
    except Exception:
        rows_skipped += 1

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "expression_atlas_experiments",
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
    json.dumps({"dataset_id": "expression_atlas_experiments", "rows_total": rows_total, "rows_skipped": rows_skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
