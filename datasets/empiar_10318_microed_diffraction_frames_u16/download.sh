#!/usr/bin/env bash
# Fetch 24 pinned MicroED diffraction frames of EMPIAR-10318 (3 per rotation
# series, 8 series) as exact ZIP byte ranges (local header + DEFLATE member,
# about 14.3 MB each, 342 MB in total), plus each archive's central directory
# tail, the EMPIAR entry record, the data directory listing and the EMPIAR FAQ
# licence page. Range transfers resume from the bytes already on disk and are
# stall-bounded; every member is CRC-checked and SMV-validated before it is
# moved into place.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10318_microed_diffraction_frames_u16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/microed_smv.py"
UA="openzl-public-datasets-acquisition/1.0"
ENTRY_URL="https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10318/"
FAQ_URL="https://www.ebi.ac.uk/empiar/faq"
LISTING_URL="https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

fetch_small() {
  local url="$1" target="$2"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --max-time 300 --max-filesize 5000000 --user-agent "$UA" \
    --output "$target.part" "$url"
  mv "$target.part" "$target"
}

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

# fetch_range URL START END TOTAL TARGET
# Appends validated 206 chunks to TARGET.part, resuming from its current size.
fetch_range() {
  local url="$1" start="$2" end="$3" total="$4" target="$5"
  local want=$((end - start + 1)) part="$target.part" chunk="$target.chunk" hdr="$target.hdr"
  local attempt have from rc
  for attempt in 1 2 3 4 5 6 7 8; do
    have="$(file_size "$part")"
    if (( have > want )); then
      echo "oversized partial $(basename "$target") ($have > $want); restarting"
      rm -f "$part"
      have=0
    fi
    (( have == want )) && break
    from=$((start + have))
    echo "fetch $(basename "$target") attempt=$attempt bytes=$from-$end resume_from=$have of $want"
    rm -f "$chunk" "$hdr"
    rc=0
    curl --fail --silent --show-error --location --retry 3 --retry-delay 5 \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize $((want - have + 4096)) --user-agent "$UA" \
      --range "$from-$end" --dump-header "$hdr" --output "$chunk" "$url" || rc=$?
    if [[ -s "$chunk" ]] && python3 "$PY" check-range-headers "$hdr" "$from" "$end" "$total"; then
      cat "$chunk" >> "$part"
    elif [[ -s "$chunk" ]]; then
      echo "discarding chunk without an exact 206 Content-Range"
    fi
    rm -f "$chunk" "$hdr"
    if (( rc != 0 )); then
      echo "curl exited $rc; pausing before resume"
      sleep $((attempt * 10))
    fi
  done
  if [[ "$(file_size "$part")" != "$want" ]]; then
    echo "ERROR: $(basename "$target") has $(file_size "$part") bytes, expected $want" >&2
    exit 1
  fi
}

# 1. Entry metadata, licence evidence and directory listing.
fetch_small "$ENTRY_URL" "$DOWNLOAD_DIR/empiar_10318_entry.json"
python3 "$PY" check-entry "$DOWNLOAD_DIR/empiar_10318_entry.json"
fetch_small "$FAQ_URL" "$DOWNLOAD_DIR/empiar_faq.html"
python3 "$PY" check-license "$DOWNLOAD_DIR/empiar_faq.html"
fetch_small "$LISTING_URL" "$DOWNLOAD_DIR/data_listing.html"
python3 "$PY" check-listing "$DOWNLOAD_DIR/data_listing.html"

# 2. Central directory tails (pinned by SHA-256) of the eight archives.
archives=0
while IFS=$'\t' read -r archive url start end total name; do
  archives=$((archives + 1))
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && python3 "$PY" check-cd "$archive" "$target" >/dev/null 2>&1; then
    echo "cache_hit $name"
    continue
  fi
  rm -f "$target" "$target.part"
  fetch_range "$url" "$start" "$end" "$total" "$target"
  if ! python3 "$PY" check-cd "$archive" "$target.part"; then
    rm -f "$target.part"
    echo "ERROR: central directory of $archive failed validation" >&2
    exit 1
  fi
  mv "$target.part" "$target"
done < <(python3 "$PY" archive-pins)
if (( archives != 8 )); then
  echo "ERROR: pin table yielded $archives archives, expected 8" >&2
  exit 1
fi

# 3. Exact member ranges of the 24 selected frames.
count=0
while IFS=$'\t' read -r archive member url start end total name; do
  count=$((count + 1))
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]]; then
    if python3 "$PY" check-member "$archive" "$member" "$target" >/dev/null 2>&1; then
      echo "cache_hit $name ($count/24)"
      continue
    fi
    echo "discarding invalid local copy of $name"
    rm -f "$target"
  fi
  fetch_range "$url" "$start" "$end" "$total" "$target"
  if ! python3 "$PY" check-member "$archive" "$member" "$target.part"; then
    echo "ERROR: $name failed ZIP/CRC/SMV validation; partial removed" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
  echo "ok $name ($count/24)"
done < <(python3 "$PY" frame-pins)
if (( count != 24 )); then
  echo "ERROR: pin table yielded $count frames, expected 24" >&2
  exit 1
fi

python3 "$PY" inventory --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
