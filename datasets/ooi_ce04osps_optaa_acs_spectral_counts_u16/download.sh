#!/usr/bin/env bash
# Fetch the 33 pinned OPTAAD105 (AC-S serial 128) raw port-agent day files
# (2019-01-01 .. 2019-06-10, every 5th day, see sources.tsv) and reject
# anything that is not a complete, checksum-valid port-agent stream for its
# day carrying >= 15,000 accepted AC-S packets of the pinned deployment.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ooi_ce04osps_optaa_acs_spectral_counts_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-ooi-optaa-download/1.0"
EXPECTED_FILES=33
EXPECTED_BYTES=811779335

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

PLAN="$DOWNLOAD_DIR/download_plan.tsv"
PLAN_TMP="$PLAN.part"
printf 'day\tfilename\tsize_bytes\tetag\tlast_modified\tsha256\turl\n' > "$PLAN_TMP"

count=0
total=0
while IFS=$'\t' read -r day filename size_bytes etag last_modified url; do
  [[ "$day" != "day" ]] || continue
  target="$DOWNLOAD_DIR/$filename"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size_bytes" ]]; then
    echo "cache_hit day=$day bytes=$size_bytes"
  else
    rm -f "$target"
    # Confirm the upstream object is still the pinned one (nginx ETag = mtime-size).
    remote_etag="$(curl --silent --show-error --fail --location --head --max-time 60 \
      --retry 5 --retry-delay 5 --retry-all-errors --user-agent "$UA" "$url" \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{gsub(/"/,"",$2); print $2}' | tail -1)"
    if [[ "$remote_etag" != "$etag" ]]; then
      echo "ETag mismatch day=$day expected=$etag remote=$remote_etag" >&2
      exit 1
    fi
    part="$target.part"
    if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size_bytes" ]]; then
      rm -f "$part"
    fi
    if [[ ! -f "$part" || "$(stat -c %s "$part")" != "$size_bytes" ]]; then
      echo "fetch day=$day bytes=$size_bytes"
      curl --globoff --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$part" "$url"
    fi
    actual="$(stat -c %s "$part")"
    if [[ "$actual" != "$size_bytes" ]]; then
      echo "size mismatch day=$day expected=$size_bytes actual=$actual" >&2
      exit 1
    fi
    mv "$part" "$target"
  fi
  if ! python3 -I "$RECIPE_DIR/scripts/optaa.py" check-file --file "$target" --day "$day" --size "$size_bytes"; then
    echo "semantic validation failed day=$day; removing $target" >&2
    rm -f "$target"
    exit 1
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$day" "$filename" "$size_bytes" "$etag" "$last_modified" "$sha" "$url" >> "$PLAN_TMP"
  count=$((count + 1))
  total=$((total + size_bytes))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_FILES" ]] || { echo "unexpected file count $count" >&2; exit 1; }
[[ "$total" == "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $total" >&2; exit 1; }
mv "$PLAN_TMP" "$PLAN"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$total"
