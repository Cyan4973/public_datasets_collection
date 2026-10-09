#!/usr/bin/env bash
# Download the pinned Starlink IRTT/iPerf3 Zenodo archive (record 10020034).
# Only two upstream files are fetched: the 1,169,608,066-byte tar.zst and the
# 3,649-byte README.txt. Both are pinned by size and Zenodo MD5. The archive
# is never extracted to disk; build.sh streams it through `zstd -dc`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_starlink_irtt_rtt_i32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=10020034
API_URL="https://zenodo.org/api/records/$RECORD_ID"
ARCHIVE_NAME="data-20230913-20230917.tar.zst"
ARCHIVE_URL="https://zenodo.org/api/records/$RECORD_ID/files/$ARCHIVE_NAME/content"
ARCHIVE_BYTES=1169608066
ARCHIVE_MD5="7c1fecd817616b49eecd414ecda31c6d"
README_NAME="README.txt"
README_URL="https://zenodo.org/api/records/$RECORD_ID/files/$README_NAME/content"
README_BYTES=3649
README_MD5="4c3cd21a6757c266b301997dfaebc340"
UA="openzl-public-datasets-starlink-irtt/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

command -v zstd >/dev/null || { echo "FATAL: zstd CLI is required" >&2; exit 1; }

# 1. Record metadata: identity, license, and pinned file size/checksum.
metadata="$DOWNLOAD_DIR/record.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 -I - "$metadata" "$RECORD_ID" "$ARCHIVE_NAME" "$ARCHIVE_BYTES" "$ARCHIVE_MD5" \
  "$README_NAME" "$README_BYTES" "$README_MD5" <<'PY'
import json
import sys

path, record_id = sys.argv[1], int(sys.argv[2])
pins = {sys.argv[3]: (int(sys.argv[4]), sys.argv[5]), sys.argv[6]: (int(sys.argv[7]), sys.argv[8])}
with open(path, encoding="utf-8") as handle:
    record = json.load(handle)
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = str(meta.get("title", ""))
if "starlink" not in title.lower() or "latency" not in title.lower():
    raise SystemExit(f"record title does not identify the Starlink latency dataset: {title!r}")
lic = meta.get("license")
lic_id = str(lic.get("id") if isinstance(lic, dict) else lic or "").lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"record license changed: {lic!r}")
access = (record.get("access") or {}).get("record") or meta.get("access_right")
if access not in (None, "public", "open"):
    raise SystemExit(f"record access is not public: {access!r}")
files = {item.get("key"): item for item in record.get("files", []) if isinstance(item, dict)}
for key, (size, md5) in pins.items():
    item = files.get(key)
    if item is None:
        raise SystemExit(f"record no longer lists {key}")
    if int(item.get("size") or -1) != size or str(item.get("checksum", "")).lower() != f"md5:{md5}":
        raise SystemExit(f"{key} changed upstream: size={item.get('size')} checksum={item.get('checksum')}")
print(f"metadata_validation=ok record={record_id} license=cc-by-4.0 title={title!r}")
PY

check_md5() {  # file expected_md5
  local actual
  actual="$(md5sum "$1" | cut -d' ' -f1)"
  if [ "$actual" != "$2" ]; then
    echo "FATAL: md5 mismatch for $1: expected=$2 actual=$actual" >&2
    return 1
  fi
  echo "md5_ok file=$(basename "$1") md5=$actual"
}

fetch_resumable() {  # url output expected_bytes
  local url="$1" out="$2" bytes="$3" have
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$bytes" ]; then
    echo "cache_hit file=$(basename "$out") bytes=$bytes"
    return 0
  fi
  rm -f "$out"
  if [ -f "$out.part" ]; then
    have="$(stat -c %s "$out.part")"
    if [ "$have" -gt "$bytes" ]; then
      echo "discarding oversized partial $out.part ($have > $bytes)"
      rm -f "$out.part"
    else
      echo "resuming $out.part at $have / $bytes bytes"
    fi
  fi
  if [ ! -f "$out.part" ] || [ "$(stat -c %s "$out.part")" -lt "$bytes" ]; then
    curl --fail --show-error --location --silent \
      --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$out.part" "$url"
  fi
  have="$(stat -c %s "$out.part")"
  if [ "$have" != "$bytes" ]; then
    echo "FATAL: $out.part has $have bytes, expected $bytes" >&2
    exit 1
  fi
  mv "$out.part" "$out"
}

# 2. README (provenance and measurement description).
readme="$DOWNLOAD_DIR/$README_NAME"
fetch_resumable "$README_URL" "$readme" "$README_BYTES"
check_md5 "$readme" "$README_MD5" || { rm -f "$readme"; exit 1; }
grep -q "IRTT" "$readme" || { echo "FATAL: README does not describe IRTT" >&2; exit 1; }

# 3. The archive (resumable).
archive="$DOWNLOAD_DIR/$ARCHIVE_NAME"
fetch_resumable "$ARCHIVE_URL" "$archive" "$ARCHIVE_BYTES"
if ! check_md5 "$archive" "$ARCHIVE_MD5"; then
  mv "$archive" "$archive.bad"
  echo "FATAL: archive md5 mismatch; moved to $archive.bad (delete it and re-run)" >&2
  exit 1
fi

# 4. Semantic check: a zstd frame wrapping a POSIX tar whose first entry is data/.
python3 -I - "$archive" <<'PY'
import subprocess
import sys

with open(sys.argv[1], "rb") as handle:
    if handle.read(4) != b"\x28\xb5\x2f\xfd":
        raise SystemExit("archive does not start with the zstd frame magic")
proc = subprocess.Popen(["zstd", "-dc", sys.argv[1]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
head = proc.stdout.read(4096)
proc.kill()
proc.wait()
if len(head) < 1024 or head[257:262] != b"ustar":
    raise SystemExit("decompressed archive is not a POSIX tar stream")
name = head[:100].split(b"\0", 1)[0].decode("utf-8", "replace")
if not name.startswith("data"):
    raise SystemExit(f"unexpected first tar member {name!r}")
print(f"archive_validation=ok first_member={name!r}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
