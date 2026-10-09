#!/usr/bin/env bash
# Fetch the single pinned zip of Zenodo record 14841855 (K. Koide, "Driving SLAM
# Test with Livox MID360", CC-BY-4.0) plus the record's API JSON (license and
# checksum evidence).
#
# Validation before the zip is accepted: Zenodo API still reports cc-by-4.0 and
# the pinned size/MD5; the payload matches size 517,088,133 and MD5
# 0836c50859bb1af591966b69da166186; the zip has exactly the two expected
# members; metadata.yaml reports sqlite3 storage, no bag compression and 2,772
# /livox/lidar sensor_msgs/msg/PointCloud2 messages; the db3 member starts with
# the SQLite magic and its CRC-32 checks out over the full 1.47 GB stream.
# Re-runs resume a partial .part file and skip a complete, valid zip.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_livox_mid360_driving_reflectivity_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/livox_bag.py"
RECORD_API="https://zenodo.org/api/records/14841855"
ZIP_NAME="rosbag2_2024_04_16-14_17_01.zip"
ZIP_URL="https://zenodo.org/records/14841855/files/$ZIP_NAME?download=1"
ZIP_SIZE=517088133
ZIP_MD5="0836c50859bb1af591966b69da166186"
UA="openzl-public-datasets-livox-mid360/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR/meta" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$TOOL" self-test

# Record metadata (license, file size and checksum), small.
curl "${CURL_COMMON[@]}" --max-time 120 -o "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json.part" "$RECORD_API"
python3 -I - "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json.part" "$ZIP_NAME" "$ZIP_SIZE" "$ZIP_MD5" <<'PY'
import json, sys
rec = json.load(open(sys.argv[1], encoding="utf-8"))
lic = (rec.get("metadata", {}).get("license") or {}).get("id")
files = {f["key"]: f for f in rec.get("files", [])}
f = files.get(sys.argv[2]) or {}
if lic != "cc-by-4.0":
    sys.exit(f"FATAL: Zenodo record license is {lic!r}, expected cc-by-4.0")
if f.get("size") != int(sys.argv[3]) or f.get("checksum") != "md5:" + sys.argv[4]:
    sys.exit(f"FATAL: Zenodo file entry changed: size={f.get('size')} checksum={f.get('checksum')}")
print(f"license=cc-by-4.0 file={sys.argv[2]} size={f['size']} checksum={f['checksum']}")
PY
mv "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json.part" "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json"

out="$DOWNLOAD_DIR/$ZIP_NAME"
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then rm -f "$out" "$out.part"; fi

if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$ZIP_SIZE" ] \
    && [ "$(md5sum "$out" | cut -d' ' -f1)" = "$ZIP_MD5" ]; then
  echo "zip already present and matches size/md5; skipping fetch"
else
  rm -f "$out"
  # Liveness and range support: one-byte range GET.
  hdr="$DOWNLOAD_DIR/meta/liveness.headers"
  curl "${CURL_COMMON[@]}" --max-time 120 --range 0-0 --dump-header "$hdr" --output /dev/null "$ZIP_URL"
  if ! grep -qiE "^content-range: bytes 0-0/$ZIP_SIZE" "$hdr"; then
    echo "FATAL: zip size changed or byte ranges unsupported" >&2
    tail -n 20 "$hdr" >&2
    exit 1
  fi
  echo "liveness=ok size=$ZIP_SIZE"
  ok=0
  for attempt in 1 2 3 4 5; do
    if curl "${CURL_COMMON[@]}" -C - --speed-limit 1024 --speed-time 120 \
        --max-filesize "$((ZIP_SIZE + 1024))" --output "$out.part" "$ZIP_URL"; then
      ok=1
      break
    fi
    echo "retry attempt=$attempt bytes=$(stat -c %s "$out.part" 2>/dev/null || echo 0)" >&2
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$ZIP_SIZE" ]; then rm -f "$out.part"; fi
    sleep $((attempt * 15))
  done
  [ "$ok" = "1" ] || { echo "FATAL: could not fetch $ZIP_NAME" >&2; exit 1; }
  size="$(stat -c %s "$out.part")"
  if [ "$size" != "$ZIP_SIZE" ]; then
    echo "FATAL: size $size != $ZIP_SIZE" >&2; rm -f "$out.part"; exit 1
  fi
  md5="$(md5sum "$out.part" | cut -d' ' -f1)"
  if [ "$md5" != "$ZIP_MD5" ]; then
    echo "FATAL: md5 $md5 != $ZIP_MD5" >&2; rm -f "$out.part"; exit 1
  fi
  echo "md5=ok $md5"
  # Semantic check on the .part before it is renamed into place.
  if ! python3 -I "$TOOL" check-zip --zip "$out.part" \
      --api-json "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json" \
      --metadata-out "$DOWNLOAD_DIR/meta/metadata.yaml"; then
    echo "FATAL: downloaded zip failed semantic validation" >&2
    exit 1
  fi
  mv "$out.part" "$out"
fi

if [ ! -f "$DOWNLOAD_DIR/meta/metadata.yaml" ]; then
  python3 -I "$TOOL" check-zip --zip "$out" --api-json "$DOWNLOAD_DIR/meta/zenodo_record_14841855.json" \
    --metadata-out "$DOWNLOAD_DIR/meta/metadata.yaml"
fi
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
