#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gdc_cases"
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
MIN_SITE_RECORDS="${GDC_MIN_SITE_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_SITE_RECORDS
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
min_site = int(os.environ["MIN_SITE_RECORDS"])

DATASET_ID = "gdc_cases"
# Non-informative partition labels (catch-all bins, not biological sites).
DROP_SITES = {"unknown", "not reported", ""}

# family -> (source group, key, numeric_kind, bit_width, struct code, lo, hi)
#   group: "diagnoses" (first diagnosis) or "demographic"
FAMILIES = {
    "gdc_age_at_diagnosis_days_u32":   ("diagnoses",   "age_at_diagnosis",       "uint", 32, "I", 0, 0xFFFFFFFF),
    "gdc_days_to_last_follow_up_i32":  ("diagnoses",   "days_to_last_follow_up",  "int", 32, "i", -2_000_000_000, 2_000_000_000),
    "gdc_year_of_diagnosis_u16":       ("diagnoses",   "year_of_diagnosis",      "uint", 16, "H", 1850, 2100),
    "gdc_year_of_birth_u16":           ("demographic", "year_of_birth",          "uint", 16, "H", 1850, 2100),
    "gdc_days_to_death_i32":           ("demographic", "days_to_death",           "int", 32, "i", -2_000_000_000, 2_000_000_000),
}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

by_field_site = {fam: defaultdict(list) for fam in FAMILIES}
seen = set()
cases = 0
dups = 0

def coerce(v, lo, hi):
    if v is None:
        return None
    try:
        iv = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return iv if lo <= iv <= hi else None

for path in sorted(pages_dir.glob("page_*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        hits = payload["data"]["hits"]
    except Exception:
        continue
    for hit in hits:
        cid = hit.get("case_id") or hit.get("id")
        if cid is None or cid in seen:
            dups += cid is not None
            continue
        seen.add(cid)
        cases += 1
        site = (hit.get("primary_site") or "").strip().lower()
        if site in DROP_SITES:
            continue
        diags = hit.get("diagnoses") or []
        diag0 = diags[0] if diags and isinstance(diags, list) else {}
        demog = hit.get("demographic") or {}
        for fam, (grp, key, _k, _b, _c, lo, hi) in FAMILIES.items():
            src = diag0 if grp == "diagnoses" else demog
            iv = coerce(src.get(key), lo, hi)
            if iv is not None:
                by_field_site[fam][site].append(iv)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

def slug(site: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in site).strip("_")

index_rows = []
fam_summary = {}
for fam, (grp, key, kind, bits, code, _lo, _hi) in FAMILIES.items():
    sites = by_field_site[fam]
    qualifying = sorted(s for s, vals in sites.items()
                        if len(vals) >= min_site and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for s in qualifying:
        values = sites[s]
        out = samples_dir / fam / f"{fam}_{slug(s)}_n{len(values):06d}.bin"
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
            "primary_site": s,
            "natural_record_kind": "gdc_case",
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
    "cases_unique": cases,
    "duplicates_dropped": dups,
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
    f"built families={fam_summary} samples={len(index_rows)} unique_cases={cases} "
    f"dups={dups} primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
