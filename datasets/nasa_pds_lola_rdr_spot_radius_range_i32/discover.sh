#!/usr/bin/env bash
# Documentation of how sources.tsv was resolved (run once by the recipe
# author; download.sh does NOT run this). Writes sources.tsv next to itself.
#
# Scope rule:
#   * Phase directories lro_no_01..lro_no_13 (NOMINAL MISSION, 2009-09-15 ..
#     2010-09-16) and lro_sm_01..lro_sm_15 (SCIENCE MISSION up to 2011-10-31)
#     of data/lola_rdr/. These 28 phases are LRO's quasi-circular ~50 km
#     polar mapping orbit (orbit products 48.58-48.69 MB, ~113 min). From
#     lro_sm_16 on, LRO was moved toward the 30 x 180 km elliptical orbit
#     (products shrink, then grow to ~51.2 MB from lro_sm_18), and lro_es_*
#     (extended science) phases have collapsed valid-spot fractions; neither
#     is touched.
#   * Within each phase, orbit products (lolardr_YYDDDHHMM.dat) are sorted by
#     name and tried in bisection order: positions n/2, n/4, 3n/4, n/8, 3n/8,
#     5n/8, 7n/8, ... (integer floor, deduplicated).
#     Each candidate is probed with PROBE_CHUNKS evenly spaced range reads of
#     PROBE_RECORDS rows; the first candidate whose probed kept-spot fraction
#     (spot policy in scripts/lola_rdr.py) is >= SELECT_MIN_FRACTION is pinned.
#     One orbit per phase.
#   * MD5s come from the volume MD5 list (lrolol_1xxx_<yymmdd>.md5 in the
#     collection root; the newest one is used) and record counts from labels.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${WORK:-/tmp/autocollect/nasa_pds_lola_rdr_spot_radius_range_i32/discover}"
H="$RECIPE_DIR/scripts/discover_helper.py"
ROOT="https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1"
BASE="$ROOT/lrolol_1xxx/data/lola_rdr"
PROBE_CHUNKS=24
PROBE_RECORDS=64
SELECT_MIN_FRACTION="${SELECT_MIN_FRACTION:-0.40}"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 600)
PHASES=()
for i in $(seq -w 1 13); do PHASES+=("lro_no_$i"); done
for i in $(seq -w 1 15); do PHASES+=("lro_sm_$i"); done

mkdir -p "$WORK/listings" "$WORK/labels" "$WORK/probe"
md5_name=$("${CURL[@]}" "$ROOT/" | grep -oE 'lrolol_1xxx_[0-9]{6}\.md5' | sort -u | tail -1)
[ -s "$WORK/$md5_name" ] || "${CURL[@]}" --output "$WORK/$md5_name" "$ROOT/$md5_name"
echo "volume md5 list: $md5_name"

out="$RECIPE_DIR/sources.tsv.new"
printf 'phase\tfile\tdat_bytes\tdat_md5\trecords\tlbl_md5\tmission_phase_name\tcandidate_rank\tprobe_kept_fraction\n' > "$out"
for phase in "${PHASES[@]}"; do
  "${CURL[@]}" --output "$WORK/listings/$phase.html" "$BASE/$phase/"
  python3 -I "$H" listing --html "$WORK/listings/$phase.html" > "$WORK/listings/$phase.tsv"
  n=$(wc -l < "$WORK/listings/$phase.tsv")
  read -r -a order <<< "$(python3 -I "$H" order --count "$n")"
  picked=""
  rank=0
  for pos in "${order[@]}"; do
    rank=$((rank + 1))
    line=$(sed -n "$((pos + 1))p" "$WORK/listings/$phase.tsv")
    name=${line%%$'\t'*}
    size=${line##*$'\t'}
    rm -rf "$WORK/probe/$name"
    python3 -I "$H" probe-config --url "$BASE/$phase/$name" --bytes "$size" \
      --chunks "$PROBE_CHUNKS" --records "$PROBE_RECORDS" --out "$WORK/probe/$name" > "$WORK/probe/$name.cfg"
    "${CURL[@]}" -K "$WORK/probe/$name.cfg"
    frac=$(python3 -I "$H" probe-stats --dir "$WORK/probe/$name" --chunks "$PROBE_CHUNKS")
    echo "$phase rank=$rank $name probe_kept_fraction=$frac"
    if awk -v f="$frac" -v t="$SELECT_MIN_FRACTION" 'BEGIN { exit !(f >= t) }'; then
      picked="$name"
      break
    fi
  done
  [ -n "$picked" ] || { echo "FATAL: no candidate in $phase reaches $SELECT_MIN_FRACTION" >&2; exit 1; }
  stem=${picked%.dat}
  "${CURL[@]}" --output "$WORK/labels/$stem.lbl" "$BASE/$phase/$stem.lbl"
  records=$(tr -d '\r' < "$WORK/labels/$stem.lbl" | awk -F'=' '/^FILE_RECORDS/ { gsub(/ /, "", $2); print $2 }')
  mphase=$(tr -d '\r' < "$WORK/labels/$stem.lbl" | awk -F'"' '/^MISSION_PHASE_NAME/ { print $2 }')
  dat_md5=$(python3 -I "$H" md5 --manifest "$WORK/$md5_name" --path "lrolol_1xxx/data/lola_rdr/$phase/$picked")
  lbl_md5=$(python3 -I "$H" md5 --manifest "$WORK/$md5_name" --path "lrolol_1xxx/data/lola_rdr/$phase/$stem.lbl")
  [ "$(md5sum "$WORK/labels/$stem.lbl" | cut -d' ' -f1)" = "$lbl_md5" ] || { echo "FATAL: label MD5 mismatch $stem" >&2; exit 1; }
  [ "$((records * 256))" = "$size" ] || { echo "FATAL: $picked size $size != $records * 256" >&2; exit 1; }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$phase" "$picked" "$size" "$dat_md5" "$records" "$lbl_md5" "$mphase" "$rank" "$frac" >> "$out"
done
mv "$out" "$RECIPE_DIR/sources.tsv"
echo "wrote $RECIPE_DIR/sources.tsv ($(($(wc -l < "$RECIPE_DIR/sources.tsv") - 1)) orbits)"
