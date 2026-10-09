#!/usr/bin/env bash
# Documents how files.tsv was resolved: fetch the sofacoustics.org HUTUBS
# Apache listing, keep exactly the ppN_HRIRs_measured.sofa entries (the
# *_simulated.sofa BEM files are excluded), and HEAD each one for its
# Content-Length and Last-Modified. Metadata only; no payload is fetched.
#
# Usage: bash discover.sh [output.tsv]   (default: print to stdout)
# files.tsv was produced by this script on 2026-10-09. Its sha256 column
# ('-' = not yet pinned) is filled from probes and the first full download
# (see README).
set -euo pipefail

BASE="https://sofacoustics.org/data/database/hutubs/"
OUT="${1:-/dev/stdout}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 5 --retry-delay 5 --max-time 120 "$BASE" -o "$TMP/listing.html"
grep -o 'href="pp[0-9]*_HRIRs_measured\.sofa"' "$TMP/listing.html" \
  | sed -e 's/^href="//' -e 's/"$//' | sort -u | sort -V > "$TMP/names.txt"
n="$(wc -l < "$TMP/names.txt")"
if [ "$n" -ne 96 ]; then
  echo "expected 96 measured SOFA files in listing, found $n" >&2
  exit 1
fi

while read -r name; do
  subj="${name%%_*}"; subj="${subj#pp}"
  hdr="$(curl -fsSI -L --retry 5 --retry-delay 5 --max-time 60 "$BASE$name" | tr -d '\r')"
  size="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}')"
  lm="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')"
  [ -n "$size" ] || { echo "no Content-Length for $name" >&2; exit 1; }
  printf '%s\t%s\t%s\t%s\t-\n' "$subj" "$name" "$size" "$lm"
done < "$TMP/names.txt" | sort -t $'\t' -k1,1n > "$TMP/rows.tsv"

{ printf 'subject\tfile\tsize_bytes\tlast_modified\tsha256\n'; cat "$TMP/rows.tsv"; } > "$OUT"
