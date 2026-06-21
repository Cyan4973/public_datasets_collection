#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nih_reporter_projects"
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

import json
import os
import re
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_re = re.compile(r"nih_(\d{4})_p\d+\.json$")
pages_by_year: dict[int, list[Path]] = defaultdict(list)
for p in page_dir.glob("nih_*_p*.json"):
    m = page_re.search(p.name)
    if m:
        pages_by_year[int(m.group(1))].append(p)
if not pages_by_year:
    raise SystemExit(f"no downloaded NIH pages found under {page_dir}")

# series_id -> (numeric_kind, bit_width, struct_code, extractor)
def ymd(value: object) -> int:
    head = str(value)[:10]
    y, m, d = head.split("-")
    y, m, d = int(y), int(m), int(d)
    if not (1000 <= y <= 3000 and 1 <= m <= 12 and 1 <= d <= 31):
        raise ValueError(f"bad date {value!r}")
    return y * 10000 + m * 100 + d


def dollars(value: object) -> int:
    n = int(value)
    if n < 0 or n > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"dollars out of range: {n}")
    return n


meta = {
    "nih_award_amount_u64": ("uint", 64, "Q", lambda r: dollars(r["award_amount"])),
    "nih_direct_cost_amt_u64": ("uint", 64, "Q", lambda r: dollars(r["direct_cost_amt"])),
    "nih_indirect_cost_amt_u64": ("uint", 64, "Q", lambda r: dollars(r["indirect_cost_amt"])),
    "nih_project_start_date_u32": ("uint", 32, "I", lambda r: ymd(r["project_start_date"])),
    "nih_project_end_date_u32": ("uint", 32, "I", lambda r: ymd(r["project_end_date"])),
    "nih_award_notice_date_u32": ("uint", 32, "I", lambda r: ymd(r["award_notice_date"])),
}

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in meta:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)

index_records = []
rows_total = 0
rows_skipped = 0
kept_total = 0
for year in sorted(pages_by_year):
    vals = {sid: [] for sid in meta}
    seen_ids: set = set()
    for path in sorted(pages_by_year[year]):
        with path.open(encoding="utf-8") as fh:
            results = json.load(fh)["results"]
        for row in results:
            rows_total += 1
            before = len(vals["nih_award_amount_u64"])
            try:
                aid = row.get("appl_id")
                if aid is None or aid in seen_ids:
                    raise ValueError("missing or duplicate appl_id")
                seen_ids.add(aid)
                parsed = {sid: extract(row) for sid, (_k, _b, _c, extract) in meta.items()}
                for sid in meta:
                    vals[sid].append(parsed[sid])
            except Exception:
                for series_values in vals.values():
                    while len(series_values) > before:
                        series_values.pop()
                rows_skipped += 1
    kept = len(vals["nih_award_amount_u64"])
    if len({len(v) for v in vals.values()}) != 1:
        raise SystemExit(f"series length mismatch in year {year}")
    if kept == 0:
        continue
    kept_total += kept
    for sid, (kind, bits, code, _extract) in meta.items():
        values = vals[sid]
        out = samples_dir / sid / f"nih_{year}_{sid}_n{len(values):07d}.bin"
        with out.open("wb") as fh:
            fh.write(struct.pack("<" + code * len(values), *values))
        index_records.append(
            {
                "dataset_id": "nih_reporter_projects",
                "series_id": sid,
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
                "fiscal_year": year,
                "natural_record_kind": "nih_project",
            }
        )

if not index_records:
    raise SystemExit("no samples produced")

primary_values = sum(r["value_count"] for r in index_records)
primary_bytes = sum(r["sample_size_bytes"] for r in index_records)
stats_out = {
    "dataset_id": "nih_reporter_projects",
    "years": sorted(pages_by_year),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_total,
    "samples": len(index_records),
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_records:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built years={len(pages_by_year)} samples={len(index_records)} rows_kept={kept_total} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
