#!/usr/bin/env bash
# Metadata-only discovery that produced sources.tsv. Not part of the
# download/build/verify path; kept to document how products were resolved.
#
# 1. Fetch the data_raw_audio collection listing, every sol directory listing
#    (file sizes), the collection inventory CSV and the bundle MD5 manifest.
# 2. Candidates = every raw-audio FITS product under 1,000,000 bytes (the short
#    LIBS+MIC recordings; long recordings are 2-23 MB), sorted by file name
#    (= sol, then spacecraft clock).
# 3. Split the candidate list into 800 equal consecutive windows. In each
#    window, probe candidates in order with two range GETs (primary header,
#    bytes 0-17279; and the 2,880-byte block at file_bytes - 351,360 where the
#    final SOUND HDU header must sit) and keep the first product whose primary
#    header says MIC_SAMP=100000, MIC_SAMC=21, MIC_DOWN=F, MIC_GAIN=2,
#    MIC_DURA=1, HSS_NUMW=174000, LIBS_MIC=T, LASDNS00=30, SCMDTYPE=9 and whose
#    SOUND header is BINTABLE, NAXIS2=174000, TFORM1='I', TZERO1=32768.
# 4. Pin each product's URL, size, bundle MD5, SOUND HDU offset and the
#    SHA-256 of both probed header blocks in sources.tsv.
set -euo pipefail

CANDIDATE_ID="nasa_pds_m2020_supercam_libs_mic_audio_i16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${DISCOVER_DIR:-${TMPDIR:-/tmp}/${CANDIDATE_ID}_discover}"
BASE="https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam"
COLL="$BASE/data_raw_audio"
mkdir -p "$WORK/listings" "$WORK/probe"
cd "$WORK"

curl -fsSL --retry 5 --max-time 120 -o top.html "$COLL/"
curl -fsSL --retry 5 --max-time 300 -o inventory.csv "$COLL/collection_data_raw_audio_inventory.csv"
[[ -s bundle.md5 ]] || curl -fsSL --retry 5 --speed-limit 1024 --speed-time 120 -o bundle.md5 "$BASE/urn-nasa-pds-mars2020_supercam.md5"
grep -o 'sol_[0-9]\{5\}/"' top.html | tr -d '/"' | sort -u > sols.txt
echo "sols=$(wc -l < sols.txt)"
xargs -P 8 -I{} sh -c '[ -s "listings/$1.html" ] || curl -fsSL --retry 5 --max-time 120 -o "listings/$1.html" "$2/$1/"' _ {} "$COLL" < sols.txt

python3 "$RECIPE_DIR/scripts/m2020mic.py" candidates --listings listings --out candidates.tsv

for round in $(seq 1 40); do
  python3 "$RECIPE_DIR/scripts/m2020mic.py" round --candidates candidates.tsv --probe-dir probe > todo.tsv
  n=$(wc -l < todo.tsv)
  echo "round=$round probes=$n"
  [[ "$n" == 0 ]] && break
  # shellcheck disable=SC2016
  xargs -P 8 -L 1 sh -c '
    name=$1; url=$2; size=$3; off=$((size - 351360))
    curl -fsSL --retry 5 --max-time 120 -r 0-17279 -o "probe/$name.primary.part" "$url" && mv "probe/$name.primary.part" "probe/$name.primary"
    curl -fsSL --retry 5 --max-time 120 -r "$off-$((off + 2879))" -o "probe/$name.soundhdr.part" "$url" && mv "probe/$name.soundhdr.part" "probe/$name.soundhdr"
    true
  ' _ < todo.tsv
done

python3 "$RECIPE_DIR/scripts/m2020mic.py" finalize --candidates candidates.tsv --probe-dir probe \
  --md5 bundle.md5 --inventory inventory.csv --out "$RECIPE_DIR/sources.tsv"
echo "inventory_sha256=$(sha256sum inventory.csv | cut -d' ' -f1) bundle_md5_sha256=$(sha256sum bundle.md5 | cut -d' ' -f1)"
echo "sources_sha256=$(sha256sum "$RECIPE_DIR/sources.tsv" | cut -d' ' -f1)"
