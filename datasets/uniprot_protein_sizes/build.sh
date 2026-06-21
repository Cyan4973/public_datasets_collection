#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uniprot_protein_sizes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_PROTEINS_PER_ORG="${UNIPROT_MIN_PROTEINS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_PROTEINS_PER_ORG
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_proteins = int(os.environ["MIN_PROTEINS_PER_ORG"])

src = download_dir / "uniprot_protein_sizes.tsv.gz"
if not src.is_file():
    raise SystemExit(f"missing {src}")

# family series_id -> (numeric_kind, bit_width, struct_code, max_value)
FAMILIES = {
    "uniprot_length_u16": ("uint", 16, "H", 0xFFFF),
    "uniprot_mass_u32": ("uint", 32, "I", 0xFFFFFFFF),
}
# per organism: {"uniprot_length_u16": [...], "uniprot_mass_u32": [...]}
by_org_len = defaultdict(list)
by_org_mass = defaultdict(list)
seen = set()

with gzip.open(src, "rt", encoding="utf-8") as fh:
    header = fh.readline().rstrip("\n").split("\t")
    idx = {name: i for i, name in enumerate(header)}
    i_acc = idx.get("Entry", 0)
    i_len = idx.get("Length", 1)
    i_mass = idx.get("Mass", 2)
    i_org = idx.get("Organism (ID)", 3)
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) <= max(i_acc, i_len, i_mass, i_org):
            continue
        acc = parts[i_acc]
        if not acc or acc in seen:
            continue
        seen.add(acc)
        org = parts[i_org].strip()
        if not org:
            continue
        raw_len = parts[i_len].strip()
        raw_mass = parts[i_mass].strip().replace(",", "")
        if raw_len:
            try:
                lv = int(raw_len)
                if 0 <= lv <= 0xFFFF:
                    by_org_len[org].append(lv)
            except ValueError:
                pass
        if raw_mass:
            try:
                mv = int(raw_mass)
                if 0 <= mv <= 0xFFFFFFFF:
                    by_org_mass[org].append(mv)
            except ValueError:
                pass

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

# an organism qualifies if it has >= min_proteins lengths
qualifying = sorted(org for org, vals in by_org_len.items() if len(vals) >= min_proteins)
if len(qualifying) < 5:
    raise SystemExit(f"only {len(qualifying)} organisms with >= {min_proteins} proteins")

index_rows = []
fam_summary = defaultdict(int)
for fam, (kind, bits, code, _maxv) in FAMILIES.items():
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    source = by_org_len if fam == "uniprot_length_u16" else by_org_mass
    for org in qualifying:
        values = source.get(org, [])
        if len(values) < min_proteins:
            continue
        if len(set(values)) <= 1:
            continue
        out = samples_dir / fam / f"org{org}_n{len(values):07d}.bin"
        with out.open("wb") as wf:
            wf.write(struct.pack("<" + code * len(values), *values))
        index_rows.append({
            "dataset_id": "uniprot_protein_sizes",
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
            "organism_id": org,
            "natural_record_kind": "uniprot_protein",
        })
        fam_summary[fam] += 1

if not index_rows:
    raise SystemExit("no samples produced")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
stats = {
    "dataset_id": "uniprot_protein_sizes",
    "families": dict(fam_summary),
    "qualifying_organisms": len(qualifying),
    "samples": len(index_rows),
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built families={dict(fam_summary)} organisms={len(qualifying)} samples={len(index_rows)} primary_values={primary_values}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
