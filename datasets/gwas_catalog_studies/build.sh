#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gwas_catalog_studies"
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
import calendar, json, os, re, shutil, struct
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

obj = json.load(open(download_dir / "gwas_catalog_studies.json", encoding="utf-8"))
rows_in = obj["_embedded"][next(iter(obj["_embedded"].keys()))]
meta = {
    "gwas_snp_count_u32": ("uint", 32, "I"),
    "gwas_platform_count_u16": ("uint", 16, "H"),
    "gwas_ancestry_count_u16": ("uint", 16, "H"),
    "gwas_trait_length_u16": ("uint", 16, "H"),
    "gwas_initial_sample_size_length_u16": ("uint", 16, "H"),
    "gwas_replication_sample_size_length_u16": ("uint", 16, "H"),
    "gwas_pubmed_id_u32": ("uint", 32, "I"),
    "gwas_publication_date_u32": ("uint", 32, "I"),
}
vals = {sid: [] for sid in meta}
for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

rows_total = len(rows_in)
rows_skipped = 0

def digits_only(s: str) -> int:
    d = re.sub(r"\D+", "", s or "")
    return int(d) if d else 0

def day_ts(s: str) -> int:
    return calendar.timegm(datetime.strptime(s[:10], "%Y-%m-%d").utctimetuple())

for row in rows_in:
    try:
        pub = row.get("publicationInfo") or {}
        trait = row.get("diseaseTrait") or {}
        vals["gwas_snp_count_u32"].append(int(row.get("snpCount") or 0))
        vals["gwas_platform_count_u16"].append(len(row.get("platforms") or []))
        vals["gwas_ancestry_count_u16"].append(len(row.get("ancestries") or []))
        vals["gwas_trait_length_u16"].append(len(trait.get("trait") or ""))
        vals["gwas_initial_sample_size_length_u16"].append(len(row.get("initialSampleSize") or ""))
        vals["gwas_replication_sample_size_length_u16"].append(len(row.get("replicationSampleSize") or ""))
        vals["gwas_pubmed_id_u32"].append(digits_only(str(pub.get("pubmedId") or "")))
        vals["gwas_publication_date_u32"].append(day_ts(pub.get("publicationDate") or "1970-01-01"))
    except Exception:
        rows_skipped += 1

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "gwas_catalog_studies",
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
    json.dumps({"dataset_id": "gwas_catalog_studies", "rows_total": rows_total, "rows_skipped": rows_skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
