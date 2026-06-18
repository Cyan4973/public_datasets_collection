#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_fsd_2024q1_q4_numeric_values_i64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'resource\tstatus\tdetail\n' > "$FAILURES"
printf 'local_name\turl\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="https://www.sec.gov/files/dera/data/financial-statement-data-sets"
FILES=(2024q1.zip 2024q2.zip 2024q3.zip 2024q4.zip)
USER_AGENT="${SEC_USER_AGENT:-openzl-public-datasets/1.0 contact=local}"

for name in "${FILES[@]}"; do
  url="$BASE_URL/$name"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%s\n' "$name" "$url" >> "$PLAN"
  if [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch url=$url"
    if ! curl -L --fail --show-error --retry 3 --retry-delay 5 -A "$USER_AGENT" -o "$target.tmp" "$url"; then
      printf '%s\tfailed\tcurl_failed\n' "$name" >> "$FAILURES"
      rm -f "$target.tmp"
      continue
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit $target"
  fi
  if ! python3 - "$target" <<'PY'
import csv, sys, zipfile
path = sys.argv[1]
required = {"uom", "value"}
with zipfile.ZipFile(path) as zf:
    num_members = [name for name in zf.namelist() if name.lower().split("/")[-1] in {"num.txt", "num.tsv"}]
    if not num_members:
        raise SystemExit("zip contains no SEC num member")
    with zf.open(sorted(num_members)[0]) as fh:
        header = next(csv.reader([fh.readline().decode("utf-8", errors="replace")], delimiter="\t"))
missing = sorted(required - set(header))
if missing:
    raise SystemExit(f"missing required columns: {missing}")
print(f"validated_zip={path} member={sorted(num_members)[0]}")
PY
  then
    printf '%s\tfailed\tsemantic_validation_failed\n' "$name" >> "$FAILURES"
  fi
done

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
