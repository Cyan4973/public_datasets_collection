#!/usr/bin/env bash
# Documents how archives.tsv and members.tsv were resolved (2026-10-06). Not
# part of the download/build path and never writes into the recipe.
#
# Fetches into a scratch directory (default: $TMPDIR or /tmp): the collection
# article listing, the article JSON of the 30 archive articles and of
# FileInfo.csv, the last 1,024 bytes and the central directory of every
# archive (30.5 MB), and FileInfo.csv (31.6 MB). Then runs
# `rousettus.py discover` (archive table + selection rule) and diffs the
# result against the pinned tables.
#
# Usage: bash discover.sh [scratch_dir]
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${1:-${TMPDIR:-/tmp}/figshare_rousettus_vocalizations_i16_discover}"
PY=(python3 "$RECIPE_DIR/scripts/rousettus.py")
NDL="https://ndownloader.figshare.com/files"
c=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "openzl-public-datasets-rousettus/1.0")

size_of() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

mkdir -p "$SCRATCH/api" "$SCRATCH/zip_tails" "$SCRATCH/central_directories"
listing="$SCRATCH/api/collection_articles.json"
[ -s "$listing" ] || "${c[@]}" --output "$listing" "https://api.figshare.com/v2/collections/3666502/articles?page_size=100"

for id in $("${PY[@]}" discover-articles --scratch "$SCRATCH"); do
  [ -s "$SCRATCH/api/article_$id.json" ] || "${c[@]}" --output "$SCRATCH/api/article_$id.json" "https://api.figshare.com/v2/articles/$id"
done

while read -r name file_id size; do
  tail="$SCRATCH/zip_tails/$name.tail"
  [ "$(size_of "$tail")" = 1024 ] || "${c[@]}" --range $((size - 1024))-$((size - 1)) --output "$tail" "$NDL/$file_id"
  read -r cd_offset cd_size < <("${PY[@]}" discover-eocd --tail "$tail" --archive-size "$size")
  cd_file="$SCRATCH/central_directories/$name.cd"
  [ "$(size_of "$cd_file")" = "$cd_size" ] || "${c[@]}" --range "$cd_offset-$((cd_offset + cd_size - 1))" --output "$cd_file" "$NDL/$file_id"
  echo "listing archive=$name cd_offset=$cd_offset cd_size=$cd_size"
done < <("${PY[@]}" discover-files --scratch "$SCRATCH")

[ -s "$SCRATCH/FileInfo.csv" ] || "${c[@]}" --output "$SCRATCH/FileInfo.csv" "$NDL/8900695"

"${PY[@]}" discover --scratch "$SCRATCH" --archives-out "$SCRATCH/archives.tsv" --members-out "$SCRATCH/members.tsv"
diff "$SCRATCH/archives.tsv" "$RECIPE_DIR/archives.tsv"
diff "$SCRATCH/members.tsv" "$RECIPE_DIR/members.tsv"
echo "pins reproduced: archives.tsv and members.tsv match $SCRATCH"
