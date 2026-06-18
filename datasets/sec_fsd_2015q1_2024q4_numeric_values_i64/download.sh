#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_fsd_2015q1_2024q4_numeric_values_i64"
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
FILES=()
for year in {2015..2024}; do
  for quarter in 1 2 3 4; do
    FILES+=("${year}q${quarter}.zip")
  done
done
if [[ -z "${SEC_USER_AGENT:-}" || "$SEC_USER_AGENT" != *"@"* ]]; then
  cat >&2 <<'EOF'
SEC requires an identifying User-Agent with contact information.
Set SEC_USER_AGENT to a project/name plus email before running, for example:

  SEC_USER_AGENT='openzl-public-datasets/1.0 contact=you@example.org' bash datasets/sec_fsd_2015q1_2024q4_numeric_values_i64/download.sh
EOF
  exit 2
fi
USER_AGENT="$SEC_USER_AGENT"
ALT_2024_DIR="$REPO_ROOT/$DATA_DIR/downloads/sec_fsd_2024q1_q4_numeric_values_i64"
RATE_LIMIT_SECONDS="${SEC_RATE_LIMIT_SECONDS:-1}"

for name in "${FILES[@]}"; do
  url="$BASE_URL/$name"
  target="$DOWNLOAD_DIR/$name"
  printf '%s\t%s\n' "$name" "$url" >> "$PLAN"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run url=$url"
    continue
  fi
  alt_2024="$ALT_2024_DIR/$name"
  if [[ ! -f "$target" && "$name" == 2024q*.zip && -f "$alt_2024" ]]; then
    echo "reuse_existing_2024_source $alt_2024"
    cp -p "$alt_2024" "$target"
  fi
  if [[ ! -f "$target" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    echo "fetch url=$url"
    http_code="$(
      curl -L --silent --show-error \
        --retry 3 --retry-delay 10 --retry-all-errors \
        --connect-timeout 20 \
        -A "$USER_AGENT" \
        -o "$target.tmp" \
        -w '%{http_code}' \
        "$url" || true
    )"
    if [[ "$http_code" != "200" ]]; then
      printf '%s\tfailed\thttp_%s\n' "$name" "$http_code" >> "$FAILURES"
      rm -f "$target.tmp"
      if [[ "$http_code" == "403" ]]; then
        echo "SEC returned HTTP 403 for $url; stopping to avoid repeated blocked requests." >&2
        echo "Use a real SEC_USER_AGENT with email contact and retry later if the client/IP is temporarily blocked." >&2
        break
      fi
      continue
    fi
    mv "$target.tmp" "$target"
  else
    echo "cache_hit $target"
  fi
  if ! python3 - "$target" <<'PY'
import csv, sys, zipfile
path = sys.argv[1]
required = {"tag", "uom", "value"}
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
  sleep "$RATE_LIMIT_SECONDS"
done

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
