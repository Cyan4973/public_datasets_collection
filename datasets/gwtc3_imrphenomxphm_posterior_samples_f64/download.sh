#!/usr/bin/env bash
# Range-fetch, from the CC BY 4.0 GWTC-3 PE data release (Zenodo record
# 8177023), only the HDF5 metadata and the contiguous C01:IMRPhenomXPHM/
# posterior_samples table of the 33 binary-black-hole *_mixed_cosmo.h5 files
# pinned in sources.tsv, plus the record JSON and one complete control file
# (GW200322_091133, 21.4 MB, MD5-checked) that proves the range assembly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwtc3_imrphenomxphm_posterior_samples_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
RECORD_URL="https://zenodo.org/api/records/8177023"
UA="openzl-public-datasets-gwtc3-pe/1.0"
MAX_ROUNDS=30
META_PARALLEL=4
SPAN_PARALLEL=4
CONTROL_EVENT="GW200322_091133"

mkdir -p "$DOWNLOAD_DIR/record" "$DOWNLOAD_DIR/blocks" "$DOWNLOAD_DIR/tables" "$DOWNLOAD_DIR/control" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 -I "$RECIPE_DIR/scripts/gwtc3_pe.py")
die() { echo "ERROR: $*" >&2; exit 1; }

python3 -I "$RECIPE_DIR/scripts/selftest_pe_h5.py"
echo "sources.tsv sha256=$(sha256sum "$SOURCES" | cut -d' ' -f1) events=$(($(wc -l < "$SOURCES") - 1))"

# 1. Record JSON: license (cc-by-4.0), title, and every pinned key/size/MD5.
rec="$DOWNLOAD_DIR/record/zenodo_8177023.json"
curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors \
  --max-time 180 --max-filesize 20000000 --user-agent "$UA" --output "$rec.part" "$RECORD_URL" < /dev/null
mv "$rec.part" "$rec"
"${TOOL[@]}" validate-record --sources "$SOURCES" --record "$rec"

# 2. Liveness: one-byte range GET of the first pinned file.
first_url="$RECORD_URL/files/$(sed -n 2p "$SOURCES" | cut -f2)/content"
code="$(curl --silent --location --output /dev/null --write-out '%{http_code}' --range 0-0 \
  --max-time 60 --retry 3 --user-agent "$UA" "$first_url" < /dev/null || true)"
[ "$code" = "206" ] || die "liveness range GET of $first_url returned HTTP $code"

# 3. Planner rounds. Each round walks every file's HDF5 metadata (superblock,
#    root and C01:IMRPhenomXPHM symbol tables, posterior_samples header)
#    through the local 64 KiB block cache. Missing metadata blocks are fetched
#    in coalesced ranges; once an event's table location is known and matches
#    sources.tsv, its one contiguous table span is fetched (resumable).
complete=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  set +e
  "${TOOL[@]}" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" \
    --meta-requests "$DOWNLOAD_DIR/meta_requests.tsv" --span-requests "$DOWNLOAD_DIR/span_requests.tsv"
  status=$?
  set -e
  if [ "$status" = 0 ]; then complete=1; break; fi
  [ "$status" = 3 ] || exit "$status"
  if [ -s "$DOWNLOAD_DIR/meta_requests.tsv" ]; then
    echo "round=$round metadata_ranges=$(wc -l < "$DOWNLOAD_DIR/meta_requests.tsv")"
    tr '\t' '\n' < "$DOWNLOAD_DIR/meta_requests.tsv" \
      | xargs -d '\n' -n 6 -P "$META_PARALLEL" bash "$RECIPE_DIR/scripts/fetch_blocks.sh"
  fi
  if [ -s "$DOWNLOAD_DIR/span_requests.tsv" ]; then
    echo "round=$round table_spans=$(wc -l < "$DOWNLOAD_DIR/span_requests.tsv") bytes=$(awk -F'\t' '{s += $3 - $2 + 1} END {print s}' "$DOWNLOAD_DIR/span_requests.tsv")"
    tr '\t' '\n' < "$DOWNLOAD_DIR/span_requests.tsv" \
      | xargs -d '\n' -n 5 -P "$SPAN_PARALLEL" bash "$RECIPE_DIR/scripts/fetch_span.sh"
  fi
done
[ "$complete" = 1 ] || die "plan did not converge within $MAX_ROUNDS rounds"

# 4. Control: the complete smallest pinned file, resumable, MD5-checked.
line="$(awk -F'\t' -v e="$CONTROL_EVENT" '$1 == e' "$SOURCES")"
[ -n "$line" ] || die "control event missing from sources.tsv"
c_url="$RECORD_URL/files/$(echo "$line" | cut -f2)/content"
c_size="$(echo "$line" | cut -f3)"
c_md5="$(echo "$line" | cut -f4)"
c_out="$DOWNLOAD_DIR/control/$CONTROL_EVENT.h5"
if [ ! -f "$c_out" ] || [ "$(stat -c %s "$c_out")" != "$c_size" ]; then
  curl --fail --silent --show-error --location --continue-at - \
    --retry 10 --retry-delay 5 --retry-all-errors --speed-limit 1024 --speed-time 120 \
    --user-agent "$UA" --output "$c_out.part" "$c_url" < /dev/null
  [ "$(stat -c %s "$c_out.part")" = "$c_size" ] || die "control size mismatch"
  echo "$c_md5  $c_out.part" | md5sum --check --status || { rm -f "$c_out.part"; die "control MD5 mismatch"; }
  mv "$c_out.part" "$c_out"
fi
echo "$c_md5  $c_out" | md5sum --check --status || die "control MD5 mismatch"
[ "$(head -c 8 "$c_out" | od -An -tx1 | tr -d ' \n')" = "894844460d0a1a0a" ] || die "control lacks HDF5 signature"
echo "control_ok $CONTROL_EVENT bytes=$c_size md5=$c_md5"

# 5. Final semantic pass: every event resolves, tables are complete, and every
#    selected column is finite, non-constant and inside its physical bounds.
"${TOOL[@]}" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" \
  --meta-requests "$DOWNLOAD_DIR/meta_requests.tsv" --span-requests "$DOWNLOAD_DIR/span_requests.tsv" \
  || die "final plan check failed"
"${TOOL[@]}" check-tables --sources "$SOURCES" --downloads "$DOWNLOAD_DIR"

echo "blocks=$(find "$DOWNLOAD_DIR/blocks" -name 'blk_*.bin' | wc -l) tables=$(find "$DOWNLOAD_DIR/tables" -name '*.bin' | wc -l) bytes_total=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
