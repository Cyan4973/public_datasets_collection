#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gdc_somatic_mutations"
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
MIN_CHR_RECORDS="${GDC_MIN_CHR_RECORDS:-5000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_CHR_RECORDS
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
min_chr = int(os.environ["MIN_CHR_RECORDS"])

DATASET_ID = "gdc_somatic_mutations"
FAMILY = "gdc_ssm_position_u32"
U32_MAX = 0xFFFFFFFF
VALID = {f"chr{i}" for i in range(1, 23)} | {"chrX", "chrY"}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

def norm_chrom(c: str) -> str | None:
    c = (c or "").strip()
    if not c.lower().startswith("chr"):
        c = "chr" + c
    c = "chr" + c[3:].upper() if c[3:].upper() in ("X", "Y") else "chr" + c[3:]
    return c if c in VALID else None

by_chrom = defaultdict(list)
rows_total = 0
rows_bad = 0

for path in sorted(pages_dir.glob("*_c*.json")):
    try:
        hits = json.loads(path.read_text(encoding="utf-8"))["data"]["hits"]
    except Exception:
        continue
    for hit in hits:
        rows_total += 1
        chrom = norm_chrom(hit.get("chromosome"))
        pos = hit.get("start_position")
        if chrom is None or not isinstance(pos, int) or not (0 < pos <= U32_MAX):
            rows_bad += 1
            continue
        by_chrom[chrom].append(pos)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
fam_dir = samples_dir / FAMILY
fam_dir.mkdir(parents=True, exist_ok=True)

def chrom_key(c: str):
    tail = c[3:]
    return (0, int(tail)) if tail.isdigit() else (1, {"X": 0, "Y": 1}.get(tail, 9))

index_rows = []
qualifying = sorted((c for c, v in by_chrom.items()
                     if len(v) >= min_chr and len(set(v)) > 1), key=chrom_key)
if len(qualifying) < 5:
    raise SystemExit(f"only {len(qualifying)} chromosomes >= {min_chr} records: {qualifying}")

for c in qualifying:
    values = sorted(by_chrom[c])  # canonical ascending genomic order
    out = fam_dir / f"{FAMILY}_{c}_n{len(values):07d}.bin"
    out.write_bytes(struct.pack("<" + "I" * len(values), *values))
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(values),
        "sample_geometry": "sequence",
        "sample_rank": 1,
        "chromosome": c,
        "natural_record_kind": "gdc_simple_somatic_mutation",
    })

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": {FAMILY: len(index_rows)},
    "samples": len(index_rows),
    "rows_total": rows_total,
    "rows_bad": rows_bad,
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
    f"built family={FAMILY} samples={len(index_rows)} rows_total={rows_total} bad={rows_bad} "
    f"primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
