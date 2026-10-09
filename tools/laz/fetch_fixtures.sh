#!/usr/bin/env bash
# Download the small public LAS/LAZ reference files used by
# tools/laz/test_laszip.py into ${DATA_DIR:-.data}/laz_fixtures/.
#
# Every file is pinned in tools/laz/fixtures.tsv by a commit-pinned URL, its
# byte size and its SHA-256. Files already present with the right checksum
# are kept; anything else is (re)downloaded with curl and verified. About
# 9.5 MB in total, no file over 4 MB.
#
# Usage: bash tools/laz/fetch_fixtures.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
OUT_DIR="$DATA_ROOT/laz_fixtures"
TABLE="$TOOL_DIR/fixtures.tsv"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

size_of() {
  wc -c < "$1" | tr -d ' '
}

mkdir -p "$OUT_DIR"
echo "fixtures -> $OUT_DIR"

fetched=0
kept=0
while IFS=$'\t' read -r name url sha256 size _description; do
  [ "$name" = "name" ] && continue
  [ -z "$name" ] && continue
  dst="$OUT_DIR/$name"
  if [ -f "$dst" ] && [ "$(size_of "$dst")" = "$size" ] && [ "$(sha256_of "$dst")" = "$sha256" ]; then
    kept=$((kept + 1))
    continue
  fi
  tmp="$dst.part"
  rm -f "$tmp"
  echo "fetching $name ($size bytes)"
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 \
    --speed-limit 1024 --speed-time 60 -sS -o "$tmp" "$url"
  got_size="$(size_of "$tmp")"
  if [ "$got_size" != "$size" ]; then
    echo "error: $name: expected $size bytes, got $got_size" >&2
    rm -f "$tmp"
    exit 1
  fi
  got_sha="$(sha256_of "$tmp")"
  if [ "$got_sha" != "$sha256" ]; then
    echo "error: $name: sha256 mismatch (expected $sha256, got $got_sha)" >&2
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$dst"
  fetched=$((fetched + 1))
done < "$TABLE"

echo "done: $fetched fetched, $kept already present and verified"
