#!/usr/bin/env bash
# Documents how sources.tsv was resolved. It is not part of the download/build
# path. It fetches the 2023..2026 RL04 year listings from GFZ ISDC, applies the
# deterministic selection rule in scripts/select_days.py, and HEADs each
# selected tarball to pin its exact Content-Length, Last-Modified and ETag.
# Output goes to $DATA_DIR/discovery/<id>/sources.discovered.tsv and is
# diffed against the committed sources.tsv. The sha256 column is "pending" in
# discovery output, because ISDC publishes no tarball checksums. Integrity of
# the kept member comes from the md5 'checksum' member inside each tarball.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gracefo_l1b_ach1b_transplant_accelerometer_f64"
BASE_URL="https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-gracefo-ach1b-discover/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

listings=()
for year in 2023 2024 2025 2026; do
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 300 --user-agent "$UA" \
    --output "$OUT_DIR/listing_$year.html" "$BASE_URL/$year/"
  listings+=("$OUT_DIR/listing_$year.html")
done

python3 "$RECIPE_DIR/scripts/select_days.py" "${listings[@]}" > "$OUT_DIR/selection.tsv"

out="$OUT_DIR/sources.discovered.tsv"
printf 'candidate_index\tdate\tfilename\tsize_bytes\tlast_modified\tetag\tsha256\turl\n' > "$out"
while IFS=$'\t' read -r idx day filename; do
  url="$BASE_URL/${day:0:4}/$filename"
  headers="$(curl --fail --silent --show-error --head --location --retry 5 \
    --retry-delay 2 --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
  size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  modified="$(printf '%s\n' "$headers" | sed -n 's/^[Ll]ast-[Mm]odified: //p' | tail -n 1)"
  etag="$(printf '%s\n' "$headers" | sed -n 's/^[Ee][Tt]ag: //p' | tail -n 1 | tr -d '"')"
  [[ "$size" =~ ^[0-9]+$ && "$size" -gt 1000000 ]] || { echo "bad size for $url: $size" >&2; exit 1; }
  modified_iso="$(date -u -d "$modified" +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$idx" "$day" "$filename" "$size" "$modified_iso" "$etag" "pending" "$url" >> "$out"
done < "$OUT_DIR/selection.tsv"

count=$(( $(wc -l < "$out") - 1 ))
bytes="$(awk -F'\t' 'NR>1{s+=$4} END{print s}' "$out")"
echo "selected_files=$count selected_bytes=$bytes"
if [[ -f "$RECIPE_DIR/sources.tsv" ]]; then
  if diff <(cut -f1-6,8 "$RECIPE_DIR/sources.tsv") <(cut -f1-6,8 "$out") > "$OUT_DIR/sources.diff"; then
    echo "committed sources.tsv matches discovery (columns other than sha256)"
  else
    echo "WARNING: committed sources.tsv differs from discovery; see $OUT_DIR/sources.diff"
  fi
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
