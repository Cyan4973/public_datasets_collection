#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="federalregister_documents_large"
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
MIN_MONTH_RECORDS="${FEDREG_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_MONTH_RECORDS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
pages_dir = Path(os.environ["DOWNLOAD_DIR"]) / "pages"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["MIN_MONTH_RECORDS"])

DATASET_ID = "federalregister_documents_large"
U16_MAX = 0xFFFF
U32_MAX = 0xFFFFFFFF
# family -> (json field, numeric_kind, bit_width, struct code, max)
FAMILIES = {
    "fedreg_page_length_u16": ("page_length", "uint", 16, "H", U16_MAX),
    "fedreg_start_page_u32": ("start_page", "uint", 32, "I", U32_MAX),
}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

# One sample per month (YYYY-MM, from the page filename); de-dup docs by number.
by_fam_month = {f: defaultdict(list) for f in FAMILIES}
seen = set()
docs = 0
for path in sorted(pages_dir.glob("*_p*.json")):
    month = path.name.split("_p", 1)[0]  # "YYYY-MM"
    try:
        results = json.loads(path.read_text(encoding="utf-8")).get("results", [])
    except Exception:
        continue
    for r in results:
        dn = r.get("document_number")
        if dn in seen:
            continue
        seen.add(dn)
        docs += 1
        for fam, (field, _k, _b, _c, vmax) in FAMILIES.items():
            v = r.get(field)
            if isinstance(v, bool) or not isinstance(v, int):
                continue
            if 0 < v <= vmax:
                by_fam_month[fam][month].append(v)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for fam, (field, kind, bits, code, _vmax) in FAMILIES.items():
    months = by_fam_month[fam]
    qualifying = sorted(mo for mo, vals in months.items()
                        if len(vals) >= min_records and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for mo in qualifying:
        vals = months[mo]
        out = samples_dir / fam / f"{fam}_{mo}_n{len(vals):06d}.bin"
        out.write_bytes(struct.pack("<" + code * len(vals), *vals))
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "month": mo,
            "natural_record_kind": "federal_register_document",
        })
    fam_summary[fam] = len(qualifying)

if not fam_summary:
    raise SystemExit(f"no family qualified (docs={docs}); need >=5 months with >={min_records} values")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "documents": docs,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} documents={docs} "
    f"primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
