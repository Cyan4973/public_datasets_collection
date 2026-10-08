#!/usr/bin/env bash
# Fetch the pinned LoRaIQ v1.0.0 record metadata, dataset.csv, and the exact
# ZIP byte ranges of 256 selected SF10 SigMF data+meta member pairs.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_epfl_loraiq_sf10_iq_frames_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/members"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=17708397
API_URL="https://zenodo.org/api/records/$RECORD_ID"
ARCHIVE_URL="https://zenodo.org/api/records/$RECORD_ID/files/sigmfs.zip/content"
ARCHIVE_BYTES=49746561196
ARCHIVE_MD5="3dc5fbc66ad24aeaa1d1d2a1801c400a"
CSV_URL="https://zenodo.org/api/records/$RECORD_ID/files/dataset.csv/content"
CSV_BYTES=18306157
CSV_MD5="b92831a0c897154e95430e399122791c"
SELECTION="$RECIPE_DIR/selection.tsv"
EXPECTED_MEMBERS=256
EXPECTED_RANGE_BYTES=319698270
UA="openzl-public-datasets-loraiq/1.0"

mkdir -p "$DOWNLOAD_DIR" "$MEMBER_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Record metadata: identity, version, license, and pinned file sizes/MD5s.
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" --header "Accept: application/json" \
  --output "$DOWNLOAD_DIR/record.json.part" "$API_URL"
mv "$DOWNLOAD_DIR/record.json.part" "$DOWNLOAD_DIR/record.json"
python3 -I - "$DOWNLOAD_DIR/record.json" "$RECORD_ID" "$ARCHIVE_BYTES" "$ARCHIVE_MD5" "$CSV_BYTES" "$CSV_MD5" <<'PY'
import json, sys
path, rid, zbytes, zmd5, cbytes, cmd5 = sys.argv[1:]
rec = json.load(open(path, encoding="utf-8"))
md = rec.get("metadata", {})
if int(rec.get("id", 0)) != int(rid):
    raise SystemExit(f"unexpected record id {rec.get('id')!r}")
if "LoRaIQ" not in md.get("title", ""):
    raise SystemExit(f"unexpected title {md.get('title')!r}")
if md.get("version") != "1.0.0":
    raise SystemExit(f"record version changed: {md.get('version')!r}")
lic = md.get("license") or {}
lic_id = str(lic.get("id", "") if isinstance(lic, dict) else lic).lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"license changed: {lic!r}")
files = {f["key"]: f for f in rec.get("files", [])}
for key, size, md5 in (("sigmfs.zip", zbytes, zmd5), ("dataset.csv", cbytes, cmd5)):
    f = files.get(key)
    if not f or int(f["size"]) != int(size) or f.get("checksum") != f"md5:{md5}":
        raise SystemExit(f"{key} size/checksum changed: {f and (f.get('size'), f.get('checksum'))}")
print(f"record_ok id={rid} version=1.0.0 license=cc-by-4.0 sigmfs.zip={zbytes} dataset.csv={cbytes}")
PY

# 2. dataset.csv (frame table), pinned by size + MD5.
csv_path="$DOWNLOAD_DIR/dataset.csv"
if [[ -f "$csv_path" ]] && [[ "$(md5sum "$csv_path" | awk '{print $1}')" == "$CSV_MD5" ]]; then
  echo "cache_hit dataset.csv"
else
  rm -f "$csv_path"
  curl --fail --location -C - --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --silent --show-error --user-agent "$UA" \
    --max-filesize $((CSV_BYTES + 1024)) --output "$csv_path.part" "$CSV_URL"
  actual_size="$(wc -c < "$csv_path.part" | tr -d ' ')"
  actual_md5="$(md5sum "$csv_path.part" | awk '{print $1}')"
  if [[ "$actual_size" != "$CSV_BYTES" || "$actual_md5" != "$CSV_MD5" ]]; then
    echo "FATAL: dataset.csv size/MD5 mismatch size=$actual_size md5=$actual_md5" >&2
    rm -f "$csv_path.part"
    exit 1
  fi
  head -c 200 "$csv_path.part" | head -n 1 | grep -q '^sf,cr,fc,bandwidth,' || { echo "FATAL: dataset.csv header" >&2; exit 1; }
  mv "$csv_path.part" "$csv_path"
fi

# 3. Exact ZIP byte ranges: data local header + member + meta local header + member.
count=0
range_bytes=0
fetched=0
while IFS=$'\t' read -r session rrh file_no area snr nsamp rstart rend rest; do
  [[ "$session" == "session" ]] && continue
  [[ -n "$session" ]] || continue
  name="${session}_${rrh}_${file_no}.zipr"
  target="$MEMBER_DIR/$name"
  want=$((rend - rstart + 1))
  count=$((count + 1))
  range_bytes=$((range_bytes + want))
  if [[ -f "$target" && -f "$target.ok" ]] && [[ "$(wc -c < "$target" | tr -d ' ')" == "$want" ]]; then
    continue
  fi
  rm -f "$target" "$target.ok"
  ok=false
  for attempt in 1 2 3; do
    rm -f "$target.part" "$target.headers"
    if curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
        --max-filesize $((want + 1024)) --range "$rstart-$rend" \
        --dump-header "$target.headers" --output "$target.part" "$ARCHIVE_URL" \
      && python3 -I "$RECIPE_DIR/scripts/loraiq.py" validate --selection "$SELECTION" \
        --range "$target.part" --headers "$target.headers" --name "$name"; then
      ok=true
      break
    fi
    echo "retry $name attempt=$attempt" >&2
    sleep 5
  done
  if [[ "$ok" != true ]]; then
    echo "FATAL: could not fetch a valid range for $name" >&2
    exit 1
  fi
  mv "$target.part" "$target"
  rm -f "$target.headers"
  touch "$target.ok"
  fetched=$((fetched + 1))
  if (( fetched % 25 == 0 )); then echo "[$(date -Is)] progress fetched=$fetched seen=$count"; fi
done < "$SELECTION"

if [[ "$count" -ne "$EXPECTED_MEMBERS" || "$range_bytes" -ne "$EXPECTED_RANGE_BYTES" ]]; then
  echo "FATAL: selection realization mismatch members=$count range_bytes=$range_bytes" >&2
  exit 1
fi
present="$(find "$MEMBER_DIR" -name '*.zipr.ok' | wc -l | tr -d ' ')"
if [[ "$present" -ne "$EXPECTED_MEMBERS" ]]; then
  echo "FATAL: $present validated ranges present, expected $EXPECTED_MEMBERS" >&2
  exit 1
fi
echo "[$(date -Is)] download done members=$count range_bytes=$range_bytes newly_fetched=$fetched"
