#!/usr/bin/env bash
# Documents (and can reproduce) how scripts/pinned_files.tsv was resolved:
# fetch the IA item metadata, take every Prelude/Etude FLAC, read its first
# 8 KiB with a range request, parse STREAMINFO, keep 44100 Hz / 2 ch / 16 bps.
# Usage: bash scripts/discover.sh WORK_DIR  > pinned_files.candidate.tsv
# Metadata-sized probes only (~52 x 8 KiB); not part of the download contract.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: discover.sh WORK_DIR}"
mkdir -p "$WORK/headers"
curl -fsSL --retry 5 --retry-all-errors --max-time 120 -o "$WORK/meta.json" \
  "https://archive.org/metadata/musopen-chopin-complete-works-flac"
python3 -I "$HERE/musopen_chopin.py" discover --meta "$WORK/meta.json" --list-urls |
  while IFS=$'\t' read -r md5 url; do
    [ -s "$WORK/headers/$md5.bin" ] && continue
    curl -fsSL --retry 5 --retry-all-errors --max-time 60 -r 0-8191 -o "$WORK/headers/$md5.bin" "$url" </dev/null
  done
python3 -I "$HERE/musopen_chopin.py" discover --meta "$WORK/meta.json" --headers-dir "$WORK/headers"
