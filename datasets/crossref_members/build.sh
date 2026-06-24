#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_members"
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
MIN_RECORDS="${CROSSREF_MIN_LETTER_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_RECORDS
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
min_records = int(os.environ["MIN_RECORDS"])

DATASET_ID = "crossref_members"
# family -> counts key
FAMILIES = {
    "crossref_member_total_dois_u32": "total-dois",
    "crossref_member_current_dois_u32": "current-dois",
    "crossref_member_backfile_dois_u32": "backfile-dois",
}
U32_MAX = 0xFFFFFFFF

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

by_fam_letter = {f: defaultdict(list) for f in FAMILIES}
members = 0
seen = set()

for path in sorted(pages_dir.glob("page_*.json")):
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["message"]["items"]
    except Exception:
        continue
    for m in items:
        mid = m.get("id")
        if mid in seen:
            continue
        seen.add(mid)
        members += 1
        name = (m.get("primary-name") or "").strip()
        if not name or not name[0].isascii() or not name[0].isalpha():
            continue
        letter = name[0].upper()
        counts = m.get("counts") or {}
        for fam, key in FAMILIES.items():
            v = counts.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            iv = int(v)
            if 0 <= iv <= U32_MAX:
                by_fam_letter[fam][letter].append(iv)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for fam in FAMILIES:
    letters = by_fam_letter[fam]
    qualifying = sorted(c for c, vals in letters.items()
                        if len(vals) >= min_records and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for c in qualifying:
        vals = letters[c]
        out = samples_dir / fam / f"{fam}_{c}_n{len(vals):06d}.bin"
        out.write_bytes(struct.pack("<" + "I" * len(vals), *vals))
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "name_initial": c,
            "natural_record_kind": "crossref_member",
        })
    fam_summary[fam] = len(qualifying)

if len(fam_summary) < 2:
    raise SystemExit(f"only {len(fam_summary)} families qualified: {fam_summary}")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts_list = sorted(r["value_count"] for r in index_rows)
median = counts_list[len(counts_list) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "members": members,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts_list[0],
    "max_value_count": counts_list[-1],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} members={members} "
    f"primary_values={primary_values} median={median} range=[{counts_list[0]},{counts_list[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
