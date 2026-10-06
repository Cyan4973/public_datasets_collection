#!/usr/bin/env bash
# Documentation aid (not part of download/build): re-list the 2026 AIND
# single-plane-ophys sessions, fetch each session.json and pophys listing
# (metadata only, a few MB), and re-apply the selection rule to confirm the
# pins in sources.tsv. download.sh never discovers keys dynamically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="aind_bci_2p_scanimage_trials_i16"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BUCKET="https://aind-open-data.s3.amazonaws.com"
UA="openzl-public-datasets-aind-bci-2p/1.0"
mkdir -p "$OUT" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

fetch() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 120 --user-agent "$UA" "$1"
}

list_all() {  # list_all <prefix> [extra-query] : concatenated ListObjectsV2 pages
  local prefix="$1" extra="${2:-}" cursor="" page
  while :; do
    if [[ -n "$cursor" ]]; then
      page="$(fetch "$BUCKET/?list-type=2$extra&prefix=$prefix&continuation-token=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$cursor")")"
    else
      page="$(fetch "$BUCKET/?list-type=2$extra&prefix=$prefix")"
    fi
    printf '%s\n' "$page"
    grep -q '<IsTruncated>true' <<< "$page" || break
    cursor="$(grep -o '<NextContinuationToken>[^<]*' <<< "$page" | sed 's/<NextContinuationToken>//')"
  done
}

list_all "single-plane-ophys_" "&delimiter=/" > "$OUT/top.xml"
grep -o '<Prefix>single-plane-ophys_[0-9]\{6\}_2026-[^<]*' "$OUT/top.xml" | sed 's#<Prefix>##; s#/$##' \
  | grep -E '^single-plane-ophys_[0-9]{6}_2026-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$' > "$OUT/sessions.txt"
echo "sessions_2026=$(wc -l < "$OUT/sessions.txt")"
while read -r session; do
  [[ -s "$OUT/$session.session.json" ]] || fetch "$BUCKET/$session/session.json" > "$OUT/$session.session.json" || {
    echo "no session.json for $session"; rm -f "$OUT/$session.session.json"; continue; }
  [[ -s "$OUT/$session.pophys.xml" ]] || list_all "$session/pophys/" > "$OUT/$session.pophys.xml"
done < "$OUT/sessions.txt"

python3 "$RECIPE_DIR/scripts/discover.py" --discovery-dir "$OUT" --sources "$RECIPE_DIR/sources.tsv"
echo "[$(date -Is)] discover done"
