#!/usr/bin/env bash
# Documentation / reproducibility helper (not part of download/build):
# re-derive files.tsv and meta.tsv from the public GCS JSON listing of
#   gs://noaa-passive-bioacoustic/nefsc/audio/sbnms/<deployment>/
# and each deployment's metadata/NEFSC_SBNMS_<deployment>.json.
#
# Rule (scripts/maru.py discover):
#   * keep deployments whose every audio object is a 36,000,054-byte .aif
#     (10 ch x 1,800,000 frames x 16 bit, 2000 Hz); this drops the FLAC
#     deployments (200806_2, 200903_1, 200905, 200907_3, 200910_2, 200911),
#     the 10 kHz AIFF deployments (200806_1, 200907_1; 180,000,054 B) and the
#     7-channel realigned 200907_2 (25,200,054 B);
#   * drop deployments with no channel flagged quality "Good" in the
#     publisher's QUALITY_DETAILS (200803 / NOPP2: every channel "Unusable");
#   * per kept deployment, take the middle object in name order, and on its
#     date pick the files named *_<date>_000000.aif and *_<date>_120000.aif.
#
# Usage: bash discover.sh [OUT_DIR]   (default /tmp/autocollect/<id>/discover)
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="noaa_nefsc_sbnms_maru_hydrophone_i16"
OUT="${1:-/tmp/autocollect/$DATASET_ID/discover}"
API="https://storage.googleapis.com/storage/v1/b/noaa-passive-bioacoustic/o"
OBJ="https://storage.googleapis.com/noaa-passive-bioacoustic"
mkdir -p "$OUT/listings" "$OUT/meta"
rm -f "$OUT"/listings/*.json

curl -fsS --max-time 120 "$API?delimiter=/&prefix=nefsc/audio/sbnms/&fields=prefixes" -o "$OUT/top.json"
deps=$(python3 -I -c 'import json,sys; [print(p.split("/")[-2]) for p in json.load(open(sys.argv[1]))["prefixes"]]' "$OUT/top.json")
for dep in $deps; do
  tok=""; n=0
  while :; do
    url="$API?prefix=nefsc/audio/sbnms/$dep/&maxResults=1000&fields=nextPageToken,items(name,size,md5Hash,crc32c,generation)"
    [ -n "$tok" ] && url="$url&pageToken=$tok"
    curl -fsS --max-time 120 "$url" -o "$OUT/listings/$dep.$(printf %03d $n).json"
    tok=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("nextPageToken",""))' "$OUT/listings/$dep.$(printf %03d $n).json")
    n=$((n + 1))
    [ -z "$tok" ] && break
  done
  u="${dep#sbnms_}"
  curl -fsS --max-time 60 "$OBJ/nefsc/audio/sbnms/$dep/metadata/NEFSC_SBNMS_$u.json" -o "$OUT/meta/$dep.json" || true
  echo "$dep pages=$n"
done
python3 -I "$RECIPE_DIR/scripts/maru.py" discover --listings "$OUT/listings" --meta "$OUT/meta" \
  --out-files "$OUT/files.tsv" --out-meta "$OUT/meta.tsv"
echo "wrote $OUT/files.tsv and $OUT/meta.tsv; compare with $RECIPE_DIR/files.tsv and meta.tsv"
