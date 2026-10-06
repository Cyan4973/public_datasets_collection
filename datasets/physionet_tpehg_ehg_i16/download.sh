#!/usr/bin/env bash
# Fetch the 300 WFDB records (.hea + .dat) of the PhysioNet Term-Preterm EHG
# Database v1.0.1 plus RECORDS and SHA256SUMS.txt from PhysioNet's official
# open S3 mirror, then validate every file against the pinned checksum list and
# the expected WFDB header semantics.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_tpehg_ehg_i16"
BASE_URL="https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1"
PROJECT_PAGE="https://physionet.org/content/tpehgdb/1.0.1/"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
# sha256 of the official SHA256SUMS.txt of tpehgdb 1.0.1 (606 entries); it
# transitively pins RECORDS and every .hea/.dat file.
SHA256SUMS_SHA256="6da37c0d996bf7706964f291282861449ccb84005500a1c16aefda3d8fcdbf3e"
EXPECTED_RECORDS=300

mkdir -p "$DOWNLOAD_DIR/tpehgdb" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID base=$BASE_URL data_root=$DATA_ROOT"

curl_get() {
  # curl_get <url> <target> <max_bytes>
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
    --max-filesize "$3" -C - --output "$2" "$1"
}

fetch() {
  # fetch <relative path under BASE_URL> <max_bytes>
  local relative="$1" max_bytes="$2"
  local target="$DOWNLOAD_DIR/$relative"
  if [[ -s "$target" ]]; then
    return 0
  fi
  if ! curl_get "$BASE_URL/$relative" "$target.part" "$max_bytes"; then
    echo "retrying from scratch: $relative"
    rm -f "$target.part"
    curl_get "$BASE_URL/$relative" "$target.part" "$max_bytes"
  fi
  mv -f "$target.part" "$target"
}

fetch "SHA256SUMS.txt" 200000
actual_sums="$(sha256sum "$DOWNLOAD_DIR/SHA256SUMS.txt" | cut -d' ' -f1)"
if [[ "$actual_sums" != "$SHA256SUMS_SHA256" ]]; then
  echo "SHA256SUMS.txt changed upstream: $actual_sums != $SHA256SUMS_SHA256" >&2
  rm -f "$DOWNLOAD_DIR/SHA256SUMS.txt"
  exit 1
fi
fetch "RECORDS" 20000
expected_records_sha="$(awk '$2 == "RECORDS" {print $1}' "$DOWNLOAD_DIR/SHA256SUMS.txt")"
actual_records_sha="$(sha256sum "$DOWNLOAD_DIR/RECORDS" | cut -d' ' -f1)"
if [[ -z "$expected_records_sha" || "$actual_records_sha" != "$expected_records_sha" ]]; then
  echo "RECORDS does not match SHA256SUMS.txt: $actual_records_sha != $expected_records_sha" >&2
  rm -f "$DOWNLOAD_DIR/RECORDS"
  exit 1
fi

mapfile -t RECORDS < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' "$DOWNLOAD_DIR/RECORDS")
if [[ "${#RECORDS[@]}" != "$EXPECTED_RECORDS" ]]; then
  echo "RECORDS count changed: ${#RECORDS[@]} != $EXPECTED_RECORDS" >&2
  exit 1
fi

count=0
for record in "${RECORDS[@]}"; do
  if [[ ! "$record" =~ ^tpehgdb/tpehg[0-9]{3,4}$ ]]; then
    echo "unexpected record entry: $record" >&2
    exit 1
  fi
  fetch "$record.hea" 20000
  fetch "$record.dat" 2000000
  count=$((count + 1))
  if (( count % 25 == 0 )); then
    echo "[$(date -Is)] fetched records=$count/$EXPECTED_RECORDS"
  fi
done

# License evidence: the release has no LICENSE file; the project page names it.
LICENSE_PAGE="$DOWNLOAD_DIR/license_evidence/tpehgdb_1.0.1_project_page.html"
mkdir -p "$(dirname "$LICENSE_PAGE")"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 120 \
  --max-filesize 2000000 --output "$LICENSE_PAGE.part" "$PROJECT_PAGE"
mv -f "$LICENSE_PAGE.part" "$LICENSE_PAGE"
for needle in "Open Data Commons Attribution License v1.0" "Anyone can access the files"; do
  if ! grep -q -F "$needle" "$LICENSE_PAGE"; then
    echo "project page no longer states: $needle" >&2
    exit 1
  fi
done
echo "license evidence ok: $PROJECT_PAGE names Open Data Commons Attribution License v1.0"

python3 "$RECIPE_DIR/scripts/validate_download.py" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
