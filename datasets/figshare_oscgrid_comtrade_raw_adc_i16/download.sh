#!/usr/bin/env bash
# Download the pinned OscGrid labeled raw COMTRADE archive (figshare article
# 28465427, file 60073955, Labeled_raw_v1.1.7z) after validating the live
# record's license and file metadata. Resumable; rejects wrong size, MD5, or
# 7z layout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_oscgrid_comtrade_raw_adc_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARTICLE_ID=28465427
API_URL="https://api.figshare.com/v2/articles/$ARTICLE_ID"
FILE_ID=60073955
FILE_NAME="Labeled_raw_v1.1.7z"
FILE_URL="https://ndownloader.figshare.com/files/$FILE_ID"
FILE_BYTES=94882365
FILE_MD5="5e15133fd38bf131115897b8737cbf19"
UA="openzl-public-datasets-oscgrid-comtrade/1.0"
MAX_ATTEMPTS=8

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Live figshare record: identity, CC BY 4.0 license, exact file entry.
metadata="$DOWNLOAD_DIR/article_$ARTICLE_ID.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 - "$metadata" "$ARTICLE_ID" "$FILE_ID" "$FILE_NAME" "$FILE_BYTES" "$FILE_MD5" <<'PY'
import json
import sys

path, article_id, file_id, file_name, file_bytes, file_md5 = sys.argv[1:]
record = json.load(open(path, encoding="utf-8"))
if int(record.get("id") or 0) != int(article_id):
    raise SystemExit(f"unexpected figshare article id {record.get('id')!r}")
title = str(record.get("title") or "")
if "oscillogram" not in title.lower():
    raise SystemExit(f"article title no longer identifies the oscillogram dataset: {title!r}")
license_info = record.get("license") or {}
if license_info.get("name") != "CC BY 4.0" or "creativecommons.org/licenses/by/4.0" not in str(license_info.get("url")):
    raise SystemExit(f"article license changed: {license_info!r}")
if record.get("is_embargoed") or record.get("download_disabled"):
    raise SystemExit("article is embargoed or downloads are disabled")
matches = [f for f in record.get("files") or [] if int(f.get("id") or 0) == int(file_id)]
if len(matches) != 1:
    raise SystemExit(f"file {file_id} not listed exactly once in the article")
entry = matches[0]
if entry.get("name") != file_name or int(entry.get("size") or 0) != int(file_bytes):
    raise SystemExit(f"file entry changed: name={entry.get('name')!r} size={entry.get('size')!r}")
if str(entry.get("computed_md5") or "").lower() != file_md5:
    raise SystemExit(f"file computed_md5 changed: {entry.get('computed_md5')!r}")
print(
    f"metadata_validation=ok article={article_id} version={record.get('version')} "
    f"license={license_info.get('name')} file={file_name} bytes={file_bytes} md5={file_md5}"
)
PY

# 2. Archive: resumable transfer; every attempt re-resolves the ndownloader
#    redirect, so each resume gets a freshly signed (10 s expiry) S3 URL.
target="$DOWNLOAD_DIR/$FILE_NAME"
part="$target.part"

check_md5() {
  local actual
  actual="$(md5sum "$1" | cut -d' ' -f1)"
  [ "$actual" = "$FILE_MD5" ]
}

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$target" "$part"
fi
if [ -f "$target" ] && [ "$(stat -c %s "$target")" = "$FILE_BYTES" ] && check_md5 "$target"; then
  echo "cache_hit file=$target"
else
  rm -f "$target"
  if [ -f "$part" ] && [ "$(stat -c %s "$part")" -gt "$FILE_BYTES" ]; then
    echo "discarding oversized partial file"
    rm -f "$part"
  fi
  attempt=1
  while :; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" = "$FILE_BYTES" ]; then
      break
    fi
    echo "attempt=$attempt resume_from=$have"
    if curl --fail --location --silent --show-error \
      --continue-at - --retry 3 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$FILE_URL"; then
      :
    else
      echo "curl exited with status $? on attempt $attempt"
    fi
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" = "$FILE_BYTES" ]; then
      break
    fi
    if [ "$have" -gt "$FILE_BYTES" ]; then
      echo "FATAL: partial file grew past the pinned size" >&2
      rm -f "$part"
      exit 1
    fi
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
      echo "FATAL: download incomplete after $MAX_ATTEMPTS attempts ($have of $FILE_BYTES bytes)" >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 10
  done
  if ! check_md5 "$part"; then
    echo "FATAL: MD5 mismatch for $FILE_NAME; removing partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  echo "downloaded file=$target bytes=$FILE_BYTES md5=$FILE_MD5"
fi

# 3. Semantic check: a 7z archive whose header lists exactly the 480 labeled
#    cfg/dat pairs in one LZMA1 solid folder.
python3 - "$RECIPE_DIR/scripts" "$target" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
import oscgrid

archive, _read, plans = oscgrid.scan_archive(__import__("pathlib").Path(sys.argv[2]))
folder = archive.streams.folders[0]
print(
    f"archive_validation=ok pairs={len(plans)} members={sum(e.has_stream for e in archive.entries)} "
    f"coder={folder.coder.method.hex()} unpack_bytes={folder.unpack_size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
