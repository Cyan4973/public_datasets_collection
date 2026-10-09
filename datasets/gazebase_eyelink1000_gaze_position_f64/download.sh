#!/usr/bin/env bash
# Fetch 24 pinned per-subject ZIP members (GazeBase Round_1, subjects 1001-1024)
# from the 6.71 GB GazeBase_v2_0.zip on figshare by exact outer-ZIP byte range,
# validate each member, and keep only the inflated inner per-subject ZIP.
# GazeBaseDemoInfo.xlsx (demographics) is never requested.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gazebase_eyelink1000_gaze_position_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API_URL="https://api.figshare.com/v2/articles/12912257"
# Always go through ndownloader: it redirects to short-lived signed S3 URLs,
# so the redirect target must never be pinned.
BULK_URL="https://ndownloader.figshare.com/files/27039812"
PINS="$RECIPE_DIR/scripts/pinned_members.tsv"
HELPER="$RECIPE_DIR/scripts/gazebase.py"
UA="openzl-public-datasets-gazebase/1.0"

mkdir -p "$DOWNLOAD_DIR/Round_1" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

article="$DOWNLOAD_DIR/article_12912257.json"
rm -f "$article.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$article.part" "$API_URL"
mv "$article.part" "$article"
python3 -I "$HELPER" check-api --json "$article"

fetched=0
cached=0
while IFS=$'\t' read -r name offset span comp uncomp crc; do
  case "$name" in ''|'#'*) continue ;; esac
  out="$DOWNLOAD_DIR/$name"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if python3 -I "$HELPER" check-inner --pins "$PINS" --member "$name" --path "$out"; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached $name failed validation; refetching"
    rm -f "$out"
  fi
  end=$((offset + span - 1))
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$out.range.part" "$out.headers.part" "$out.part"
    if curl --fail --silent --show-error --location \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --max-filesize "$((span + 1024))" \
        --range "$offset-$end" --user-agent "$UA" \
        --dump-header "$out.headers.part" --output "$out.range.part" "$BULK_URL" \
      && python3 -I "$HELPER" extract --pins "$PINS" --member "$name" \
        --headers "$out.headers.part" --range-file "$out.range.part" --output "$out.part"; then
      mv "$out.part" "$out"
      rm -f "$out.range.part" "$out.headers.part"
      ok=1
      break
    fi
    echo "attempt $attempt for $name failed; retrying"
    sleep $((attempt * 5))
  done
  if [ "$ok" != 1 ]; then
    echo "FATAL: could not fetch and validate $name" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
done < "$PINS"

total=$(grep -vc '^#' "$PINS")
if [ "$((fetched + cached))" != "$total" ]; then
  echo "FATAL: expected $total members, have $((fetched + cached))" >&2
  exit 1
fi
echo "members_ok total=$total fetched=$fetched cached=$cached"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
