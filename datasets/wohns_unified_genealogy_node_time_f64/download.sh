#!/usr/bin/env bash
# Fetch, per chromosome arm, only the ZIP central directory and the two stored
# zarr members `nodes/time/.zarray` + `nodes/time/0` of the 39 modern-sample
# Wohns et al. (2022) unified-genealogy tree sequences (Zenodo 5495535 v1.0.0).
# Pins live in resources.tsv (regenerate with discover.py).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="wohns_unified_genealogy_node_time_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RESOURCES="$RECIPE_DIR/resources.tsv"
HELPER="$RECIPE_DIR/scripts/tsz_nodes_time.py"
RECORD_ID=5495535
API_URL="https://zenodo.org/api/records/$RECORD_ID"
UA="openzl-public-datasets-wohns-genealogy/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

record="$DOWNLOAD_DIR/zenodo_record_$RECORD_ID.json"
rm -f "$record.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 180 --max-filesize 20000000 --user-agent "$UA" --header "Accept: application/json" \
  --output "$record.part" "$API_URL"
mv "$record.part" "$record"

# Record identity, version, license, and every pinned file size/md5.
python3 - "$record" "$RESOURCES" "$RECORD_ID" <<'PY'
import csv
import json
import sys

record = json.load(open(sys.argv[1], encoding="utf-8"))
rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8"), delimiter="\t"))
if int(record.get("id") or 0) != int(sys.argv[3]):
    raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = meta.get("title", "")
if "unified genealogy of modern and ancient genomes" not in title.lower() or "1000 genomes" not in title.lower():
    raise SystemExit(f"record title changed: {title!r}")
if meta.get("version") != "1.0.0":
    raise SystemExit(f"record version changed: {meta.get('version')!r}")
lic = meta.get("license") or {}
lic_id = str(lic.get("id") if isinstance(lic, dict) else lic).lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"record license changed: {lic_id!r}")
files = {f["key"]: f for f in record.get("files", [])}
if len(rows) != 39 or len(files) != 39:
    raise SystemExit(f"expected 39 pinned and 39 record files, got {len(rows)} / {len(files)}")
for r in rows:
    f = files.get(r["file_key"])
    if f is None:
        raise SystemExit(f"pinned file missing from record: {r['file_key']}")
    if int(f["size"]) != int(r["file_size"]) or f.get("checksum") != f"md5:{r['file_md5']}":
        raise SystemExit(f"{r['file_key']}: size/md5 changed ({f['size']}, {f.get('checksum')})")
print(f"record_validation=ok record={sys.argv[3]} version=1.0.0 license=cc-by-4.0 files=39")
PY

fetch_range() {
  # fetch_range URL START END TOTAL OUTPUT
  local url="$1" start="$2" end="$3" total="$4" out="$5"
  local want=$((end - start + 1))
  rm -f "$out.part" "$out.headers"
  curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize "$((want + 4096))" \
    --user-agent "$UA" --range "$start-$end" --dump-header "$out.headers" \
    --output "$out.part" "$url"
  python3 "$HELPER" check-headers "$out.headers" "$start" "$end" "$total"
  local got
  got="$(wc -c < "$out.part" | tr -d ' ')"
  if [ "$got" != "$want" ]; then
    echo "FATAL: $out.part has $got bytes, expected $want" >&2
    exit 1
  fi
  rm -f "$out.headers"
}

tail -n +2 "$RESOURCES" | while IFS=$'\t' read -r arm key fsize _md5 cdoff _cdsize _cdn _zo _zs _zc _co _cs _cc rstart rend; do
  url="https://zenodo.org/api/records/$RECORD_ID/files/$key/content"
  cd_file="$DOWNLOAD_DIR/$arm.cd.bin"
  range_file="$DOWNLOAD_DIR/$arm.nodes_time.bin"

  if [ -s "$cd_file" ] && python3 "$HELPER" validate-cd "$RESOURCES" "$arm" "$cd_file" >/dev/null 2>&1; then
    echo "cache_hit arm=$arm cd"
  else
    fetch_range "$url" "$cdoff" "$((fsize - 1))" "$fsize" "$cd_file"
    python3 "$HELPER" validate-cd "$RESOURCES" "$arm" "$cd_file.part"
    mv "$cd_file.part" "$cd_file"
  fi

  if [ -s "$range_file" ] && python3 "$HELPER" validate-range "$RESOURCES" "$arm" "$range_file" >/dev/null 2>&1; then
    echo "cache_hit arm=$arm nodes_time"
  else
    fetch_range "$url" "$rstart" "$rend" "$fsize" "$range_file"
    python3 "$HELPER" validate-range "$RESOURCES" "$arm" "$range_file.part"
    mv "$range_file.part" "$range_file"
  fi
done

python3 - "$DOWNLOAD_DIR" "$RESOURCES" <<'PY'
import csv
import os
import sys

d = sys.argv[1]
rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8"), delimiter="\t"))
total = 0
for r in rows:
    for suffix, want in ((".cd.bin", int(r["file_size"]) - int(r["cd_offset"])),
                         (".nodes_time.bin", int(r["range_end"]) - int(r["range_start"]) + 1)):
        p = os.path.join(d, r["arm"] + suffix)
        if os.path.getsize(p) != want:
            raise SystemExit(f"FATAL: {p} size mismatch")
        total += want
print(f"download_summary=ok arms={len(rows)} member_and_cd_bytes={total}")
PY
echo "[$(date -Is)] download done dataset=$DATASET_ID"
