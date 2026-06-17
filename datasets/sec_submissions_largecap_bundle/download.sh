#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_submissions_largecap_bundle"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_TSV="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

ISSUERS_FILE="${ISSUERS_FILE_OVERRIDE:-$REPO_ROOT/datasets/sec_submissions_largecap_bundle/issuers.tsv}"
USER_AGENT="${SEC_USER_AGENT:-openzl-public-datasets/1.0 contact=local}"
FORCE_DOWNLOAD="${FORCE_DOWNLOAD:-0}"
failure_count=0

cat >"$FAIL_TSV" <<'EOF'
issuer	cik	url	reason
EOF

fetch_one() {
  local issuer="$1"
  local cik="$2"
  local out="$DOWNLOAD_DIR/${issuer}.json"
  local tmp="$out.tmp"
  local url="https://data.sec.gov/submissions/CIK${cik}.json"

  if [ "$FORCE_DOWNLOAD" != "1" ] && [ -s "$out" ]; then
    echo "[$(date -Is)] cache_hit issuer=$issuer cik=$cik path=$out"
    return 0
  fi

  echo "[$(date -Is)] fetch issuer=$issuer cik=$cik url=$url"
  if ! curl --globoff -fL --retry 3 --retry-delay 2 -A "$USER_AGENT" -o "$tmp" "$url"; then
    echo -e "${issuer}\t${cik}\t${url}\tcurl_failed" >>"$FAIL_TSV"
    rm -f "$tmp"
    failure_count=$((failure_count + 1))
    return 0
  fi

  if ! python3 - "$tmp" <<'PY'; then
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
assert isinstance(obj, dict)
assert obj.get("filings", {}).get("recent", {}).get("accessionNumber") is not None
PY
    echo -e "${issuer}\t${cik}\t${url}\tbad_payload" >>"$FAIL_TSV"
    rm -f "$tmp"
    failure_count=$((failure_count + 1))
    return 0
  fi

  mv "$tmp" "$out"
  echo "[$(date -Is)] ok issuer=$issuer path=$out"
}

while IFS=$'\t' read -r issuer cik; do
  if [ "$issuer" = "issuer" ]; then
    continue
  fi
  fetch_one "$issuer" "$cik"
done <"$ISSUERS_FILE"

echo "[$(date -Is)] download done dataset=$DATASET_ID failure_count=$failure_count"
exit "$failure_count"
