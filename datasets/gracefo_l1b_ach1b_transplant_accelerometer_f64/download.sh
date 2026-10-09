#!/usr/bin/env bash
# Fetch the 97 pinned GRACE-FO L1B RL04 ACX2 daily tarballs listed in
# sources.tsv (JPL product mirrored by GFZ ISDC), then semantically validate
# every payload: gzip/tar integrity, presence of ACH1B_<date>_D_04.txt, md5 of
# every member against the in-tarball 'checksum' member, and the ACH1B header
# (title, platform GRACE D, RL04, license URL, DOI, ACH1A input lineage,
# pinned software build). See scripts/ach1b.py validate-downloads.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gracefo_l1b_ach1b_transplant_accelerometer_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TGZ_DIR="$DOWNLOAD_DIR/tgz"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_FILES=97
EXPECTED_BYTES=617255766
UA="openzl-public-datasets-gracefo-ach1b-download/1.0"

mkdir -p "$TGZ_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

plan_files="$(awk -F'\t' 'NR>1 && NF' "$SOURCES" | wc -l)"
plan_bytes="$(awk -F'\t' 'NR>1 && NF {s+=$4} END{printf "%d", s}' "$SOURCES")"
[[ "$plan_files" = "$EXPECTED_FILES" && "$plan_bytes" = "$EXPECTED_BYTES" ]] || {
  echo "FATAL: sources.tsv plan files=$plan_files bytes=$plan_bytes, expected $EXPECTED_FILES/$EXPECTED_BYTES" >&2
  exit 1
}

# Liveness: one-byte range GET on the first pinned file.
first_url="$(awk -F'\t' 'NR==2 {print $8}' "$SOURCES")"
curl --fail --silent --show-error --location --range 0-0 --max-time 60 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

fetched=0
cached=0
while IFS=$'\t' read -r idx day filename size modified etag sha url; do
  [[ "$idx" = "candidate_index" || -z "$idx" ]] && continue
  target="$TGZ_DIR/$filename"
  part="$target.part"
  rm -f "$target.invalid"
  if [[ -f "$target" ]]; then
    if [[ "$(stat -c %s "$target")" = "$size" ]] \
      && { [[ "$sha" = "pending" ]] || [[ "$(sha256sum "$target" | cut -d' ' -f1)" = "$sha" ]]; }; then
      cached=$((cached + 1))
      continue
    fi
    echo "mismatch_existing file=$filename; refetching"
    rm -f "$target"
  fi
  if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
    rm -f "$part"
  fi
  if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
    echo "fetch date=$day bytes=$size file=$filename"
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 30000000 \
      --user-agent "$UA" --output "$part" "$url"
  fi
  actual="$(stat -c %s "$part")"
  if [[ "$actual" != "$size" ]]; then
    echo "FATAL: $filename size $actual != pinned $size (upstream may have reissued it; rerun discover.sh)" >&2
    rm -f "$part"
    exit 1
  fi
  magic="$(od -An -tx1 -N2 "$part" | tr -d ' \n')"
  if [[ "$magic" != "1f8b" ]]; then
    echo "FATAL: $filename is not gzip (magic $magic)" >&2
    rm -f "$part"
    exit 1
  fi
  if [[ "$sha" != "pending" && "$(sha256sum "$part" | cut -d' ' -f1)" != "$sha" ]]; then
    echo "FATAL: $filename sha256 differs from pinned value" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  fetched=$((fetched + 1))
done < "$SOURCES"
echo "transfer_done fetched=$fetched cached=$cached"

local_bytes="$(du -cb "$TGZ_DIR"/*.tgz | tail -n 1 | cut -f1)"
echo "local_tgz_bytes=$local_bytes"
[[ "$local_bytes" = "$EXPECTED_BYTES" ]] || { echo "FATAL: local bytes $local_bytes != $EXPECTED_BYTES" >&2; exit 1; }

PYTHONDONTWRITEBYTECODE=1 python3 -I "$RECIPE_DIR/scripts/ach1b.py" validate-downloads --quarantine \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$SOURCES"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$EXPECTED_FILES bytes=$EXPECTED_BYTES"
