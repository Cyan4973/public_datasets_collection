#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="hyg_star_photometry_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# The HYG database (astronexus/HYG-Database) is a public compiled star catalog
# (Hipparcos + Yale Bright Star + Gliese) distributed as a single self-describing
# CSV. We collect the genuine photometric quantities (apparent magnitude,
# absolute magnitude, B-V colour index); the build scales them to integer
# millimagnitudes (int16). Upstream file paths have moved across versions, so we
# try a list of candidate URLs and accept the first CSV that carries the expected
# columns. Override entirely with HYG_CSV_URL.
OUT="$DOWNLOAD_DIR/hyg.csv"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
REPO="${HYG_REPO:-astronexus/HYG-Database}"

# Upstream file paths move between HYG versions, so discover the catalogue CSV(s)
# from the GitHub repo tree (default branch, recursive) instead of guessing.
# All network goes through curl (proxy-aware via ~/.curlrc); python only parses
# the JSON on stdin. Emit best-first candidate URLs: an explicit override, then
# discovered raw and git-LFS media URLs, then a legacy guess.
gh_api() { curl --globoff -fsSL --max-time 60 -A "$UA" -H "Accept: application/vnd.github+json" "$1" 2>/dev/null; }

discover_candidates() {
  [ -n "${HYG_CSV_URL:-}" ] && echo "$HYG_CSV_URL"
  local branch tree paths
  branch="$(gh_api "https://api.github.com/repos/$REPO" \
            | python3 -c "import sys,json;print(json.load(sys.stdin).get('default_branch','main'))" 2>/dev/null || echo main)"
  for br in "$branch" main master; do
    tree="$(gh_api "https://api.github.com/repos/$REPO/git/trees/$br?recursive=1")"
    [ -n "$tree" ] || continue
    paths="$(printf '%s' "$tree" | python3 -c "
import sys, json
try: tree = json.load(sys.stdin).get('tree', [])
except Exception: sys.exit(0)
items = [(int(t.get('size',0)), t['path']) for t in tree
         if t.get('type')=='blob' and t['path'].lower().endswith('.csv') and 'hyg' in t['path'].lower()]
items.sort(reverse=True)
for _s, p in items: print(p)
" 2>/dev/null)"
    if [ -n "$paths" ]; then
      while IFS= read -r p; do
        [ -n "$p" ] || continue
        echo "https://raw.githubusercontent.com/$REPO/$br/$p"
        echo "https://media.githubusercontent.com/media/$REPO/$br/$p"  # git-LFS variant
      done <<< "$paths"
      break
    fi
  done
  echo "https://raw.githubusercontent.com/astronexus/HYG-Database/master/hygdata_v3.csv"
}
mapfile_candidates() { discover_candidates | awk 'NF && !seen[$0]++'; }

has_columns() {
  # header (line 1) must contain mag, absmag and ci columns
  python3 - "$1" <<'PY' 2>/dev/null || return 1
import csv, sys
with open(sys.argv[1], newline="", encoding="utf-8", errors="replace") as fh:
    header = next(csv.reader(fh))
cols = {c.strip().lower() for c in header}
sys.exit(0 if {"mag", "absmag", "ci"} <= cols else 1)
PY
}

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && has_columns "$OUT"; then
  echo "cache_hit path=$OUT bytes=$(wc -c < "$OUT" | tr -d ' ')"
  echo "[$(date -Is)] download done dataset=$DATASET_ID (cached)"
  exit 0
fi

ok=0
while IFS= read -r url; do
  [ -n "$url" ] || continue
  echo "try url=$url"
  part="$OUT.part"; rm -f "$part"
  if ! curl --globoff -fSL --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 -C - -A "$UA" -o "$part" "$url"; then
    echo "  WARN: fetch failed"; rm -f "$part"; continue
  fi
  if ! has_columns "$part"; then
    sz="$(wc -c < "$part" | tr -d ' ')"
    echo "  WARN: not a HYG CSV with mag/absmag/ci (bytes=$sz; maybe an LFS pointer)"; rm -f "$part"; continue
  fi
  mv "$part" "$OUT"
  echo "downloaded path=$OUT bytes=$(wc -c < "$OUT" | tr -d ' ')"
  ok=1; break
done < <(mapfile_candidates)

if [ "$ok" != 1 ]; then
  echo "FATAL: could not obtain a HYG CSV with mag/absmag/ci columns."
  echo "       Supply one with HYG_CSV_URL=<url> (astronexus/HYG-Database CSV)."
  exit 1
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
