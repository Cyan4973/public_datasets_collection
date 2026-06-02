#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mitbih_arrhythmia_physionet"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import json
import os
from array import array
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
records_file = download_dir / "RECORDS.selected"
if not records_file.exists():
    records_file = download_dir / "RECORDS"
if not records_file.exists():
    raise SystemExit(f"missing record list: {records_file}")
records = [r.strip() for r in records_file.read_text(encoding="utf-8").splitlines() if r.strip()]
if not records:
    raise SystemExit("RECORDS is empty")

record_meta = {}
lead_names = set()
for rec in records:
    hea = download_dir / f"{rec}.hea"
    dat = download_dir / f"{rec}.dat"
    if not hea.exists() or not dat.exists():
        raise SystemExit(f"missing .hea/.dat for record {rec}")
    lines = [ln.strip() for ln in hea.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"empty header for {rec}")
    h0 = lines[0].split()
    if len(h0) < 4:
        raise SystemExit(f"bad first header line in {hea}")
    nsig = int(h0[1])
    fs = int(float(h0[2]))
    nsamp = int(h0[3])
    if nsig != 2:
        raise SystemExit(f"expected 2 signals for {rec}, got {nsig}")
    if fs != 360:
        raise SystemExit(f"expected fs=360 for {rec}, got {fs}")
    sig_lines = lines[1:1 + nsig]
    if len(sig_lines) != nsig:
        raise SystemExit(f"header signal line mismatch for {rec}")
    leads = []
    for sline in sig_lines:
        parts = sline.split()
        if len(parts) < 2:
            raise SystemExit(f"bad signal line in {hea}: {sline}")
        fmt_tok = parts[1]
        fmt = int(fmt_tok.split('/')[0])
        if fmt != 212:
            raise SystemExit(f"unsupported WFDB fmt {fmt_tok} in {hea}; expected 212")
        lead = parts[-1]
        leads.append(lead)
        lead_names.add(lead)
    expected_bytes = nsamp * 3
    actual_bytes = dat.stat().st_size
    if actual_bytes != expected_bytes:
        raise SystemExit(f"{dat} size mismatch: expected {expected_bytes}, got {actual_bytes}")
    record_meta[rec] = {"nsamp": nsamp, "leads": leads}

lead_to_family = {
    "MLII": "mitbih_mlii_1d_var",
    "V1": "mitbih_v1_1d_var",
    "V2": "mitbih_v2_1d_var",
    "V4": "mitbih_v4_1d_var",
    "V5": "mitbih_v5_1d_var",
}
def sanitize_lead(lead: str) -> str:
    s = ''.join(ch.lower() if ch.isalnum() else '_' for ch in lead)
    while '__' in s:
        s = s.replace('__', '_')
    return s.strip('_')
for lead in sorted(lead_names):
    if lead not in lead_to_family:
        lead_to_family[lead] = f"mitbih_{sanitize_lead(lead)}_1d_var"

for fam in sorted(set(lead_to_family.values())):
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)

inventory = []
rows = []
for rec in records:
    meta = record_meta[rec]
    dat = (download_dir / f"{rec}.dat").read_bytes()
    nsamp = meta["nsamp"]
    leads = meta["leads"]
    c0 = array('h')
    c1 = array('h')
    for i in range(0, len(dat), 3):
        b0 = dat[i]
        b1 = dat[i + 1]
        b2 = dat[i + 2]
        s0 = ((b1 & 0x0F) << 8) | b0
        s1 = ((b1 & 0xF0) << 4) | b2
        if s0 >= 2048:
            s0 -= 4096
        if s1 >= 2048:
            s1 -= 4096
        c0.append(s0)
        c1.append(s1)
    if len(c0) != nsamp or len(c1) != nsamp:
        raise SystemExit(f"decoded sample count mismatch for {rec}")
    for values, lead in ((c0, leads[0]), (c1, leads[1])):
        family = lead_to_family[lead]
        out = samples_dir / family / f"{rec}_1d_n{nsamp}.bin"
        with out.open("wb") as fh:
            values.tofile(fh)
        rows.append({
            "dataset_id": "mitbih_arrhythmia_physionet",
            "series_id": family,
            "sample_path": str(out.relative_to(repo / data_dir)),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": out.stat().st_size,
            "value_count": nsamp,
        })
        inventory.append((rec, family, lead, nsamp, out.stat().st_size, out.name))

filter_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("record\tseries_id\tlead\tsamples\tbytes\toutput_file\n")
    for row in inventory:
        fh.write("\t".join(str(x) for x in row) + "\n")
index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
