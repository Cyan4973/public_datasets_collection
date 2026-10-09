#!/usr/bin/env bash
# Download the pinned Zenodo 5545821 record metadata and the 10 legacy
# Oxford HKL CHANNEL5 .ctf EBSD maps listed in maps.tsv (about 1.94 GB of
# tab-separated text). Each file is fetched whole with a resumable curl
# (-C -, stall-based --speed-limit/--speed-time, no --max-time) into a .part
# file, then checked for the pinned size and md5 and for a CHANNEL5 header
# (Device 0, 20 kV, 70 deg tilt, pinned grid, BC and BS columns).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_nakhlite_ebsd_band_contrast_slope_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=5545821
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
MAPS_FILE="$RECIPE_DIR/maps.tsv"
UA="openzl-public-datasets-nakhlite-ebsd/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$DOWNLOAD_DIR"/record.json "$DOWNLOAD_DIR"/*.ctf "$DOWNLOAD_DIR"/*.ctf.part
fi

# ---------------------------------------------------------------- metadata
metadata="$DOWNLOAD_DIR/record.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --connect-timeout 30 --max-time 180 --max-filesize 20000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 -I - "$metadata" "$RECORD_ID" "$MAPS_FILE" <<'PY'
import json
import sys

path, record_id, maps_file = sys.argv[1], int(sys.argv[2]), sys.argv[3]
record = json.loads(open(path, encoding="utf-8").read())
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = str(meta.get("title") or "")
if "nakhlite" not in title.lower() or "petrofabric" not in title.lower():
    raise SystemExit(f"record title no longer identifies the nakhlite petrofabric deposit: {title!r}")
lic = meta.get("license")
lic_id = str((lic.get("id") if isinstance(lic, dict) else lic) or "").lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"record license changed: {lic!r}")
access = meta.get("access_right") or (record.get("access") or {}).get("record")
if access not in ("open", "public"):
    raise SystemExit(f"record access changed: {access!r}")
files = {f.get("key"): f for f in record.get("files") or [] if isinstance(f, dict)}
n = 0
for line in open(maps_file, encoding="utf-8"):
    if not line.strip() or line.startswith("#"):
        continue
    _map_id, key, size, md5, *_ = line.rstrip("\n").split("\t")
    item = files.get(key)
    if item is None:
        raise SystemExit(f"record no longer lists {key!r}")
    if int(item.get("size") or -1) != int(size):
        raise SystemExit(f"{key} size changed: {item.get('size')!r} != {size}")
    if str(item.get("checksum") or "").lower() != f"md5:{md5}":
        raise SystemExit(f"{key} checksum changed: {item.get('checksum')!r}")
    n += 1
if n != 10:
    raise SystemExit(f"maps.tsv lists {n} maps, expected 10")
print(f"metadata_validation=ok record={record_id} license=cc-by-4.0 access={access} maps={n} title={title[:70]!r}")
PY

# --------------------------------------------------------------- .ctf maps
check_file() {
  # args: path size md5 xcells ycells step
  local path="$1" size="$2" md5="$3"
  local actual
  actual="$(stat -c %s "$path")"
  if [ "$actual" != "$size" ]; then
    echo "size mismatch $path: $actual != $size" >&2
    return 1
  fi
  if ! printf '%s  %s\n' "$md5" "$path" | md5sum --check --status; then
    echo "md5 mismatch $path" >&2
    return 1
  fi
  python3 -I "$RECIPE_DIR/scripts/check_ctf_header.py" "$path" "$4" "$5" "$6"
}

total=0
while IFS=$'\t' read -r -u 3 map_id key size md5 xcells ycells step; do
  case "$map_id" in ''|'#'*) continue ;; esac
  out="$DOWNLOAD_DIR/$map_id.ctf"
  if [ -s "$out" ]; then
    if check_file "$out" "$size" "$md5" "$xcells" "$ycells" "$step"; then
      echo "cache_hit $map_id.ctf bytes=$size"
      total=$((total + size))
      continue
    fi
    echo "cached $map_id.ctf failed validation; refetching"
    rm -f "$out"
  fi
  encoded="$(python3 -I -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$key")"
  url="$FILE_BASE/$encoded/content"
  # A .part larger than the pinned size cannot be resumed meaningfully.
  if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$size" ]; then
    rm -f "$out.part"
  fi
  ok=0
  for attempt in 1 2 3 4 5; do
    echo "fetch $map_id.ctf <- $url attempt=$attempt"
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -eq "$size" ]; then
      ok=1
      break
    fi
    if curl --fail --silent --show-error --location -C - \
         --retry 10 --retry-delay 5 --retry-all-errors \
         --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
         --max-filesize "$((size + 1024))" \
         --user-agent "$UA" --output "$out.part" "$url"; then
      ok=1
      break
    fi
    echo "curl attempt $attempt failed for $map_id.ctf (partial kept for resume)" >&2
    sleep $((attempt * 15))
  done
  [ "$ok" = "1" ] || { echo "FATAL: could not fetch $map_id.ctf" >&2; exit 1; }
  if ! check_file "$out.part" "$size" "$md5" "$xcells" "$ycells" "$step"; then
    rm -f "$out.part"
    echo "FATAL: $map_id.ctf failed validation after download (removed; re-run to refetch)" >&2
    exit 1
  fi
  mv "$out.part" "$out"
  total=$((total + size))
done 3< "$MAPS_FILE"

echo "ctf_files=10 ctf_bytes=$total"
[ "$total" = "1935123923" ] || { echo "FATAL: expected 1935123923 .ctf bytes, got $total" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID"
