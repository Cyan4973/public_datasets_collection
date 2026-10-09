#!/usr/bin/env bash
# Range-fetch 100 pinned config_<n>.pt members of the 22.6 GB RQCD qcdML ens_001 zip.
# Never downloads the whole archive: one ~1 MiB tail request (Zip64 EOCD + central
# directory) plus one exact byte range per pinned member.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="rqcd_qcdml_quenched_su3_gauge_links_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/members"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/qcdml.py"
MEMBERS_TSV="$RECIPE_DIR/scripts/selected_members.tsv"
API_URL="https://zenodo.org/api/records/15018324"
ARCHIVE_URL="https://zenodo.org/api/records/15018324/files/ens_001_pt.zip/content"
ARCHIVE_BYTES=22571455882
TAIL_BYTES=1048576
UA="openzl-public-datasets-qcdml/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5
  --retry-all-errors --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR" "$MEMBER_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Record metadata: identity, CC-BY-4.0 license, archive size and md5.
record="$DOWNLOAD_DIR/record.json"
rm -f "$record.part"
curl "${CURL_COMMON[@]}" --max-time 180 --max-filesize 5000000 \
  --header "Accept: application/json" --output "$record.part" "$API_URL"
mv "$record.part" "$record"
python3 -I "$HELPER" check-record "$record"

# 2. Archive tail: Zip64 EOCD locator, Zip64 EOCD and full central directory.
tail_file="$DOWNLOAD_DIR/ens_001_pt.zip.tail"
tail_headers="$DOWNLOAD_DIR/ens_001_pt.zip.tail.headers"
tail_start=$((ARCHIVE_BYTES - TAIL_BYTES))
if [ ! -s "$tail_file" ] || [ "$(wc -c < "$tail_file")" -ne "$TAIL_BYTES" ] || [ ! -s "$tail_headers" ]; then
  rm -f "$tail_file.part" "$tail_headers.part"
  curl "${CURL_COMMON[@]}" --max-time 600 --range "$tail_start-$((ARCHIVE_BYTES - 1))" \
    --dump-header "$tail_headers.part" --output "$tail_file.part" "$ARCHIVE_URL"
  mv "$tail_headers.part" "$tail_headers"
  mv "$tail_file.part" "$tail_file"
fi
python3 -I "$HELPER" check-tail --tail "$tail_file" --headers "$tail_headers" --members "$MEMBERS_TSV"

# 3. One exact byte range per pinned member. The fetched range covers the local header
#    (30 bytes + name + up to 1024 bytes of local extra field) plus csize bytes; the
#    helper validates header, DEFLATE end, CRC32 and the inner torch archive, then
#    trims to the exact local-header-plus-data length.
fetched=0
cached=0
while IFS=$'\t' read -r config member offset csize usize crc; do
  out="$MEMBER_DIR/config_${config}.zipmember"
  if [ -s "$out" ] && python3 -I "$HELPER" check-member --members "$MEMBERS_TSV" \
      --config "$config" --path "$out" 2>/dev/null; then
    cached=$((cached + 1))
    continue
  fi
  rm -f "$out"
  end=$((offset + 30 + ${#member} + 1024 + csize - 1))
  part="$MEMBER_DIR/config_${config}.range.part"
  hdr="$MEMBER_DIR/config_${config}.range.headers"
  ok=0
  for attempt in 1 2 3; do
    rm -f "$part" "$hdr"
    if curl "${CURL_COMMON[@]}" --range "$offset-$end" --dump-header "$hdr" \
        --output "$part" "$ARCHIVE_URL" \
      && python3 -I "$HELPER" trim-member --members "$MEMBERS_TSV" --config "$config" \
        --part "$part" --headers "$hdr" --output "$out.tmp"; then
      mv "$out.tmp" "$out"
      ok=1
      break
    fi
    echo "retry config=$config attempt=$attempt"
    sleep 5
  done
  rm -f "$part" "$hdr" "$out.tmp"
  if [ "$ok" != 1 ]; then
    echo "FATAL: could not fetch a valid member for config=$config" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "fetched config=$config ($fetched new, $cached cached)"
done < <(tail -n +2 "$MEMBERS_TSV")

count="$(find "$MEMBER_DIR" -name 'config_*.zipmember' | wc -l | tr -d ' ')"
bytes="$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
if [ "$count" != 100 ]; then
  echo "FATAL: expected 100 validated members, found $count" >&2
  exit 1
fi
echo "members_ok count=$count fetched=$fetched cached=$cached download_dir_bytes=$bytes"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
