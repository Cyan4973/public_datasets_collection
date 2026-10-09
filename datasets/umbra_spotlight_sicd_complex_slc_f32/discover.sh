#!/usr/bin/env bash
# Metadata-only: regenerate sources.tsv from the live bucket listing plus
# 4 KB head / 64 KB tail range probes of the smallest SICDs and their ~7 KB
# METADATA.json siblings. Not called by download.sh. Writes scratch to
# ${DISCOVER_WORK:-/tmp/umbra_sicd_discover} and the plan to $1 (default:
# sources.discovered.tsv in that scratch dir) so the pinned sources.tsv is
# only replaced deliberately.
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${DISCOVER_WORK:-/tmp/umbra_sicd_discover}"
OUT="${1:-$WORK/sources.discovered.tsv}"
mkdir -p "$WORK"
python3 -I "$RECIPE_DIR/scripts/discover.py" --work "$WORK" --out "$OUT"
echo "wrote $OUT"
