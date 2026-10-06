#!/usr/bin/env bash
# Fetch the 132 pinned raw DM4 slices of EMPIAR-10994 (every 8th valid slice of
# the control and REEP3/4-KD HeLa cells, about 0.5 GB) plus the EMPIAR entry
# record and the EMPIAR FAQ licence page. Each slice is resumable (curl -C -),
# stall-bounded, size-checked and fully validated (DM4 tag tree, uint16 image,
# acquisition metadata, skeleton SHA-256, and whole-file SHA-256 once pinned)
# before it is moved into place. Re-runs skip valid local files.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10994_sbfsem_bsed_slices_u16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/empiar10994.py"
UA="openzl-public-datasets-acquisition/1.0"
ENTRY_URL="https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10994/"
FAQ_URL="https://www.ebi.ac.uk/empiar/faq"

mkdir -p "$DOWNLOAD_DIR/control" "$DOWNLOAD_DIR/kd" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

python3 "$PY" selftest

fetch_small() {
  local url="$1" target="$2"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --max-time 300 --max-filesize 5000000 --user-agent "$UA" \
    --output "$target.part" "$url"
  mv "$target.part" "$target"
}

fetch_small "$ENTRY_URL" "$DOWNLOAD_DIR/empiar_10994_entry.json"
python3 "$PY" check-entry "$DOWNLOAD_DIR/empiar_10994_entry.json"
fetch_small "$FAQ_URL" "$DOWNLOAD_DIR/empiar_faq.html"
python3 "$PY" check-license "$DOWNLOAD_DIR/empiar_faq.html"

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

total="$(python3 "$PY" pins | wc -l)"
count=0
while IFS=$'\t' read -r cell z name url size; do
  count=$((count + 1))
  target="$DOWNLOAD_DIR/$cell/$name"
  part="$target.part"
  if [[ -f "$target" ]]; then
    if [[ "$(file_size "$target")" == "$size" ]] && python3 "$PY" check-file "$target" "$cell" "$z" >/dev/null; then
      echo "cache_hit $cell/$name ($count/$total)"
      continue
    fi
    echo "discarding invalid local copy of $cell/$name"
    rm -f "$target"
  fi
  for attempt in 1 2 3 4 5 6; do
    have="$(file_size "$part")"
    if (( have > size )); then
      echo "oversized partial $cell/$name ($have > $size); restarting"
      rm -f "$part"
      have=0
    fi
    (( have == size )) && break
    echo "fetch $cell/$name attempt=$attempt resume_from=$have size=$size ($count/$total)"
    if curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$part" "$url"; then
      :
    else
      echo "curl exited $? for $cell/$name; retrying after pause"
      sleep $((attempt * 10))
    fi
  done
  if [[ "$(file_size "$part")" != "$size" ]]; then
    echo "ERROR: $cell/$name has $(file_size "$part") bytes, expected $size" >&2
    exit 1
  fi
  if ! python3 "$PY" check-file "$part" "$cell" "$z"; then
    echo "ERROR: $cell/$name failed semantic validation; partial removed" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
done < <(python3 "$PY" pins)

if (( count != 132 )); then
  echo "ERROR: pin table yielded $count slices, expected 132" >&2
  exit 1
fi
python3 "$PY" inventory --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
