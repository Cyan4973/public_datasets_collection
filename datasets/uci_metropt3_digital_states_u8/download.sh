#!/usr/bin/env bash
# Acquire, pin, and profile the official CC BY 4.0 UCI MetroPT-3 source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_metropt3_digital_states_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
METADATA_URL="https://archive.ics.uci.edu/api/dataset?id=791"
RIGHTS_URL="https://archive.ics.uci.edu/dataset/791/metropt+3+dataset"
ARCHIVE_URL="https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip"
ARCHIVE="$DOWNLOAD_DIR/metropt3_dataset.zip"
METADATA="$DOWNLOAD_DIR/uci_dataset_791.json"
RIGHTS="$DOWNLOAD_DIR/uci_dataset_791.html"
METADATA_SIZE=9576
METADATA_SHA256="82b91c5ac61d01dadb53299d9be559f748c7e22904a6e4c08e313627d57e50b1"
RIGHTS_SIZE=206466
RIGHTS_SHA256="7181bb85f212ff0dec63b47c15ec17ca5f8f4ca742cbe6316b3a641fc882402e"
ARCHIVE_SIZE=218381995
ARCHIVE_SHA256="aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a"

mkdir -p "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_file() {
  local path="$1" expected_size="$2" expected_sha="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$expected_size" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_sha" ]]
}

validate_metadata() {
  python3 - "$1" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():raise SystemExit(1)
data=json.loads(p.read_text(encoding="utf-8"))
text=json.dumps(data,ensure_ascii=False).lower()
checks={
 "dataset identity":"metropt" in text,
 "doi":"10.24432/c5vw3r" in text,
 "uci id":('"uci_id": 791' in text or '"uci_id":791' in text),
}
failed=[name for name,ok in checks.items() if not ok]
if failed:raise SystemExit(f"UCI metadata validation failed: {failed}")
PY
}

if validate_metadata "$METADATA" && valid_file "$METADATA" "$METADATA_SIZE" "$METADATA_SHA256"; then
  echo "validated existing UCI metadata"
else
  rm -f "$METADATA" "$METADATA.part"
  curl --globoff --fail --silent --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
    --connect-timeout 30 --max-time 240 --user-agent "openzl-public-datasets/1.0" \
    --output "$METADATA.part" "$METADATA_URL"
  validate_metadata "$METADATA.part"
  valid_file "$METADATA.part" "$METADATA_SIZE" "$METADATA_SHA256" || {
    echo "pinned UCI metadata identity mismatch" >&2; exit 1; }
  mv "$METADATA.part" "$METADATA"
fi

validate_rights() {
  python3 - "$1" <<'PY'
import html,re,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():raise SystemExit(1)
text=html.unescape(p.read_text(encoding="utf-8",errors="replace")).lower()
text=re.sub(r"\s+"," ",text)
identity="metropt" in text and ("10.24432/c5vw3r" in text or "dataset/791" in text)
license_evidence=("creative commons attribution 4.0" in text or "cc by 4.0" in text
                  or "cc-by-4.0" in text or "creativecommons.org/licenses/by/4.0" in text)
if not identity or not license_evidence:
 raise SystemExit(f"official UCI page validation failed: identity={identity} cc_by_4={license_evidence}")
PY
}

if validate_rights "$RIGHTS" && valid_file "$RIGHTS" "$RIGHTS_SIZE" "$RIGHTS_SHA256"; then
  echo "validated existing UCI rights page"
else
  rm -f "$RIGHTS" "$RIGHTS.part"
  curl --globoff --fail --silent --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
    --connect-timeout 30 --max-time 240 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets/1.0" --output "$RIGHTS.part" "$RIGHTS_URL"
  validate_rights "$RIGHTS.part"
  valid_file "$RIGHTS.part" "$RIGHTS_SIZE" "$RIGHTS_SHA256" || {
    echo "pinned UCI rights-page identity mismatch" >&2; exit 1; }
  mv "$RIGHTS.part" "$RIGHTS"
fi

if valid_file "$ARCHIVE" "$ARCHIVE_SIZE" "$ARCHIVE_SHA256" && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "reuse existing archive bytes=$(stat -c %s "$ARCHIVE")"
else
  rm -f "$ARCHIVE" "$ARCHIVE.part"
  curl --globoff --fail --silent --show-error --location --retry 5 --retry-all-errors --retry-delay 5 \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 --max-time 1800 \
    --max-filesize 500000000 --user-agent "openzl-public-datasets/1.0" \
    --output "$ARCHIVE.part" "$ARCHIVE_URL"
  valid_file "$ARCHIVE.part" "$ARCHIVE_SIZE" "$ARCHIVE_SHA256" || {
    echo "pinned MetroPT archive identity mismatch" >&2; exit 1; }
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

export ARCHIVE EXTRACT_DIR DISCOVERY_DIR DOWNLOAD_DIR METADATA RIGHTS
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import zipfile


archive=Path(os.environ["ARCHIVE"])
extract_dir=Path(os.environ["EXTRACT_DIR"])
discovery_dir=Path(os.environ["DISCOVERY_DIR"])
download_dir=Path(os.environ["DOWNLOAD_DIR"])
metadata=Path(os.environ["METADATA"])
rights=Path(os.environ["RIGHTS"])


def file_hash(path:Path)->str:
 d=hashlib.sha256()
 with path.open("rb") as h:
  for block in iter(lambda:h.read(1<<20),b""):d.update(block)
 return d.hexdigest()


if not zipfile.is_zipfile(archive):raise SystemExit("MetroPT source is not a ZIP archive")
if archive.stat().st_size!=218_381_995 or file_hash(archive)!="aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a":
 raise SystemExit("pinned MetroPT archive identity changed")

with zipfile.ZipFile(archive) as zf:
 members=[];total=0
 for info in zf.infolist():
  path=PurePosixPath(info.filename)
  if path.is_absolute() or ".." in path.parts:raise SystemExit(f"unsafe ZIP member: {info.filename}")
  total+=info.file_size
  if total>1_000_000_000:raise SystemExit("MetroPT uncompressed archive exceeds 1 GB")
  if not info.is_dir() and path.suffix.lower()==".csv" and "metropt" in path.name.lower():members.append(info)
 if len(members)!=1:raise SystemExit(f"expected one MetroPT CSV, found {[m.filename for m in members]}")
 info=members[0]
 if not 10_000_000 <= info.file_size <= 800_000_000:raise SystemExit(f"CSV size outside bounds: {info.file_size}")
 extract_dir.mkdir(parents=True,exist_ok=True)
 csv_path=extract_dir/"metropt3.csv"
 with zf.open(info) as source,csv_path.open("wb") as destination:shutil.copyfileobj(source,destination,1<<20)

if csv_path.stat().st_size!=218_300_507 or file_hash(csv_path)!="db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24":
 raise SystemExit("pinned MetroPT CSV identity changed")

with csv_path.open("r",encoding="utf-8-sig",newline="") as handle:
 reader=csv.reader(handle)
 try:header=next(reader)
 except StopIteration:raise SystemExit("empty MetroPT CSV")
 header=[name.strip() for name in header]
 if len(header)<10 or len(set(header))!=len(header):raise SystemExit(f"invalid CSV header: {header}")
 unique=[set() for _ in header]
 overflow=[False for _ in header]
 missing=[0 for _ in header]
 rows=0
 for row in reader:
  if not row or all(not value.strip() for value in row):continue
  if len(row)!=len(header):raise SystemExit(f"row {rows+2} has {len(row)} fields, expected {len(header)}")
  rows+=1
  for index,value in enumerate(row):
   value=value.strip()
   if not value:missing[index]+=1;continue
   if not overflow[index]:
    unique[index].add(value)
    if len(unique[index])>256:
     overflow[index]=True;unique[index].clear()
if not 1_000_000 <= rows <= 2_000_000:raise SystemExit(f"unexpected MetroPT row count: {rows}")

profiles=[];candidates=[]
for index,name in enumerate(header):
 values=sorted(unique[index]) if not overflow[index] else []
 integral_values=[];integral=True
 if not overflow[index] and not missing[index]:
  for value in values:
   try:number=float(value);integer=int(number)
   except ValueError:integral=False;break
   if not number.is_integer() or not 0<=integer<=255:integral=False;break
   integral_values.append(integer)
 else:integral=False
 profile={
  "column_index":index,
  "column_name":name,
  "missing_values":missing[index],
  "unique_values_over_256":overflow[index],
  "unique_value_count":None if overflow[index] else len(values),
  "unique_values":values if not overflow[index] else None,
  "complete_integral_u8_candidate":integral,
 }
 profiles.append(profile)
 if integral and index!=0:
  candidates.append({**profile,"integer_values":integral_values})

if len(candidates)<5:raise SystemExit(f"too few integral uint8 candidates: {[p['column_name'] for p in candidates]}")
summary={
 "dataset_id":"uci_metropt3_digital_states_u8",
 "uci_dataset_id":791,
 "doi":"10.24432/C5VW3R",
 "license":"CC BY 4.0",
 "archive_url":"https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip",
 "archive_size_bytes":archive.stat().st_size,
 "archive_sha256":file_hash(archive),
 "metadata_sha256":file_hash(metadata),
 "rights_page_sha256":file_hash(rights),
 "csv_zip_member":info.filename,
 "csv_size_bytes":csv_path.stat().st_size,
 "csv_sha256":file_hash(csv_path),
 "row_count":rows,
 "column_count":len(header),
 "columns":profiles,
 "complete_integral_u8_candidates":candidates,
}
(discovery_dir/"column_profile.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (discovery_dir/"candidate_columns.tsv").open("w",encoding="utf-8",newline="") as h:
 writer=csv.writer(h,delimiter="\t",lineterminator="\n")
 writer.writerow(["column_index","column_name","unique_value_count","integer_values"])
 for row in candidates:writer.writerow([row["column_index"],row["column_name"],row["unique_value_count"],",".join(map(str,row["integer_values"]))])
print(json.dumps({key:value for key,value in summary.items() if key not in {"columns","complete_integral_u8_candidates"}},indent=2,sort_keys=True))
print("candidate_columns="+",".join(row["column_name"] for row in candidates))
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
