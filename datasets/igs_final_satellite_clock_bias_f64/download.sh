#!/usr/bin/env bash
# Download the 182 pinned IGS final 30-s clock files (2024 doy 001..182) from the
# BKG IGS Global Data Center over anonymous HTTPS, resumably, and validate them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="igs_final_satellite_clock_bias_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
CLK_DIR="$DOWNLOAD_DIR/clk"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_FILES=182
EXPECTED_BYTES=519688708
UA="openzl-public-datasets-igs-clk/1.0"

mkdir -p "$CLK_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

first_url="$(awk -F'\t' 'NR==2{print $8}' "$SOURCES")"
live="$(curl --silent --show-error --location --range 0-0 --max-time 60 \
  --user-agent "$UA" --output /dev/null --write-out '%{http_code}' "$first_url" || true)"
if [ "$live" != "206" ] && [ "$live" != "200" ]; then
  echo "FATAL: liveness check failed for $first_url (HTTP $live)" >&2
  exit 1
fi
echo "liveness=ok http=$live url=$first_url"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'doy\tgps_week\tfilename\tsize_bytes\tlast_modified\tetag\tsha256\turl\n' > "$plan.part"

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

count=0
bytes=0
# Tab is IFS whitespace (empty fields would collapse), so split on the unit separator.
while IFS=$'\037' read -r doy week filename size_bytes last_modified etag pinned_sha url; do
  [ "$doy" != "doy" ] || continue
  case "$filename" in
    IGS0OPSFIN_2024"$doy"0000_01D_30S_CLK.CLK.gz) ;;
    *) echo "FATAL: unexpected source file name $filename" >&2; exit 1 ;;
  esac
  target="$CLK_DIR/$filename"
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$target" "$target.part"
  fi
  if [ -s "$target" ] && [ "$(file_size "$target")" = "$size_bytes" ]; then
    echo "cache_hit doy=$doy bytes=$size_bytes file=$filename"
  else
    rm -f "$target"
    part="$target.part"
    if [ "$(file_size "$part")" -gt "$size_bytes" ]; then
      rm -f "$part"
    fi
    attempt=0
    while [ "$(file_size "$part")" -lt "$size_bytes" ]; do
      attempt=$((attempt + 1))
      if [ "$attempt" -gt 5 ]; then
        echo "FATAL: could not complete $filename after 5 resumable attempts" >&2
        exit 1
      fi
      echo "fetch doy=$doy week=$week bytes=$size_bytes have=$(file_size "$part") attempt=$attempt"
      curl --fail --location --silent --show-error --continue-at - \
        --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$part" "$url" || sleep 10
    done
    actual="$(file_size "$part")"
    if [ "$actual" != "$size_bytes" ]; then
      rm -f "$part"
      echo "FATAL: size mismatch $filename expected=$size_bytes actual=$actual" >&2
      exit 1
    fi
    if ! gzip -t "$part" 2>/dev/null; then
      rm -f "$part"
      echo "FATAL: gzip integrity (CRC32/ISIZE) check failed for $filename" >&2
      exit 1
    fi
    mv "$part" "$target"
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  if [ -n "$pinned_sha" ] && [ "$sha" != "$pinned_sha" ]; then
    echo "FATAL: sha256 mismatch $filename expected=$pinned_sha actual=$sha" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$doy" "$week" "$filename" "$size_bytes" \
    "$last_modified" "$etag" "$sha" "$url" >> "$plan.part"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < <(tr '\t' '\037' < "$SOURCES")

if [ "$count" != "$EXPECTED_FILES" ] || [ "$bytes" != "$EXPECTED_BYTES" ]; then
  echo "FATAL: expected $EXPECTED_FILES files / $EXPECTED_BYTES bytes, got $count / $bytes" >&2
  exit 1
fi
mv "$plan.part" "$plan"

# Semantic validation: RINEX 3.00 clock header, IGS analysis center, GPS week/day
# identity, PRN LIST == AS satellites, 30 s lattice, 12-decimal finite tokens.
python3 "$RECIPE_DIR/scripts/igs_clk.py" check-downloads \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$SOURCES"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
