#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="inspirehep_literature"
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
MIN_YEAR_RECORDS="${INSPIRE_MIN_YEAR_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_YEAR_RECORDS
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
download_dir = Path(os.environ["DOWNLOAD_DIR"])
pages_dir = download_dir / "pages"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_year_records = int(os.environ["MIN_YEAR_RECORDS"])

DATASET_ID = "inspirehep_literature"

# field path in metadata -> (family id, numeric_kind, bit_width, struct code, max value)
FAMILIES = {
    "citation_count":      ("inspirehep_citation_count_u32", "uint", 32, "I", 0xFFFFFFFF),
    "author_count":        ("inspirehep_author_count_u16",   "uint", 16, "H", 0xFFFF),
    "number_of_pages":     ("inspirehep_page_count_u16",      "uint", 16, "H", 0xFFFF),
    "number_of_references":("inspirehep_reference_count_u16", "uint", 16, "H", 0xFFFF),
}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

def year_of(meta: dict) -> int | None:
    for key in ("earliest_date", "preprint_date"):
        v = meta.get(key)
        if isinstance(v, str) and len(v) >= 4 and v[:4].isdigit():
            return int(v[:4])
    return None

# field -> {year -> [values]}
by_field_year = {f: defaultdict(list) for f in FAMILIES}
seen_ids = set()
records = 0
dups = 0
no_year = 0

for path in sorted(pages_dir.glob("year*_p*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        hits = payload["hits"]["hits"]
    except Exception:
        continue
    for hit in hits:
        meta = hit.get("metadata", {}) or {}
        rid = meta.get("control_number") or hit.get("id")
        if rid is None:
            continue
        if rid in seen_ids:
            dups += 1
            continue
        seen_ids.add(rid)
        records += 1
        y = year_of(meta)
        if y is None:
            no_year += 1
            continue
        for field, (_fam, _k, _b, _c, maxv) in FAMILIES.items():
            raw = meta.get(field)
            if raw is None:
                continue
            try:
                iv = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= iv <= maxv:
                by_field_year[field][y].append(iv)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for field, (fam, kind, bits, code, _maxv) in FAMILIES.items():
    years = by_field_year[field]
    qualifying = sorted(y for y, vals in years.items()
                        if len(vals) >= min_year_records and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue  # family lacks enough year-samples (e.g. sparse/absent field)
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for y in qualifying:
        values = years[y]
        out = samples_dir / fam / f"{fam}_y{y}_n{len(values):06d}.bin"
        out.write_bytes(struct.pack("<" + code * len(values), *values))
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
            "value_count": len(values),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "year": y,
            "natural_record_kind": "inspirehep_literature_record",
        })
    fam_summary[fam] = len(qualifying)

if len(fam_summary) < 2:
    raise SystemExit(f"only {len(fam_summary)} families qualified: {fam_summary}")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "records_unique": records,
    "duplicates_dropped": dups,
    "records_without_year": no_year,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} unique_records={records} "
    f"dups={dups} no_year={no_year} primary_values={primary_values} "
    f"median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
