#!/usr/bin/env bash
# Metadata-only discovery that documents how sources.tsv was resolved.
# Fetches the P1018 collection search, each collection's metadata, data
# listing and file log (small JSON/text), applies scripts/select_sources.py,
# then (PROBE_RANGES=1, default) range-fetches each pick's 25,920-byte header
# and the 266,280-byte auxiliary prefix of SUBINT row 112 to recompute the
# header_sha256 and row_aux_prefix_sha256 values pinned in sources.tsv.
# Total transfer is about 3.5 MB. Not part of the acceptance path.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="csiro_parkes_uwl_search_mode_u8"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API="https://data.csiro.au/dap/ws/v2"
UA="openzl-public-datasets-parkes-uwl/1.0"
PROBE_RANGES="${PROBE_RANGES:-1}"
mkdir -p "$OUT" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1

get() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 60 --max-time 300 --max-filesize 20000000 --user-agent "$UA" \
    --header "Accept: application/json" --output "$2" "$1"
}

get "$API/collections?q=Parkes%20observations%20for%20project%20P1018&rpp=100" "$OUT/search.json"
for cid in $(python3 -c 'import json,sys; [print(c["dataCollectionId"]) for c in json.load(open(sys.argv[1]))["dataCollections"]]' "$OUT/search.json"); do
  get "$API/collections/$cid" "$OUT/collection_$cid.json"
  get "$API/collections/$cid/data" "$OUT/collection_${cid}_data.json"
  log_url="$(python3 - "$OUT/collection_${cid}_data.json" "$cid" <<'PY'
import json, sys
files = json.load(open(sys.argv[1])).get("file", [])
hits = [f for f in files if f["filename"] == f"{sys.argv[2]}.log"]
print(hits[0]["presignedLink"]["href"] if hits else "")
PY
)"
  if [ -n "$log_url" ]; then
    get "$log_url" "$OUT/$cid.log"
  fi
done

python3 "$RECIPE_DIR/scripts/select_sources.py" --discovery-dir "$OUT" | tee "$OUT/selection.tsv" | cut -f1-7

if [ "$PROBE_RANGES" = "1" ]; then
  echo "observation_id	header_sha256	row_aux_prefix_sha256" > "$OUT/probe_hashes.tsv"
  grep -v '^#' "$OUT/selection.tsv" | tail -n +2 | while IFS=$'\t' read -r obs cid doi fid fname fsize md5 url; do
    curl --fail --silent --show-error --range 0-25919 --user-agent "$UA" --output "$OUT/$obs.header" "$url"
    start=$((25920 + 112 * 54792232))
    curl --fail --silent --show-error --range "$start-$((start + 266279))" --user-agent "$UA" --output "$OUT/$obs.aux" "$url"
    printf '%s\t%s\t%s\n' "$obs" "$(sha256sum < "$OUT/$obs.header" | cut -d' ' -f1)" \
      "$(sha256sum < "$OUT/$obs.aux" | cut -d' ' -f1)" >> "$OUT/probe_hashes.tsv"
  done
  cat "$OUT/probe_hashes.tsv"
fi
