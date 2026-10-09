#!/usr/bin/env bash
# Fetch the 96 HUTUBS measured-HRIR SOFA files (ppN_HRIRs_measured.sofa) from
# the sofacoustics.org mirror, plus the license evidence (DepositOnce item
# page) and the database documentation. Only the files pinned in files.tsv are
# fetched; the *_simulated.sofa BEM files, head meshes and anthropometry are
# not. Every SOFA file must match its pinned size (and sha256 where pinned) and
# pass semantic validation (HDF5 checksums, DatabaseName=HUTUBS, the CC BY 4.0
# License attribute, ListenerShortName=ppN, Data.IR float64 LE [440,2,256],
# 44.1 kHz, no NaN/fill/all-zero rows) before it is moved into place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hutubs_measured_hrir_f64"
DL_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$DL_DIR/docs" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dest=$DL_DIR"

BASE="https://sofacoustics.org/data/database/hutubs/"
ITEM_URL="https://depositonce.tu-berlin.de/items/dc2a3076-a291-417e-97f0-7697e332c960"
DOC_SIZE=1707195
DOC_SHA256="cb52311e463236bd37890d19dbbbf2dda222b135425d569684dfed07ce2571a4"
TOOL="$RECIPE_DIR/scripts/hutubs_sofa.py"
CURL=(curl -fL --retry 10 --retry-delay 5 --connect-timeout 30 --speed-limit 1024 --speed-time 120 -sS)

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

python3 -I "$RECIPE_DIR/scripts/selftest.py"

# 1. License evidence: the DepositOnce item page (DOI 10.14279/depositonce-8487
#    -> handle 11303/9429) must carry dc.rights.uri = CC BY 4.0.
"${CURL[@]}" --max-time 300 -o "$DL_DIR/docs/depositonce_item.html.part" "$ITEM_URL"
python3 -I "$TOOL" license --file "$DL_DIR/docs/depositonce_item.html.part"
mv -f "$DL_DIR/docs/depositonce_item.html.part" "$DL_DIR/docs/depositonce_item.html"

# 2. Database documentation (FABIAN repeats, subject table); pinned size+sha256.
doc="$DL_DIR/docs/Documentation.pdf"
if [ "$(file_size "$doc")" -ne "$DOC_SIZE" ]; then
  rm -f "$doc.part"
  "${CURL[@]}" -o "$doc.part" "${BASE}Documentation.pdf"
  mv -f "$doc.part" "$doc"
fi
[ "$(head -c 5 "$doc")" = "%PDF-" ] || { echo "Documentation.pdf is not a PDF" >&2; exit 1; }
[ "$(file_size "$doc")" -eq "$DOC_SIZE" ] || { echo "Documentation.pdf size $(file_size "$doc") != $DOC_SIZE" >&2; exit 1; }
[ "$(sha256sum "$doc" | cut -d' ' -f1)" = "$DOC_SHA256" ] || { echo "Documentation.pdf sha256 mismatch" >&2; exit 1; }
echo "documentation ok: $doc"

# 3. The 96 measured SOFA files.
n=0
unpinned=0
while IFS=$'\t' read -r subject name size _last_modified sha; do
  dest="$DL_DIR/$name"
  if [ "$(file_size "$dest")" -ne "$size" ]; then
    rm -f "$dest"
    part="$dest.part"
    have="$(file_size "$part")"
    if [ "$have" -gt "$size" ]; then
      echo "$name: partial file larger than pinned size; restarting" >&2
      rm -f "$part"; have=0
    fi
    if [ "$have" -lt "$size" ]; then
      "${CURL[@]}" -C - -o "$part" "$BASE$name"
    fi
    got="$(file_size "$part")"
    if [ "$got" -ne "$size" ]; then
      echo "$name: size $got != pinned $size" >&2
      rm -f "$part"
      exit 1
    fi
    mv -f "$part" "$dest"
  fi
  actual_sha="$(sha256sum "$dest" | cut -d' ' -f1)"
  if [ "$sha" != "-" ]; then
    if [ "$actual_sha" != "$sha" ]; then
      echo "$name: sha256 $actual_sha != pinned $sha" >&2
      mv -f "$dest" "$dest.rejected"
      exit 1
    fi
  else
    unpinned=$((unpinned + 1))
  fi
  if ! python3 -I "$TOOL" validate --file "$dest" --subject "$subject"; then
    mv -f "$dest" "$dest.rejected"
    exit 1
  fi
  n=$((n + 1))
done < <(tail -n +2 "$RECIPE_DIR/files.tsv")

[ "$n" -eq 96 ] || { echo "validated $n files, expected 96" >&2; exit 1; }
(cd "$DL_DIR" && sha256sum pp*_HRIRs_measured.sofa | sort -k2,2V > SHA256SUMS)
echo "files without a pinned sha256 in files.tsv: $unpinned (recorded in $DL_DIR/SHA256SUMS)"
echo "total SOFA bytes: $(cat "$DL_DIR"/pp*_HRIRs_measured.sofa | wc -c)"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$n"
