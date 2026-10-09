#!/usr/bin/env bash
# Metadata-only discovery that produced pinned_hdus.tsv (not part of the
# download/build/verify contract). It lists the DR1 iron healpix/main/dark
# groups, takes 36 evenly spaced groups, picks in each the lowest-numbered
# healpix whose coadd FITS is 100-250 MB (moving to the next group when none
# qualifies), and walks every HDU header of that file with small curl range
# GETs to pin the B/R/Z_FLUX header offsets, shapes, header SHA-256 and the
# FITS DATASUM of each data unit. Only headers are fetched.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$RECIPE_DIR/pinned_hdus.tsv}"
python3 -I "$RECIPE_DIR/scripts/desi_coadd.py" discover --out "$OUT" --files 36 \
  --min-bytes 100000000 --max-bytes 250000000
