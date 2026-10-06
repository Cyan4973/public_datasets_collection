#!/usr/bin/env bash
# Metadata-only discovery: documents how sources.tsv was resolved from the
# Zenodo record API. Not part of the download/build/verify contract.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hamsci_grape1_wwv10_doppler_frequency_f64"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-hamsci-grape1-discovery/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

curl --fail --silent --show-error --location \
  --retry 8 --retry-delay 15 --retry-all-errors --max-time 300 --max-filesize 20000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$OUT_DIR/record_6590283.json.part" "https://zenodo.org/api/records/6590283"
mv "$OUT_DIR/record_6590283.json.part" "$OUT_DIR/record_6590283.json"

# Tally of the whole record by receiver type and beacon (what is excluded).
python3 - "$OUT_DIR/record_6590283.json" <<'PY'
import collections
import json
import re
import sys

record = json.load(open(sys.argv[1], encoding="utf-8"))
tally = collections.Counter()
size = collections.Counter()
for item in record["files"]:
    match = re.search(r"_(G1|S1)_[A-Za-z0-9]+_FRQ_([A-Za-z0-9]+)\.csv\.gz$", item["key"])
    label = f"{match.group(1)}/{match.group(2)}" if match else "other"
    tally[label] += 1
    size[label] += item["size"]
for label in sorted(tally):
    print(f"record_files receiver/beacon={label} files={tally[label]} bytes={size[label]}")
related = record["metadata"].get("related_identifiers", [])
print(f"related_identifiers={related}")
PY

python3 "$RECIPE_DIR/scripts/grape_sources.py" select "$OUT_DIR/record_6590283.json" "$OUT_DIR/sources.discovered.tsv"
if diff <(cut -f1-10 "$RECIPE_DIR/sources.tsv") <(cut -f1-10 "$OUT_DIR/sources.discovered.tsv") > "$OUT_DIR/sources.diff"; then
  echo "pinned sources.tsv matches the live record selection (columns 1-10)"
else
  echo "WARNING: pinned sources.tsv differs from the live selection; see $OUT_DIR/sources.diff"
fi
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
