#!/usr/bin/env bash
# Fetch only the pressure.npy member (plus the archive tail holding the ZIP
# central directory and time.npy) of every selected near_vent_NNNNNN.npz on
# Zenodo record 4127362, by exact HTTP byte range.  Offsets, sizes and CRC32s
# are pinned in scripts/near_vent_members.tsv (produced by discover.sh).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hyburn_argon_decompression_near_vent_pressure_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TABLE="$RECIPE_DIR/scripts/near_vent_members.tsv"
HELPER="$RECIPE_DIR/scripts/hyburn_npz.py"
RECORD_ID=4127362
API_URL="https://zenodo.org/api/records/$RECORD_ID"
BASE="$API_URL/files"
UA="openzl-public-datasets-hyburn-near-vent/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 60 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Record identity, license, and per-file size/MD5 against the pinned table.
for name in record files; do
  url="$API_URL"; [ "$name" = files ] && url="$BASE"
  curl "${CURL_COMMON[@]}" --max-time 300 --max-filesize 20000000 \
    --header "Accept: application/json" --output "$DOWNLOAD_DIR/$name.json.part" "$url"
  mv "$DOWNLOAD_DIR/$name.json.part" "$DOWNLOAD_DIR/$name.json"
done
python3 -I - "$DOWNLOAD_DIR/record.json" "$DOWNLOAD_DIR/files.json" "$TABLE" "$RECORD_ID" <<'PY'
import csv, json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
files = json.load(open(sys.argv[2], encoding="utf-8"))["entries"]
rows = list(csv.DictReader(open(sys.argv[3], encoding="utf-8", newline=""), delimiter="\t"))
if int(record.get("id") or 0) != int(sys.argv[4]):
    raise SystemExit(f"unexpected record id {record.get('id')!r}")
meta = record["metadata"]
if "Standing Shock Prevents Propagation of Sparks" not in meta.get("title", ""):
    raise SystemExit(f"record title changed: {meta.get('title')!r}")
desc = meta.get("description", "")
if "Hyburn" not in desc or "argon" not in desc.lower():
    raise SystemExit("record description no longer identifies the Hyburn argon decompression run")
lic = meta.get("license") or {}
lic_id = lic.get("id") if isinstance(lic, dict) else str(lic)
if str(lic_id).lower() != "cc-by-4.0":
    raise SystemExit(f"license changed: {lic_id!r}")
by_key = {e["key"]: e for e in files}
near_vent = [k for k in by_key if k.startswith("near_vent_")]
if len(near_vent) != len(rows):
    raise SystemExit(f"near_vent file count changed: {len(near_vent)} != {len(rows)}")
for row in rows:
    e = by_key.get(row["key"])
    if e is None:
        raise SystemExit(f"missing upstream file {row['key']}")
    if int(e["size"]) != int(row["npz_size"]) or e["checksum"] != "md5:" + row["npz_md5"]:
        raise SystemExit(f"{row['key']}: size/checksum changed upstream")
selected = sum(r["selected"] == "1" for r in rows)
print(f"metadata_validation=ok record={sys.argv[4]} license=cc-by-4.0 near_vent={len(rows)} selected={selected}")
PY

# 2. Exact byte ranges for every selected snapshot.
python3 -I - "$TABLE" > "$DOWNLOAD_DIR/selected.tsv" <<'PY'
import csv, sys
for r in csv.DictReader(open(sys.argv[1], encoding="utf-8", newline=""), delimiter="\t"):
    if r["selected"] == "1":
        print("\t".join([r["key"], r["npz_size"], r["tail_start"], r["range_start"], r["range_end"]]))
PY

fetch_range() { # url start end out
  local url="$1" start="$2" end="$3" out="$4"
  rm -f "$out.part" "$out.headers.part"
  curl "${CURL_COMMON[@]}" --max-filesize "$((end - start + 1 + 4096))" \
    --range "$start-$end" --dump-header "$out.headers.part" --output "$out.part" "$url"
  mv "$out.headers.part" "$out.headers"
  mv "$out.part" "$out"
}

count=0
total_bytes=0
while IFS=$'\t' read -r key size tail_start start end; do
  stem="${key%.npz}"
  url="$BASE/$key/content"
  tail_file="$DOWNLOAD_DIR/$stem.tail"
  member_file="$DOWNLOAD_DIR/$stem.pressure.zipmember"
  for attempt in 1 2 3; do
    if [ ! -s "$tail_file" ] || [ ! -s "$tail_file.headers" ]; then
      fetch_range "$url" "$tail_start" "$((size - 1))" "$tail_file"
    fi
    if python3 -I "$HELPER" check-tail --table "$TABLE" --key "$key" \
        --tail "$tail_file" --headers "$tail_file.headers"; then
      break
    fi
    echo "WARN: invalid tail for $key (attempt $attempt); refetching" >&2
    rm -f "$tail_file" "$tail_file.headers"
    [ "$attempt" = 3 ] && { echo "FATAL: tail validation failed for $key" >&2; exit 1; }
  done
  for attempt in 1 2 3; do
    if [ ! -s "$member_file" ] || [ ! -s "$member_file.headers" ]; then
      fetch_range "$url" "$start" "$end" "$member_file"
    fi
    if python3 -I "$HELPER" check-member --table "$TABLE" --key "$key" \
        --member "$member_file" --headers "$member_file.headers"; then
      break
    fi
    echo "WARN: invalid pressure.npy member for $key (attempt $attempt); refetching" >&2
    rm -f "$member_file" "$member_file.headers"
    [ "$attempt" = 3 ] && { echo "FATAL: member validation failed for $key" >&2; exit 1; }
  done
  count=$((count + 1))
  total_bytes=$((total_bytes + end - start + 1 + size - tail_start))
  echo "ok $key member_bytes=$((end - start + 1)) (#$count)"
done < "$DOWNLOAD_DIR/selected.tsv"

echo "[$(date -Is)] download done dataset=$DATASET_ID snapshots=$count range_bytes=$total_bytes"
