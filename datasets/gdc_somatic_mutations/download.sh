#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gdc_somatic_mutations"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# GDC simple somatic mutations (open). One family: genomic start_position, one sample per
# chromosome -- FULL pull (every mutation). To cover whole chromosomes without GDC's deep
# `from` limit, we use keyset pagination: always from=0, advancing a `start_position >=
# cursor` filter page by page. Only chromosome + start_position are projected.
API="https://api.gdc.cancer.gov/ssms"
SIZE="${GDC_PAGE_SIZE:-5000}"
SAFETY_MAX="${GDC_MAX_PER_CHR:-5000000}"   # runaway guard only; full pull by default
SLEEP="${GDC_SLEEP:-0.5}"                   # inter-request delay (raise if rate-limited)
CHROMS="${GDC_CHROMS:-chr1 chr2 chr3 chr4 chr5 chr6 chr7 chr8 chr9 chr10 chr11 chr12 chr13 chr14 chr15 chr16 chr17 chr18 chr19 chr20 chr21 chr22 chrX chrY}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

# Drop stale page files from the earlier capped (position-sorted) run; this full keyset
# pull uses a different naming scheme and must not be mixed with the old biased pages.
find "$PAGES_DIR" -maxdepth 1 -type f -name '*_p*.json' -delete 2>/dev/null || true

# fetch one page for chrom with start_position >= cursor; echoes "<hits> <last_pos> <total>"
fetch_page() {
  local chrom="$1" cursor="$2" out="$3"
  local filt="{\"op\":\"and\",\"content\":[{\"op\":\"in\",\"content\":{\"field\":\"chromosome\",\"value\":[\"$chrom\"]}},{\"op\":\">=\",\"content\":{\"field\":\"start_position\",\"value\":$cursor}}]}"
  curl --globoff -fsSL --retry 4 --retry-delay 3 --max-time 180 \
    -A "$UA" -H "Accept: application/json" -G \
    --data-urlencode "filters=$filt" \
    --data-urlencode "fields=chromosome,start_position" \
    --data-urlencode "sort=start_position:asc" \
    --data-urlencode "size=$SIZE" \
    --data-urlencode "from=0" \
    -o "$out" "$API"
  python3 - "$out" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    hits = d["data"]["hits"]; total = d["data"]["pagination"]["total"]
    last = max((h.get("start_position") or 0) for h in hits) if hits else 0
except Exception as e:
    print(f"PARSE_ERROR {e}", file=sys.stderr); sys.exit(3)
print(f"{len(hits)} {int(last)} {int(total)}")
PY
}

read_cached() {  # out -> echoes "<hits> <last_pos>"
  python3 - "$1" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8")); hits = d["data"]["hits"]
    last = max((h.get("start_position") or 0) for h in hits) if hits else 0
    print(f"{len(hits)} {int(last)}")
except Exception:
    print("0 0")
PY
}

# ---- fail-fast page-0 guard on the first chromosome ----------------------------------
FIRST_CHR="${CHROMS%% *}"
PROBE="$(printf '%s/%s_c%012d.json' "$PAGES_DIR" "$FIRST_CHR" 0)"
if [ ! -s "$PROBE" ]; then
  echo "probe chrom=$FIRST_CHR cursor=0"
  if ! read -r hits last total < <(fetch_page "$FIRST_CHR" 0 "$PROBE"); then
    echo "FATAL: first ssms request failed (network/field/filter)."; rm -f "$PROBE"; exit 1
  fi
  if [ "${total:-0}" -le 0 ] || [ "${hits:-0}" -le 0 ]; then
    echo "FATAL: ssms returned total=$total hits=$hits for $FIRST_CHR."; rm -f "$PROBE"; exit 1
  fi
  echo "probe ok chrom=$FIRST_CHR hits=$hits total=$total"
fi

# ---- keyset crawl per chromosome -----------------------------------------------------
pages_fetched=0
for chrom in $CHROMS; do
  cursor=0
  got=0
  while [ "$got" -lt "$SAFETY_MAX" ]; do
    out="$(printf '%s/%s_c%012d.json' "$PAGES_DIR" "$chrom" "$cursor")"
    if [ -s "$out" ]; then
      read -r hits last < <(read_cached "$out")
    else
      if ! read -r hits last total < <(fetch_page "$chrom" "$cursor" "$out"); then
        echo "WARN: fetch failed chrom=$chrom cursor=$cursor (stopping this chrom)"; rm -f "$out"; break
      fi
      pages_fetched=$((pages_fetched + 1))
      [ "$cursor" -eq 0 ] && echo "chrom=$chrom total=$total"
      sleep "$SLEEP"
    fi
    [ "${hits:-0}" -le 0 ] && { [ -s "$out" ] || rm -f "$out"; break; }
    got=$((got + hits))
    [ "$hits" -lt "$SIZE" ] && break        # last page for this chromosome
    next=$((last + 1))
    [ "$next" -le "$cursor" ] && break       # no forward progress (safety)
    cursor="$next"
  done
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 5
