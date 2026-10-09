#!/usr/bin/env bash
# Authoring-time key resolution (not part of download/build/verify). Lists every 1998-04-20..
# 1998-10-31 day prefix of TRACE 171 A source-area-0 files in the NASA GSFC HelioCloud bucket,
# range-reads the 5,760-byte FITS headers of up to 32 evenly spaced frames per day, applies the
# header regime and the spacing policy in scripts/discover.py and rewrites sources.tsv.
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${DISCOVER_CACHE:-/tmp/autocollect/nasa_heliocloud_trace_171_euv_frames_i16/discover}"
python3 "$RECIPE_DIR/scripts/discover.py" scan --cache "$CACHE"
python3 "$RECIPE_DIR/scripts/discover.py" select --cache "$CACHE" --out "$RECIPE_DIR/sources.tsv"
