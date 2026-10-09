#!/usr/bin/env bash
# Documents how sources.tsv was resolved (metadata only; never fetches FLUX data or whole files).
#  1. MAST Mast.Caom.Filtered: JWST / timeseries / NIRSPEC/SLIT / F290LP;G395H / calib_level 3
#  2. MAST Mast.Caom.Products for every PUBLIC SUB2048 observation (batches of 20 obsids)
#  3. sparse FITS header walk (HTTP Range, 57,600-byte pieces) of every *-seg001_nrs1_x1dints.fits
#     up to and including the EXTRACT1D header; ETag/Last-Modified captured from the responses
#  4. scripts/discover.py checks the header regime, selects one product per target and writes
#     sources.tsv
# Scratch goes to $DISCOVER_DIR (default /tmp/autocollect/<id>/discover), not into the recipe.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="mast_jwst_nirspec_g395h_tso_x1dints_flux_f64"
DISCOVER_DIR="${DISCOVER_DIR:-/tmp/autocollect/$DATASET_ID/discover}"
API="https://mast.stsci.edu/api/v0/invoke"
DL="https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product"
UA="openzl-public-datasets-jwst-nirspec-x1dints/1.0"
DISCOVER="$RECIPE_DIR/scripts/discover.py"
X1D="$RECIPE_DIR/scripts/x1dints.py"

mkdir -p "$DISCOVER_DIR/products" "$DISCOVER_DIR/hdr"

req='{"service":"Mast.Caom.Filtered","format":"json","pagesize":5000,"page":1,"params":{"columns":"*","filters":[{"paramName":"obs_collection","values":["JWST"]},{"paramName":"dataproduct_type","values":["timeseries"]},{"paramName":"instrument_name","values":["NIRSPEC/SLIT"]},{"paramName":"filters","values":["F290LP;G395H"]},{"paramName":"calib_level","values":[3]}]}}'
curl --fail --silent --show-error --max-time 300 --retry 5 --retry-delay 10 --user-agent "$UA" \
  -X POST "$API" --data-urlencode "request=$req" --output "$DISCOVER_DIR/observations.json"

rm -f "$DISCOVER_DIR"/products/batch_*.json
n=0
python3 -I "$DISCOVER" obsid-batches "$DISCOVER_DIR/observations.json" | while read -r ids; do
  n=$((n + 1))
  req="{\"service\":\"Mast.Caom.Products\",\"format\":\"json\",\"pagesize\":50000,\"page\":1,\"params\":{\"obsid\":\"$ids\"}}"
  curl --fail --silent --show-error --max-time 600 --retry 5 --retry-delay 10 --user-agent "$UA" \
    -X POST "$API" --data-urlencode "request=$req" --output "$DISCOVER_DIR/products/batch_$(printf %03d "$n").json"
done
python3 -I "$DISCOVER" candidates "$DISCOVER_DIR" > "$DISCOVER_DIR/candidates.tsv"
echo "candidates=$(($(wc -l < "$DISCOVER_DIR/candidates.tsv") - 1))"

tail -n +2 "$DISCOVER_DIR/candidates.tsv" | cut -f1 | while read -r name; do
  dir="$DISCOVER_DIR/hdr/$name"
  mkdir -p "$dir"
  for _ in $(seq 1 12); do
    read -r verdict start end < <(python3 -I "$X1D" next-header "$dir")
    [[ "$verdict" == "DONE" ]] && break
    curl --fail --silent --show-error --location --max-time 120 --retry 5 --retry-delay 10 \
      --range "$start-$end" --user-agent "$UA" --dump-header "$dir/$start.http" \
      --output "$dir/$start.bin" "$DL/$name" </dev/null
  done
  python3 -I "$X1D" layout "$dir" > "$dir/layout.json"
done

python3 -I "$DISCOVER" finalize "$DISCOVER_DIR" "$RECIPE_DIR/sources.tsv"
