#!/usr/bin/env bash
# Documents how the pinned tables master_datasets.tsv and sources.tsv were
# resolved. Metadata only: the ExoMol master file, every .def (about 2.3 MB),
# the .def.json of each selected dataset, and HEAD requests for each selected
# .states.bz2. It never fetches .states payloads. The tables are written to
# DISCOVERY_DIR; copy them into the recipe after review. Not part of the
# download/build/verify contract.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="exomol_state_energy_levels_f64"
WORK="${DISCOVERY_DIR:-$DATA_ROOT/discovery/$DATASET_ID}"
UA="openzl-public-datasets-exomol-discover/1.0"
HELPER="$RECIPE_DIR/scripts/exomol_states.py"

mkdir -p "$WORK/def" "$WORK/defjson"
fetch_small() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 120 --max-filesize 5000000 \
    --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

fetch_small "https://www.exomol.com/db/exomol.all" "$WORK/exomol.all"
head -2 "$WORK/exomol.all"

# Every .def listed by the master file (selection needs all state counts).
python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import exomol_states as x
from pathlib import Path
_, _, entries = x.parse_master(Path(sys.argv[2]))
for e in entries:
    print(x.db_url(e["formula"], e["iso_slug"], e["dataset"], ".def") + "\t" + x.def_name(e["iso_slug"], e["dataset"]))
' "$RECIPE_DIR/scripts" "$WORK/exomol.all" > "$WORK/def_urls.tsv"
while IFS=$'\t' read -r url name; do
  [ -s "$WORK/def/$name" ] || fetch_small "$url" "$WORK/def/$name"
done < "$WORK/def_urls.tsv"
echo "def_files=$(wc -l < "$WORK/def_urls.tsv")"

# Selected datasets: .def.json and HEAD of .states.bz2.
python3 "$HELPER" selected --work "$WORK" > "$WORK/selected_urls.txt"
: > "$WORK/heads.tsv"
while read -r url; do
  case "$url" in
    *.def.json) fetch_small "$url" "$WORK/defjson/$(basename "$url")" ;;
    *.states.bz2)
      headers="$(curl --silent --show-error --location --head --max-time 60 \
        --retry 3 --user-agent "$UA" "$url" | tr -d '\r')"
      code="$(printf '%s\n' "$headers" | awk '/^HTTP\//{c=$2} END{print c}')"
      size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{l=$2} END{print l}')"
      modified="$(printf '%s\n' "$headers" | awk 'tolower($1)=="last-modified:"{sub(/^[^:]*: /,""); m=$0} END{print m}')"
      printf '%s\t%s\t%s\t%s\n' "$url" "$code" "$size" "$modified" >> "$WORK/heads.tsv"
      ;;
  esac
done < "$WORK/selected_urls.txt"

python3 "$HELPER" discover --work "$WORK" \
  --out-master "$WORK/master_datasets.tsv" --out-sources "$WORK/sources.tsv" \
  --previous "$RECIPE_DIR/sources.tsv"
echo "wrote $WORK/master_datasets.tsv and $WORK/sources.tsv"
