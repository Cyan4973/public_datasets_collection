#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geonames_postal_fixed"
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
import json, os, re, shutil, struct, zipfile
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

raw = download_dir / "US.zip"
if not raw.is_file():
    raise SystemExit("missing raw archive")

meta = {
    "geonames_postal_code_u32": ("uint", 32, "I"),
    "geonames_postal_latitude_f64": ("float", 64, "d"),
    "geonames_postal_longitude_f64": ("float", 64, "d"),
    "geonames_postal_admin1_code_u8": ("uint", 8, "B"),
    "geonames_postal_admin2_code_u16": ("uint", 16, "H"),
    "geonames_postal_accuracy_u8": ("uint", 8, "B"),
}
vals = {sid: [] for sid in meta}
for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

rows_total = 0
rows_skipped = 0

def digits_only(value: str) -> int:
    digits = re.sub(r"\D+", "", value)
    return int(digits) if digits else 0

with zipfile.ZipFile(raw) as zf:
    with zf.open("US.txt") as fh:
        for raw_line in fh:
            parts = raw_line.decode("utf-8", "replace").rstrip("\n").split("\t")
            rows_total += 1
            if len(parts) < 12:
                rows_skipped += 1
                continue
            try:
                postal_code = digits_only(parts[1].strip())
                latitude = float(parts[9].strip())
                longitude = float(parts[10].strip())
                admin1_code = digits_only(parts[4].strip())
                admin2_code = digits_only(parts[6].strip())
                accuracy = int(parts[11].strip()) if parts[11].strip() else 0
            except Exception:
                rows_skipped += 1
                continue
            vals["geonames_postal_code_u32"].append(postal_code)
            vals["geonames_postal_latitude_f64"].append(latitude)
            vals["geonames_postal_longitude_f64"].append(longitude)
            vals["geonames_postal_admin1_code_u8"].append(admin1_code)
            vals["geonames_postal_admin2_code_u16"].append(admin2_code)
            vals["geonames_postal_accuracy_u8"].append(accuracy)

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "geonames_postal_fixed",
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
    json.dumps({"dataset_id": "geonames_postal_fixed", "rows_total": rows_total, "rows_skipped": rows_skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
