#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Not part of the acceptance path.
#
# 1. Lists the top level of the public boreas bucket and keeps the 44
#    boreas-2020-11-* .. boreas-2021-11-* sequences (the Velodyne Alpha Prime
#    era; 2022/2024/2025 sequences are excluded).
# 2. Lists each sequence's lidar/ prefix with ListObjectsV2 (list-type=2),
#    following continuation tokens, and records key, size and ETag (plain MD5:
#    every lidar object is a single-part upload).
# 3. Selects 6 sweeps per sequence, centred in equal timestamp-order strata
#    (index floor((2k+1) n / 12), k = 0..5), writes sources.tsv and diffs it
#    against the pinned copy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="boreas_velodyne_alpha_prime_intensity_u8"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/boreas_lidar.py"
BUCKET="https://boreas.s3.amazonaws.com"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --max-time 120)
mkdir -p "$OUT_DIR/listings" "$OUT_DIR/pages" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

"${CURL[@]}" "$BUCKET/?list-type=2&delimiter=/" -o "$OUT_DIR/root.xml"
mapfile -t seqs < <(grep -o '<Prefix>boreas-20\(20-1[12]\|21-\(0[1-9]\|1[01]\)\)-[0-9-]*/</Prefix>' "$OUT_DIR/root.xml" \
  | sed -e 's#<Prefix>##' -e 's#/</Prefix>##' | sort)
echo "alpha_prime_sequences=${#seqs[@]}"
[ "${#seqs[@]}" -eq 44 ] || { echo "FATAL: expected 44 sequences" >&2; exit 1; }

rm -f "$OUT_DIR"/listings/*.tsv
for seq in "${seqs[@]}"; do
  cont=""
  page=0
  while :; do
    url="$BUCKET/?list-type=2&prefix=$seq/lidar/"
    [ -n "$cont" ] && url="$url&continuation-token=$cont"
    "${CURL[@]}" "$url" -o "$OUT_DIR/pages/page.xml"
    cont="$(python3 "$TOOL" parse-listing --xml "$OUT_DIR/pages/page.xml" --append "$OUT_DIR/listings/$seq.tsv")"
    page=$((page + 1))
    [ -z "$cont" ] && break
  done
  echo "$seq pages=$page sweeps=$(wc -l < "$OUT_DIR/listings/$seq.tsv")"
done

python3 "$TOOL" select --listing-dir "$OUT_DIR/listings" --per-sequence 6 --out "$OUT_DIR/sources.tsv"
diff -u "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.tsv" && echo "selection matches pinned sources.tsv"
echo "[$(date -Is)] discover done"
