#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ptbxl_physionet"
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
from array import array
import json
import os
from pathlib import Path
import re
import shutil
import sys

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
records_path = download_dir / "RECORDS.selected"
out_dir = samples_dir / "ptbxl_ecg_lr_12x1000"
canonical_leads = ['I', 'II', 'III', 'AVR', 'AVL', 'AVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6']
gain_re = re.compile(r'^(?P<gain>[+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\((?P<baseline>-?\d+)\))?(?:/(?P<units>\S+))?$')
little = sys.byteorder == "little"

def parse_signal_line(line: str):
    parts = line.split()
    if len(parts) < 3:
        raise SystemExit(f"bad PTB-XL signal line: {line}")
    fmt_match = re.match(r'^(?P<fmt>\d+)', parts[1])
    if not fmt_match:
        raise SystemExit(f"bad WFDB format token: {parts[1]}")
    fmt = int(fmt_match.group('fmt'))
    if fmt != 16:
        raise SystemExit(f"unsupported WFDB format {fmt}")
    gain = 1.0
    baseline = 0
    units = None
    m = gain_re.match(parts[2])
    if m:
        gain = float(m.group('gain'))
        if m.group('baseline') is not None:
            baseline = int(m.group('baseline'))
        elif len(parts) > 4:
            baseline = int(parts[4])
        units = m.group('units')
    else:
        if parts[2] != '0':
            raise SystemExit(f"could not parse ADC gain token: {parts[2]}")
        if len(parts) > 4:
            baseline = int(parts[4])
    return {
        "dat_name": parts[0],
        "gain": gain,
        "baseline": baseline,
        "units": units,
        "lead": parts[-1].upper(),
    }

def parse_header(path: Path):
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
      raise SystemExit(f"empty header: {path}")
    first = lines[0].split()
    if len(first) < 4:
      raise SystemExit(f"bad first header line: {path}")
    nsig = int(first[1])
    fs = int(float(first[2].split('/')[0]))
    nsamp = int(first[3])
    if nsig != 12 or fs != 100 or nsamp != 1000:
      raise SystemExit(f"unexpected PTB-XL shape in {path.name}")
    sig_lines = lines[1:1+nsig]
    signals = [parse_signal_line(line) for line in sig_lines]
    leads = [sig["lead"] for sig in signals]
    if leads != canonical_leads:
      raise SystemExit(f"lead order mismatch in {path.name}: {leads}")
    dat_names = {sig["dat_name"] for sig in signals}
    if len(dat_names) != 1:
      raise SystemExit(f"expected one shared .dat file in {path.name}")
    return {"signals": signals, "nsig": nsig, "nsamp": nsamp, "dat_name": next(iter(dat_names))}

if not records_path.exists():
    raise SystemExit(f"missing selection file: {records_path}")
records = [ln.strip() for ln in records_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
if not records:
    raise SystemExit("empty RECORDS.selected")
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)

inventory = []
rows = []
for idx, rel in enumerate(records, start=1):
    hea_path = download_dir / f"{rel}.hea"
    dat_path = download_dir / f"{rel}.dat"
    if not hea_path.exists() or not dat_path.exists():
        raise SystemExit(f"missing .hea/.dat pair for {rel}")
    meta = parse_header(hea_path)
    raw = dat_path.read_bytes()
    expected_bytes = meta["nsig"] * meta["nsamp"] * 2
    if len(raw) != expected_bytes:
        raise SystemExit(f"size mismatch for {dat_path}")
    digital = array('h')
    digital.frombytes(raw)
    if not little:
        digital.byteswap()
    physical = array('f')
    for lead_idx, sig in enumerate(meta["signals"]):
        gain = sig["gain"] if sig["gain"] not in (0.0, -0.0) else 1.0
        baseline = sig["baseline"]
        for pos in range(lead_idx, len(digital), meta["nsig"]):
            value = (digital[pos] - baseline) / gain
            physical.append(float(value))
    if not little:
        physical.byteswap()
    out = out_dir / f"{Path(rel).name}_12x1000.bin"
    with out.open("wb") as fh:
        physical.tofile(fh)
    rows.append({
        "dataset_id": "ptbxl_physionet",
        "series_id": "ptbxl_ecg_lr_12x1000",
        "sample_path": str(out.relative_to(repo / data_dir)),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": out.stat().st_size,
        "value_count": 12 * 1000,
    })
    inventory.append((rel, out.name, out.stat().st_size, 12 * 1000))

filter_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("record\toutput_file\tbytes\tvalues\n")
    for row in inventory:
        fh.write("\t".join(str(x) for x in row) + "\n")
index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
