#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_submissions_largecap_bundle"
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
export ISSUERS_FILE="${ISSUERS_FILE_OVERRIDE:-$REPO_ROOT/staging/sec_submissions_largecap_bundle/issuers.tsv}"

python3 - <<'PY'
from __future__ import annotations
import array
import csv
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
issuers_file = Path(os.environ["ISSUERS_FILE"])
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

issuers = []
with issuers_file.open(encoding="utf-8") as fh:
    reader = csv.DictReader(fh, delimiter="\t")
    for row in reader:
        issuers.append((row["issuer"], row["cik"]))

series_defs = [
    {"series_id": "sec_submission_form_code", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "sec_submission_size", "array_type": "I", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
    {"series_id": "sec_submission_acceptance_timestamp", "array_type": "Q", "numeric_kind": "uint", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "sec_submission_xbrl_flag", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "sec_submission_inline_xbrl_flag", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "sec_submission_filing_date_ordinal", "array_type": "I", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]

for s in series_defs:
    d = samples_dir / s["series_id"]
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

payloads = {}
all_forms: set[str] = set()
for issuer, cik in issuers:
    path = download_dir / f"{issuer}.json"
    if not path.exists():
        raise SystemExit(f"missing download payload for {issuer}: {path}")
    obj = json.load(open(path, encoding="utf-8"))
    payloads[issuer] = obj
    for form in obj["filings"]["recent"].get("form", []):
        if form:
            all_forms.add(str(form))

form_code = {form: idx + 1 for idx, form in enumerate(sorted(all_forms))}
with (filter_dir / "form_codebook.tsv").open("w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["form", "code"])
    for form, code in form_code.items():
        w.writerow([form, code])

records = []
with (filter_dir / "issuer_stats.tsv").open("w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["issuer", "cik", "row_count", "kept_count", "skipped_count", "distinct_forms"])
    for issuer, cik in issuers:
        recent = payloads[issuer]["filings"]["recent"]
        row_count = len(recent.get("accessionNumber", []))
        kept = 0
        skipped = 0
        vals = {s["series_id"]: [] for s in series_defs}

        zipped = zip(
            recent.get("form", []),
            recent.get("size", []),
            recent.get("acceptanceDateTime", []),
            recent.get("isXBRL", []),
            recent.get("isInlineXBRL", []),
            recent.get("filingDate", []),
        )
        for form, size, acceptance, is_xbrl, is_inline, filing_date in zipped:
            try:
                dt_filed = datetime.strptime(filing_date, "%Y-%m-%d").date()
                accepted_dt = datetime.strptime(acceptance, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc)
                code = form_code[str(form or "")]
                vals["sec_submission_form_code"].append(code)
                vals["sec_submission_size"].append(int(size))
                vals["sec_submission_acceptance_timestamp"].append(int(accepted_dt.timestamp()))
                vals["sec_submission_xbrl_flag"].append(1 if int(is_xbrl) else 0)
                vals["sec_submission_inline_xbrl_flag"].append(1 if int(is_inline) else 0)
                vals["sec_submission_filing_date_ordinal"].append(dt_filed.toordinal())
                kept += 1
            except Exception:
                skipped += 1

        w.writerow([issuer, cik, row_count, kept, skipped, len(set(recent.get("form", [])))])

        for s in series_defs:
            arr = array.array(s["array_type"], vals[s["series_id"]])
            if arr.itemsize > 1 and os.sys.byteorder != "little":
                arr.byteswap()
            out = samples_dir / s["series_id"] / f"{issuer}.bin"
            with out.open("wb") as ofh:
                ofh.write(arr.tobytes())
            records.append({
                "dataset_id": "sec_submissions_largecap_bundle",
                "series_id": s["series_id"],
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": s["numeric_kind"],
                "bit_width": s["bit_width"],
                "endianness": s["endianness"],
                "element_size_bytes": s["element_size_bytes"],
                "sample_size_bytes": out.stat().st_size,
                "value_count": len(vals[s["series_id"]]),
                "issuer": issuer,
                "cik": cik,
            })

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in records:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

if not records:
    raise SystemExit("no SEC large-cap submission samples produced")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"

