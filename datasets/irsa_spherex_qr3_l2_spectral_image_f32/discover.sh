#!/usr/bin/env bash
# Documents how sources.tsv was resolved (metadata only; never fetches image data):
#  1. anonymous S3 ListObjectsV2 of qr3/level2/ (week groups) and of each group's primary
#     l2b-v27-* run, detector directory 1/ (paginated)
#  2. header-only range probes (<= 115,200 bytes, If-Match on the listed ETag) of the picked
#     exposures; scripts/discover.py checks the header regime and writes sources.tsv
# Scratch goes to $DISCOVER_DIR (default /tmp/autocollect/<id>/discover), not into the recipe.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="irsa_spherex_qr3_l2_spectral_image_f32"
DISCOVER_DIR="${DISCOVER_DIR:-/tmp/autocollect/$DATASET_ID/discover}"
mkdir -p "$DISCOVER_DIR"
python3 "$RECIPE_DIR/scripts/discover.py" "$DISCOVER_DIR" "$RECIPE_DIR/sources.tsv"
