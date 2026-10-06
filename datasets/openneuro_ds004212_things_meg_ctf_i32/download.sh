#!/usr/bin/env bash
# Acquire 24 pinned THINGS-MEG res4 headers and range-extract 192 axial-
# gradiometer channel blocks (8 per run) from the matching meg4 objects.
# Whole 518 MB meg4 runs are never fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds004212_things_meg_ctf_i32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
TOOL="$RECIPE_DIR/scripts/ctf_meg.py"
SELECTION="$RECIPE_DIR/selection.tsv"
STREAMS="$RECIPE_DIR/streams.tsv"
UA="openzl-public-datasets-things-meg/1.0"
DESCRIPTION_KEY="ds004212/dataset_description.json"
DESCRIPTION_VERSION="wfsYJNoFXN6rHilyRd9qTP1Uox0FqQcC"
DESCRIPTION_MD5="e1cae4f6b155f8325beb0921809b35c3"
MEG4_BYTES=517824008

mkdir -p "$DOWNLOAD_DIR/res4" "$DOWNLOAD_DIR/streams" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

CURL_SMALL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5
  --retry-all-errors --max-time 120 --user-agent "$UA")
CURL_BULK=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5
  --retry-all-errors --speed-limit 1024 --speed-time 120 --user-agent "$UA")

python3 "$TOOL" selftest

# 1. License evidence: the pinned dataset_description.json object version.
description="$DOWNLOAD_DIR/dataset_description.json"
if [[ ! -f "$description" || "$(md5sum "$description" | awk '{print $1}')" != "$DESCRIPTION_MD5" ]]; then
  "${CURL_SMALL[@]}" --max-filesize 100000 --output "$description.part" \
    "$BASE_URL/$DESCRIPTION_KEY?versionId=$DESCRIPTION_VERSION"
  if [[ "$(md5sum "$description.part" | awk '{print $1}')" != "$DESCRIPTION_MD5" ]]; then
    echo "dataset_description.json MD5 mismatch" >&2
    exit 1
  fi
  mv "$description.part" "$description"
fi
python3 "$TOOL" check-description --path "$description"

# 2. res4 headers (3.19 MB each) at pinned object versions, MD5 = S3 ETag.
runs=0
while IFS=$'\t' read -r subject session run res4_key res4_version res4_size res4_md5 meg4_key meg4_version meg4_size meg4_etag; do
  [[ "$subject" == "subject" || -z "$subject" ]] && continue
  runs=$((runs + 1))
  target="$DOWNLOAD_DIR/res4/${res4_key##*/}"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$res4_size" \
        && "$(md5sum "$target" | awk '{print $1}')" == "$res4_md5" ]]; then
    echo "res4 ok (cached) $subject $session $run"
  else
    # A complete or oversized leftover .part cannot be resumed (HTTP 416).
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" -ge "$res4_size" ]]; then
      rm -f "$target.part"
    fi
    "${CURL_BULK[@]}" -C - --max-filesize "$res4_size" --output "$target.part" \
      "$BASE_URL/$res4_key?versionId=$res4_version"
    if [[ "$(stat -c %s "$target.part")" != "$res4_size" \
          || "$(md5sum "$target.part" | awk '{print $1}')" != "$res4_md5" ]]; then
      echo "res4 size/MD5 mismatch for $subject $session $run" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
    echo "res4 fetched $subject $session $run"
  fi

  # meg4 identity: pinned version must still report the pinned size and ETag,
  # and its first 8 bytes must be the CTF 'MEG41CP\0' magic.
  meg4_url="$BASE_URL/$meg4_key?versionId=$meg4_version"
  headers="$("${CURL_SMALL[@]}" --head "$meg4_url" | tr -d '\r')"
  length="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  etag="$(printf '%s\n' "$headers" | awk 'tolower($1)=="etag:"{v=$2} END{gsub(/"/,"",v); print v}')"
  if [[ "$length" != "$meg4_size" || "$length" != "$MEG4_BYTES" || "$etag" != "$meg4_etag" ]]; then
    echo "meg4 identity changed for $subject $session $run: length=$length etag=$etag" >&2
    exit 1
  fi
  magic="$("${CURL_SMALL[@]}" --range 0-7 --max-filesize 9 "$meg4_url" | od -An -c | tr -d ' \n')"
  if [[ "$magic" != 'MEG41CP\0' ]]; then
    echo "meg4 magic mismatch for $subject $session $run: $magic" >&2
    exit 1
  fi
done < "$SELECTION"
if [[ "$runs" -ne 24 ]]; then
  echo "expected 24 runs in selection.tsv, found $runs" >&2
  exit 1
fi

# 3. Re-derive channel indices from every res4 (type-count self-check,
#    identical channel order, single compensation grade) and plan ranges.
PLAN="$DOWNLOAD_DIR/plan.tsv"
python3 "$TOOL" plan --selection "$SELECTION" --streams "$STREAMS" \
  --download-dir "$DOWNLOAD_DIR" --out "$PLAN"

# 4. Exact per-channel byte ranges: channel c of a single-trial run occupies
#    [8 + c*nsamp*4, 8 + (c+1)*nsamp*4).
fetched=0
cached=0
while IFS=$'\t' read -r stream_id byte_start byte_end byte_length url expected_sha256; do
  [[ "$stream_id" == "stream_id" || -z "$stream_id" ]] && continue
  if [[ "$url" != "$BASE_URL/"*"?versionId="* || -z "$expected_sha256" ]]; then
    echo "malformed plan row for $stream_id" >&2
    exit 1
  fi
  sha256_be=""
  if [[ "$expected_sha256" != "-" ]]; then
    sha256_be="$expected_sha256"
  fi
  target="$DOWNLOAD_DIR/streams/$stream_id.i32be"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$byte_length" ]]; then
    cached=$((cached + 1))
    continue
  fi
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$target.part"
    code="$("${CURL_BULK[@]}" --range "$byte_start-$byte_end" --max-filesize "$((byte_length + 1))" \
      --write-out '%{http_code}' --output "$target.part" "$url" || true)"
    if [[ "$code" == "206" && -f "$target.part" && "$(stat -c %s "$target.part")" == "$byte_length" ]]; then
      ok=1
      break
    fi
    echo "range attempt $attempt failed for $stream_id (http=$code)" >&2
    sleep $((attempt * 5))
  done
  if [[ "$ok" -ne 1 ]]; then
    echo "could not fetch exact range for $stream_id" >&2
    exit 1
  fi
  python3 "$TOOL" check-stream --stream-id "$stream_id" --path "$target.part" --expected-sha256 "$sha256_be"
  mv "$target.part" "$target"
  fetched=$((fetched + 1))
  echo "stream fetched $stream_id bytes=$byte_length"
done < "$PLAN"
echo "streams fetched=$fetched cached=$cached"

# 5. Full audit: sizes, pinned hashes, degeneracy, duplicate payloads.
python3 "$TOOL" audit --selection "$SELECTION" --streams "$STREAMS" --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
