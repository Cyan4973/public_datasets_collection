#!/usr/bin/env bash
# Fetch the pinned AIND BCI trial TIFFs (exact S3 object versions) plus each
# session's data_description.json and session.json, then validate every object
# against its pins (size, S3 ETag, SHA-256 where pinned) and its semantics
# (CC-BY-4.0 license, rig/FOV regime, complete single-channel ScanImage
# acquisition). Resumable; re-runs re-validate cached files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="aind_bci_2p_scanimage_trials_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/aind_bci.py"
SOURCES="$RECIPE_DIR/sources.tsv"
UA="openzl-public-datasets-aind-bci-2p/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# validate_or_reject <file> <local_name>: on success prints the record line.
# Exit 3 from the helper means the bytes are corrupt (size/ETag/SHA-256), so
# they are deleted and a re-run downloads them again. Any other failure is a
# semantic rejection of intact server bytes: they are kept as *.rejected and
# re-validated (not re-downloaded) by the next run.
validate_or_reject() {
  local file="$1" name="$2" rc=0
  line="$(python3 "$HELPER" validate --sources "$SOURCES" --local-name "$name" --path "$file")" || rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  if (( rc == 3 )); then
    rm -f "$file"
    echo "FATAL: $name failed integrity checks; deleted for re-download" >&2
  else
    mv -f "$file" "$DOWNLOAD_DIR/$name.rejected"
    echo "FATAL: $name failed semantic validation; kept as $DOWNLOAD_DIR/$name.rejected" >&2
  fi
  exit 1
}

python3 "$HELPER" check-sources --sources "$SOURCES"
plan="$(python3 "$HELPER" plan --sources "$SOURCES")"
record="$DOWNLOAD_DIR/download_record.tsv"
printf 'kind\tlocal_name\tsize_bytes\tetag_verified\tsha256\tframes\tversion_id\tkey\n' > "$record.tmp"

fetched=0
cached=0
total_bytes=0
while IFS=$'\t' read -r kind local_name size url; do
  [[ -n "$kind" ]] || continue
  target="$DOWNLOAD_DIR/$local_name"
  part="$target.part"
  if [[ -f "$target" ]]; then
    echo "cache_hit kind=$kind file=$local_name"
    cached=$((cached + 1))
    validate_or_reject "$target" "$local_name"
  else
    if [[ -f "$target.rejected" && ! -f "$part" ]] \
      && [[ "$(stat -c %s "$target.rejected")" == "$size" ]]; then
      echo "revalidate previously rejected $local_name without re-downloading"
      mv "$target.rejected" "$part"
    fi
    have=0
    [[ -f "$part" ]] && have="$(stat -c %s "$part")"
    if (( have > size )); then
      rm -f "$part"
      have=0
    fi
    if [[ "$kind" == "trial_tiff" ]]; then
      # Liveness: the pinned version must answer a one-byte range GET (an
      # archived Intelligent-Tiering object would answer 403 InvalidObjectState).
      code="$(curl --silent --show-error --location --range 0-0 --max-time 120 \
        --retry 5 --retry-delay 5 --retry-all-errors --user-agent "$UA" \
        --output /dev/null --write-out '%{http_code}' "$url" || true)"
      if [[ "$code" != "206" ]]; then
        echo "FATAL: liveness range GET for $local_name returned HTTP $code" >&2
        exit 1
      fi
      attempt=0
      while (( have < size )); do
        attempt=$((attempt + 1))
        if (( attempt > 6 )); then
          echo "FATAL: $local_name still incomplete after $((attempt - 1)) curl attempts ($have/$size bytes)" >&2
          exit 1
        fi
        echo "fetch kind=$kind file=$local_name bytes=$size resume_from=$have attempt=$attempt"
        curl --fail --location --silent --show-error -C - \
          --retry 10 --retry-delay 5 --retry-all-errors \
          --speed-limit 1024 --speed-time 120 \
          --user-agent "$UA" --output "$part" "$url" || echo "curl exited $? for $local_name; retrying"
        have=0
        [[ -f "$part" ]] && have="$(stat -c %s "$part")"
        if (( have > size )); then
          echo "FATAL: $local_name grew past the pinned size ($have > $size)" >&2
          rm -f "$part"
          exit 1
        fi
      done
    else
      echo "fetch kind=$kind file=$local_name bytes=$size"
      curl --fail --location --silent --show-error \
        --retry 5 --retry-delay 2 --retry-all-errors --max-time 120 \
        --max-filesize 1000000 --user-agent "$UA" --output "$part" "$url"
    fi
    validate_or_reject "$part" "$local_name"
    mv "$part" "$target"
    fetched=$((fetched + 1))
  fi
  printf '%s\n' "$line" >> "$record.tmp"
  echo "valid $line"
  total_bytes=$((total_bytes + size))
done <<< "$plan"

mv "$record.tmp" "$record"
echo "[$(date -Is)] download done dataset=$DATASET_ID fetched=$fetched cached=$cached bytes=$total_bytes record=$record"
