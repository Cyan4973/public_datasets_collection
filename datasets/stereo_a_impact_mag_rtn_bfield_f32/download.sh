#!/usr/bin/env bash
# Download the 50 pinned STEREO-A IMPACT/MAG L1 normal-mode RTN V06 daily CDFs
# listed in sources.tsv (999,050,619 bytes). Resumable; validates exact size,
# uncompressed CDF v2.6+/v3 magic, network encoding, GDR eof == size, and the
# pinned SHA-256 when sources.tsv carries one.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="stereo_a_impact_mag_rtn_bfield_f32"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
CDF_DIR="$DOWNLOAD_DIR/cdf"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-stereo-mag-download/1.0"
EXPECTED_FILES=50
EXPECTED_BYTES=999050619

mkdir -p "$CDF_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Liveness: one-byte range GET on the first pinned file.
first_url="$(awk -F'\t' 'NR==2{print $6}' "$RECIPE_DIR/sources.tsv")"
curl -fsSL --max-time 60 --retry 3 -A "$UA" -r 0-0 -o /dev/null "$first_url" \
  || { echo "source host not reachable: $first_url" >&2; exit 1; }

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'date\tfilename\tsize_bytes\tsha256\turl\n' > "$plan"
count=0
total=0
# Tab is an IFS-whitespace character, so consecutive tabs (empty sha256 column)
# would collapse; translate to the non-whitespace unit separator first.
while IFS=$'\037' read -r day name size last_modified pinned_sha url; do
  [[ "$day" != "date" ]] || continue
  [[ "$name" =~ ^STA_L1_MAG_RTN_[0-9]{8}_V06\.cdf$ ]] || { echo "bad filename $name" >&2; exit 1; }
  [[ "$size" =~ ^[0-9]+$ ]] || { echo "bad size '$size' for $name" >&2; exit 1; }
  [[ "$url" == https://stereo-ssc.nascom.nasa.gov/*/"$name" ]] || { echo "bad url '$url' for $name" >&2; exit 1; }
  [[ -z "$pinned_sha" || "$pinned_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "bad sha256 '$pinned_sha' for $name" >&2; exit 1; }
  target="$CDF_DIR/$name"
  if [[ -s "$target" && "$(stat -c %s "$target")" = "$size" ]]; then
    echo "cache_hit $name"
  else
    part="$target.part"
    # A previous run may have quarantined a full-size file (e.g. before the
    # CDF v3 layout was accepted); re-validate it instead of refetching.
    if [[ -f "$target.invalid" && ! -s "$part" ]]; then
      mv "$target.invalid" "$part"
    fi
    if [[ -s "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
      echo "oversized partial for $name; restarting"; : > "$part"
    fi
    if [[ ! -s "$part" || "$(stat -c %s "$part")" != "$size" ]]; then
      echo "fetch $name ($size bytes)"
      curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 -A "$UA" -o "$part" "$url"
    fi
    mv "$part" "$target"
  fi
  python3 -I "$RECIPE_DIR/scripts/check_cdf_header.py" "$target" "$size" \
    || { echo "invalid CDF payload: $name" >&2; mv "$target" "$target.invalid"; exit 1; }
  sha="$(sha256sum "$target" | awk '{print $1}')"
  if [[ -n "$pinned_sha" && "$sha" != "$pinned_sha" ]]; then
    echo "SHA-256 mismatch $name: $sha != $pinned_sha" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$day" "$name" "$size" "$sha" "$url" >> "$plan"
  count=$((count + 1))
  total=$((total + size))
done < <(tr '\t' '\037' < "$RECIPE_DIR/sources.tsv")

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "file count $count != $EXPECTED_FILES" >&2; exit 1; }
[[ "$total" = "$EXPECTED_BYTES" ]] || { echo "byte total $total != $EXPECTED_BYTES" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$total"
