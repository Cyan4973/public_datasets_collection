#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mitbih_arrhythmia_u8"
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
MIN_RECORDS="${MITBIH_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_RECORDS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_root = repo / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["MIN_RECORDS"])

DATASET_ID = "mitbih_arrhythmia_u8"
LEAD_FAMILY = {
    "MLII": "mitbih_mlii_u8", "V1": "mitbih_v1_u8", "V2": "mitbih_v2_u8",
    "V4": "mitbih_v4_u8", "V5": "mitbih_v5_u8",
}

records_file = download_dir / "RECORDS.selected"
if not records_file.exists():
    records_file = download_dir / "RECORDS"
if not records_file.exists():
    raise SystemExit(f"missing record list: {records_file}")
records = [r.strip() for r in records_file.read_text(encoding="utf-8").splitlines() if r.strip()]
if not records:
    raise SystemExit("RECORDS is empty")

# parse headers
record_meta = {}
for rec in records:
    hea = download_dir / f"{rec}.hea"
    dat = download_dir / f"{rec}.dat"
    if not hea.exists() or not dat.exists():
        raise SystemExit(f"missing .hea/.dat for record {rec}")
    lines = [ln.strip() for ln in hea.read_text(encoding="utf-8").splitlines() if ln.strip()]
    h0 = lines[0].split()
    nsig = int(h0[1]); fs = int(float(h0[2])); nsamp = int(h0[3])
    if nsig != 2 or fs != 360:
        raise SystemExit(f"unexpected nsig/fs for {rec}: {nsig}/{fs}")
    leads = []
    for sline in lines[1:1 + nsig]:
        parts = sline.split()
        fmt = int(parts[1].split('/')[0])
        if fmt != 212:
            raise SystemExit(f"unsupported WFDB fmt {parts[1]} in {hea}")
        leads.append(parts[-1])
    if dat.stat().st_size != nsamp * 3:
        raise SystemExit(f"{dat} size mismatch")
    record_meta[rec] = {"nsamp": nsamp, "leads": leads}

# decode fmt-212 -> two 12-bit signed channels -> quantize to unsigned u8
by_family = defaultdict(list)  # family -> [(rec, bytes)]
for rec in records:
    meta = record_meta[rec]
    dat = (download_dir / f"{rec}.dat").read_bytes()
    nsamp = meta["nsamp"]
    c0 = bytearray(nsamp); c1 = bytearray(nsamp)
    j = 0
    for i in range(0, len(dat), 3):
        b0 = dat[i]; b1 = dat[i + 1]; b2 = dat[i + 2]
        s0 = ((b1 & 0x0F) << 8) | b0
        s1 = ((b1 & 0xF0) << 4) | b2
        if s0 >= 2048: s0 -= 4096
        if s1 >= 2048: s1 -= 4096
        # 12-bit signed [-2048,2047] -> unsigned u8 (baseline -> 128)
        c0[j] = (s0 + 2048) >> 4
        c1[j] = (s1 + 2048) >> 4
        j += 1
    if j != nsamp:
        raise SystemExit(f"decoded sample count mismatch for {rec}")
    for buf, lead in ((c0, meta["leads"][0]), (c1, meta["leads"][1])):
        fam = LEAD_FAMILY.get(lead)
        if fam is None:
            continue
        by_family[fam].append((rec, bytes(buf)))

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for fam, items in sorted(by_family.items()):
    qualifying = [(rec, b) for (rec, b) in items
                  if len(b) >= min_records and len(set(b)) > 1]
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for rec, b in qualifying:
        out = samples_dir / fam / f"{rec}_n{len(b):07d}.bin"
        out.write_bytes(b)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(b),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "record": rec,
            "natural_record_kind": "ecg_record_lead",
        })
    fam_summary[fam] = len(qualifying)

if len(fam_summary) < 2:
    raise SystemExit(f"only {len(fam_summary)} families qualified: {fam_summary}")

counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "records": len(records),
    "primary_values": sum(counts),
    "primary_sample_bytes": sum(r["sample_size_bytes"] for r in index_rows),
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built families={fam_summary} samples={len(index_rows)} "
      f"primary_values={sum(counts)} median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
