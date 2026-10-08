#!/usr/bin/env bash
# Documents how members.tsv and the archive pins in scripts/mimii.py were
# resolved (2026-10-06). Not part of the download/build path and never writes
# into the recipe.
#
# Fetches into a scratch directory (default: $TMPDIR or /tmp) the Zenodo
# record JSON and the archive tail [cd_offset, end) of 6_dB_valve.zip
# (492,374 bytes), then runs `mimii.py discover` (EOCD, ZIP64 EOCD,
# central-directory parse, selection rule) and diffs the result against the
# pinned members.tsv.
#
# Usage: bash discover.sh [scratch_dir]
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${1:-${TMPDIR:-/tmp}/zenodo_mimii_valve_mic_array_i16_discover}"
PY=(python3 "$RECIPE_DIR/scripts/mimii.py")
ZIP_URL="https://zenodo.org/api/records/3384388/files/6_dB_valve.zip/content"
c=(curl --fail --silent --show-error --location --retry 10 --retry-delay 10 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "openzl-public-datasets-mimii/1.0")

mkdir -p "$SCRATCH"
"${c[@]}" --output "$SCRATCH/record_3384388.json" "https://zenodo.org/api/records/3384388"
"${PY[@]}" check-record --record "$SCRATCH/record_3384388.json"

# The archive size comes from the record JSON; the central-directory offset
# was first read from a 600,000-byte tail (EOCD -> ZIP64 locator -> ZIP64
# EOCD record: 4,183 entries, cd_offset 6,915,459,463, cd_size 492,276).
read -r first last bytes < <("${PY[@]}" tail-bytes)
"${c[@]}" --range "$first-$last" --output "$SCRATCH/archive_tail.bin" "$ZIP_URL"

"${PY[@]}" discover --tail "$SCRATCH/archive_tail.bin" --members-out "$SCRATCH/members.tsv"
diff "$SCRATCH/members.tsv" "$RECIPE_DIR/members.tsv"
echo "pins reproduced: members.tsv matches $SCRATCH/members.tsv"
