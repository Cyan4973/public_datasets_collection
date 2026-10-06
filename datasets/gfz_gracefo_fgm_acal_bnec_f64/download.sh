#!/usr/bin/env bash
# Fetch the 64 pinned GRACE-FO FGM ACAL_CORR v0201 daily CDFs listed in
# sources.tsv plus the two ISDC README files (license + version notes), then
# semantically validate every payload (scripts/gracefo_fgm.py validate-downloads).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gfz_gracefo_fgm_acal_bnec_f64"
BASE_URL="https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
CDF_DIR="$DOWNLOAD_DIR/cdf"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_FILES=64
EXPECTED_BYTES=975321560
UA="openzl-public-datasets-gracefo-fgm-download/1.0"

mkdir -p "$CDF_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Pinned plan sanity: count and byte total of sources.tsv.
plan_files="$(awk -F'\t' 'NR>1 && NF' "$SOURCES" | wc -l)"
plan_bytes="$(awk -F'\t' 'NR>1 && NF {s+=$6} END{printf "%d", s}' "$SOURCES")"
[[ "$plan_files" = "$EXPECTED_FILES" && "$plan_bytes" = "$EXPECTED_BYTES" ]] || {
  echo "FATAL: sources.tsv plan files=$plan_files bytes=$plan_bytes, expected $EXPECTED_FILES/$EXPECTED_BYTES" >&2
  exit 1
}

# License / version-note READMEs (small; content-validated, not hash-pinned,
# because GFZ appends processing notes to them over time).
for sat in GF1 GF2; do
  out="$DOWNLOAD_DIR/README_${sat}.txt"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 120 --max-filesize 200000 --user-agent "$UA" \
    --output "$out.part" "$BASE_URL/$sat/README.txt"
  mv "$out.part" "$out"
  echo "readme satellite=$sat bytes=$(stat -c %s "$out")"
done

# Liveness: one-byte range GET on the first pinned file.
first_url="$(awk -F'\t' 'NR==2 {print $10}' "$SOURCES")"
curl --fail --silent --show-error --location --range 0-0 --max-time 60 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

fetched=0
cached=0
while IFS=$'\t' read -r slot day sat note filename size modified etag sha url; do
  [[ "$slot" = "slot" || -z "$slot" ]] && continue
  target="$CDF_DIR/$filename"
  part="$target.part"
  quarantined="$target.invalid"
  if [[ ! -f "$target" && -f "$quarantined" ]]; then
    # A previous run quarantined this file under an older validation policy.
    # Reinstate it only if it is byte-identical to the pinned payload; the
    # semantic validation below re-checks it under the current policy.
    if [[ "$(stat -c %s "$quarantined")" = "$size" ]] \
      && [[ "$(sha256sum "$quarantined" | cut -d' ' -f1)" = "$sha" ]]; then
      mv "$quarantined" "$target"
      echo "reinstated_quarantined file=$filename"
    else
      rm -f "$quarantined"
      echo "discarded_quarantined file=$filename (does not match pinned size/sha256)"
    fi
  fi
  if [[ -f "$target" ]]; then
    if [[ "$(stat -c %s "$target")" = "$size" ]]; then
      cached=$((cached + 1))
      continue
    fi
    echo "size_mismatch_existing file=$filename; refetching"
    rm -f "$target"
  fi
  if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
    rm -f "$part"
  fi
  if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
    echo "fetch slot=$slot satellite=$sat date=$day bytes=$size file=$filename"
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 40000000 \
      --user-agent "$UA" --output "$part" "$url"
  fi
  actual="$(stat -c %s "$part")"
  if [[ "$actual" != "$size" ]]; then
    echo "FATAL: $filename size $actual != pinned $size" >&2
    rm -f "$part"
    exit 1
  fi
  magic="$(od -An -tx1 -N8 "$part" | tr -d ' \n')"
  if [[ "$magic" != "cdf30001cccc0001" ]]; then
    echo "FATAL: $filename is not a whole-file-compressed CDF v3 (magic $magic)" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  fetched=$((fetched + 1))
done < "$SOURCES"
echo "transfer_done fetched=$fetched cached=$cached"

local_bytes="$(du -cb "$CDF_DIR"/*.cdf | tail -n 1 | cut -f1)"
echo "local_cdf_bytes=$local_bytes"

PYTHONDONTWRITEBYTECODE=1 python3 "$RECIPE_DIR/scripts/gracefo_fgm.py" validate-downloads --quarantine \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$SOURCES"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$EXPECTED_FILES bytes=$EXPECTED_BYTES"
