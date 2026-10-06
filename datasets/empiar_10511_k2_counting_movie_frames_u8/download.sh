#!/usr/bin/env bash
# Fetch, for 40 pinned EMPIAR-10511 K2 counting-mode movies, the 1024-byte MRC
# header and the single frame z = 20 (bytes 284,780,624-299,019,603, exactly
# 14,238,980 bytes) by HTTP range request, plus the EMPIAR entry record and the
# EMPIAR FAQ licence page. Whole 569.6 MB movies are never fetched. About
# 569.6 MB in total. Ranges resume from the bytes already on disk, are
# stall-bounded, must come back as 206 with the exact Content-Range, and every
# header and frame is validated before it is moved into place.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10511_k2_counting_movie_frames_u8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/k2_movie_frames.py"
UA="openzl-public-datasets-acquisition/1.0"
ENTRY_URL="https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10511/"
FAQ_URL="https://www.ebi.ac.uk/empiar/faq"

mkdir -p "$DOWNLOAD_DIR/headers" "$DOWNLOAD_DIR/frames" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

read -r FILE_SIZE HEADER_BYTES FRAME_START FRAME_END FRAME_BYTES _PROBE < <(python3 "$PY" constants)
if [[ "$FILE_SIZE $HEADER_BYTES $FRAME_START $FRAME_END $FRAME_BYTES" != "569560224 1024 284780624 299019603 14238980" ]]; then
  echo "ERROR: unexpected layout constants from $PY" >&2
  exit 1
fi

fetch_small() {
  local url="$1" target="$2"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --max-time 300 --max-filesize 5000000 --user-agent "$UA" \
    --output "$target.part" "$url"
  mv "$target.part" "$target"
}

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

# range_fetch URL START END TARGET: write bytes START..END (inclusive) of URL to
# TARGET.part, resuming from the bytes already there. A chunk is appended only
# if the server answered 206 with Content-Range "bytes FROM-END/FILE_SIZE";
# --max-filesize stops a server that ignores Range from sending the whole movie.
range_fetch() {
  local url="$1" start="$2" end="$3" target="$4"
  local want=$((end - start + 1)) part="$target.part" chunk="$target.chunk" hdr="$target.resp"
  local attempt have from code rc range
  for attempt in 1 2 3 4 5 6 7 8; do
    have="$(file_size "$part")"
    if (( have > want )); then
      echo "oversized partial $(basename "$part") ($have > $want); restarting"
      rm -f "$part"
      have=0
    fi
    (( have == want )) && break
    from=$((start + have))
    echo "range $(basename "$target") bytes=$from-$end attempt=$attempt resume_from=$have"
    rm -f "$chunk" "$hdr"
    rc=0
    code="$(curl --fail --silent --show-error --location \
      --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
      --max-filesize "$want" --user-agent "$UA" --range "$from-$end" \
      --dump-header "$hdr" --output "$chunk" --write-out '%{http_code}' "$url")" || rc=$?
    range="$(tr -d '\r' < "$hdr" 2>/dev/null | awk 'tolower($1)=="content-range:"{v=$2" "$3} END{print v}')"
    if [[ "$code" == "206" && "$range" == "bytes $from-$end/$FILE_SIZE" && -f "$chunk" ]]; then
      cat "$chunk" >> "$part"
    else
      echo "unexpected response code=$code content-range='$range' curl_rc=$rc; chunk discarded"
    fi
    rm -f "$chunk" "$hdr"
    if (( rc != 0 )); then
      echo "curl exited $rc; pausing before retry"
      sleep $((attempt * 10))
    fi
  done
  if [[ "$(file_size "$part")" != "$want" ]]; then
    echo "ERROR: $(basename "$target") has $(file_size "$part") bytes, expected $want" >&2
    exit 1
  fi
}

fetch_small "$ENTRY_URL" "$DOWNLOAD_DIR/empiar_10511_entry.json"
python3 "$PY" check-entry "$DOWNLOAD_DIR/empiar_10511_entry.json"
fetch_small "$FAQ_URL" "$DOWNLOAD_DIR/empiar_faq.html"
python3 "$PY" check-license "$DOWNLOAD_DIR/empiar_faq.html"

count=0
while IFS=$'\t' read -r slot name url header_rel frame_rel; do
  count=$((count + 1))
  header="$DOWNLOAD_DIR/$header_rel"
  frame="$DOWNLOAD_DIR/$frame_rel"

  if [[ -f "$header" ]] && ! python3 "$PY" check-header "$header" "$name" >/dev/null 2>&1; then
    echo "discarding invalid local header for $name"
    rm -f "$header"
  fi
  if [[ ! -f "$header" ]]; then
    rm -f "$header.part"
    range_fetch "$url" 0 $((HEADER_BYTES - 1)) "$header"
    if ! python3 "$PY" check-header "$header.part" "$name"; then
      echo "ERROR: header of $name failed validation" >&2
      rm -f "$header.part"
      exit 1
    fi
    mv "$header.part" "$header"
  fi

  if [[ -f "$frame" ]]; then
    if python3 "$PY" check-frame "$frame" "$header" "$name" >/dev/null 2>&1; then
      echo "cache_hit $name ($count/40)"
      continue
    fi
    echo "discarding invalid local frame for $name"
    rm -f "$frame"
  fi
  echo "fetch slot=$slot $name frame z=20 ($count/40)"
  range_fetch "$url" "$FRAME_START" "$FRAME_END" "$frame"
  if ! python3 "$PY" check-frame "$frame.part" "$header" "$name"; then
    echo "ERROR: frame of $name failed semantic validation; partial removed" >&2
    rm -f "$frame.part"
    exit 1
  fi
  mv "$frame.part" "$frame"
done < <(python3 "$PY" pins)

if (( count != 40 )); then
  echo "ERROR: pin table yielded $count movies, expected 40" >&2
  exit 1
fi
python3 "$PY" inventory --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
