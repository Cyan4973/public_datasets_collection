#!/usr/bin/env bash
# Authoring-time key resolution (not part of download/build/verify). Scans 60 evenly spaced
# minute-of-day index CSVs of the HelioCloud IRIS index, range-reads candidate FITS headers,
# applies the selection policy in scripts/discover.py and rewrites sources.tsv.
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${DISCOVER_CACHE:-/tmp/autocollect/iris/discover}"
python3 "$RECIPE_DIR/scripts/discover.py" scan --cache "$CACHE"
python3 "$RECIPE_DIR/scripts/discover.py" select --cache "$CACHE" --out "$RECIPE_DIR/sources.tsv"
