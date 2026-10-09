#!/usr/bin/env bash
# Download the 24 pinned JANUS SimulationArchive files from Zenodo record 546258.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_janus_solar_system_integer_phase_space_i64"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
RECORD_ID=546258
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_URL_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
FILES_TSV="$RECIPE_DIR/scripts/files.tsv"
DECODER="$RECIPE_DIR/scripts/janus_sa.py"
UA="openzl-public-datasets-janus/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$DECODER" selftest

metadata="$DOWNLOAD_DIR/record.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 -I - "$metadata" "$RECORD_ID" "$FILES_TSV" <<'PY'
import json
import sys

record = json.load(open(sys.argv[1], encoding="utf-8"))
if int(record.get("id") or 0) != int(sys.argv[2]):
    raise SystemExit(f"unexpected record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = str(meta.get("title", ""))
if "JANUS" not in title or "Solar System" not in title:
    raise SystemExit(f"record title changed: {title!r}")
lic = meta.get("license")
lic_id = str(lic.get("id", "") if isinstance(lic, dict) else lic or "").lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"record license changed: {lic_id!r}")
live = {f["key"]: (int(f["size"]), str(f["checksum"])) for f in record.get("files", [])}
pinned = {}
for i, line in enumerate(open(sys.argv[3], encoding="utf-8").read().splitlines()):
    if i == 0 or not line.strip():
        continue
    key, size, md5 = line.split("\t")
    pinned[key] = (int(size), f"md5:{md5}")
if live != pinned:
    raise SystemExit(f"Zenodo file list differs from pinned files.tsv: live={sorted(live)} pinned={sorted(pinned)}")
print(f"metadata_validation=ok record={sys.argv[2]} license=cc-by-4.0 files={len(pinned)} bytes={sum(s for s, _ in pinned.values())}")
PY

tail -n +2 "$FILES_TSV" | while IFS=$'\t' read -r key size md5; do
  [ -n "$key" ] || continue
  out="$DOWNLOAD_DIR/$key"
  if [ -f "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if [ "$(stat -c %s "$out")" = "$size" ] && [ "$(md5sum "$out" | cut -d' ' -f1)" = "$md5" ]; then
      echo "cache_hit $key"
      continue
    fi
    echo "cached $key invalid; refetching"
    rm -f "$out"
  fi
  [ "${FORCE_DOWNLOAD:-0}" = "1" ] && rm -f "$out.part"
  if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$size" ]; then
    rm -f "$out.part"
  fi
  if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" = "$size" ]; then
    # Fully fetched by an earlier run that stopped at validation; a resumed
    # range request past EOF would return 416, so re-check it in place.
    echo "[$(date -Is)] recheck complete partial $key ($size bytes)"
  else
    echo "[$(date -Is)] fetch $key ($size bytes)"
    curl --fail --silent --show-error --location -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$out.part" "$FILE_URL_BASE/$key/content"
  fi
  actual_size="$(stat -c %s "$out.part")"
  actual_md5="$(md5sum "$out.part" | cut -d' ' -f1)"
  if [ "$actual_size" != "$size" ] || [ "$actual_md5" != "$md5" ]; then
    echo "FATAL: $key size=$actual_size md5=$actual_md5 expected size=$size md5=$md5" >&2
    rm -f "$out.part"
    exit 1
  fi
  python3 -I "$DECODER" validate "$out.part"
  mv "$out.part" "$out"
done

echo "[$(date -Is)] download done dataset=$DATASET_ID"
