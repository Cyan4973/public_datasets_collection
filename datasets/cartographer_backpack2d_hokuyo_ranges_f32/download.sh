#!/usr/bin/env bash
# Download the 16 pinned Cartographer backpack_2d ROS bags listed in sources.tsv.
#
# Each bag is a whole GCS object (bz2 chunks interleave all topics, so there is
# no lean per-topic byte range). Every object is checked against its pinned
# size and MD5 (x-goog-hash) before and after transfer, and the local file must
# carry a valid ROS bag v2.0 header and index section whose horizontal-laser
# message count equals the pinned scan count. The data.rst license section and
# bag listing are re-validated on every run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cartographer_backpack2d_hokuyo_ranges_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
BAG_DIR="$DOWNLOAD_DIR/bags"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
HELPER="$RECIPE_DIR/scripts/cartographer_hokuyo.py"
# data.rst as of its last change (commit ef0e971b, 2018-10-25), identical to master on 2026-10-06
DATA_RST_URL="https://raw.githubusercontent.com/cartographer-project/cartographer_ros/ef0e971b50ed94b06fa29cdd12a311240c56c571/docs/source/data.rst"
DATA_RST_SHA256="97187a77c1b906f9bcaf919455df5c61a6b71a0d7ada4a387a71d424a665a431"
BAG_BASE="https://storage.googleapis.com/cartographer-public-data/bags/backpack_2d"
UA="openzl-public-datasets-cartographer-backpack2d/1.0"
EXPECTED_BAGS=16
EXPECTED_TOTAL_BYTES=1470431881

mkdir -p "$BAG_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# ---------------------------------------------------------------- license page
rm -f "$DOWNLOAD_DIR/data.rst.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 120 --max-filesize 2000000 --user-agent "$UA" \
  --output "$DOWNLOAD_DIR/data.rst.part" "$DATA_RST_URL"
printf '%s  %s\n' "$DATA_RST_SHA256" "$DOWNLOAD_DIR/data.rst.part" | sha256sum --check --status || {
  echo "FATAL: data.rst SHA-256 mismatch" >&2
  exit 1
}
mv "$DOWNLOAD_DIR/data.rst.part" "$DOWNLOAD_DIR/data.rst"
python3 - "$DOWNLOAD_DIR/data.rst" "$SOURCES" "$BAG_BASE" <<'PY'
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
if "2D Cartographer Backpack" not in text or "3D Cartographer Backpack" not in text:
    raise SystemExit("data.rst no longer has the backpack sections")
section = text.split("2D Cartographer Backpack", 1)[1].split("3D Cartographer Backpack", 1)[0]
for needle in ("Copyright 2016 The Cartographer Authors",
               'Licensed under the Apache License, Version 2.0 (the "License");',
               "http://www.apache.org/licenses/LICENSE-2.0"):
    if needle not in section:
        raise SystemExit(f"backpack_2d license text changed: missing {needle!r}")
rows = [line.split("\t") for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()[1:] if line]
for row in rows:
    url = f"{sys.argv[3]}/{row[0]}.bag"
    if url not in section:
        raise SystemExit(f"pinned bag no longer listed in the backpack_2d section: {url}")
print(f"license_validation=ok spdx=Apache-2.0 listed_bags={len(rows)}")
PY

# ---------------------------------------------------------------- helpers
md5_base64() {
  python3 - "$1" <<'PY'
import base64
import hashlib
import sys

digest = hashlib.md5()
with open(sys.argv[1], "rb") as handle:
    while block := handle.read(16 * 1024 * 1024):
        digest.update(block)
print(base64.b64encode(digest.digest()).decode("ascii"))
PY
}

file_size() { stat -c %s "$1"; }

validate_local() {
  local bag="$1" path="$2" size="$3" md5="$4"
  local actual_size actual_md5
  actual_size="$(file_size "$path")"
  if [ "$actual_size" != "$size" ]; then
    echo "size mismatch bag=$bag expected=$size actual=$actual_size" >&2
    return 1
  fi
  actual_md5="$(md5_base64 "$path")"
  if [ "$actual_md5" != "$md5" ]; then
    echo "md5 mismatch bag=$bag expected=$md5 actual=$actual_md5" >&2
    return 1
  fi
  python3 "$HELPER" validate-bag --sources "$SOURCES" --bag "$bag" --path "$path"
}

check_remote() {
  local bag="$1" url="$2" size="$3" md5="$4" headers remote_size remote_md5
  headers="$(curl --fail --silent --show-error --location --head --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
  remote_size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  remote_md5="$(printf '%s\n' "$headers" | sed -n 's/^[Xx]-[Gg]oog-[Hh]ash: md5=//p' | tail -1)"
  if [ "$remote_size" != "$size" ] || [ "$remote_md5" != "$md5" ]; then
    echo "FATAL: upstream object changed bag=$bag size=$remote_size md5=$remote_md5 (pinned $size $md5)" >&2
    return 1
  fi
}

# ---------------------------------------------------------------- bags
rows=0
total=0
while IFS=$'\t' read -r bag unit floor duration size md5 crc gen index_pos chunks scans; do
  [ "$bag" = "bag" ] && continue
  rows=$((rows + 1))
  total=$((total + size))
  url="$BAG_BASE/$bag.bag"
  target="$BAG_DIR/$bag.bag"
  part="$target.part"
  if [ -f "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if validate_local "$bag" "$target" "$size" "$md5"; then
      echo "cache_hit bag=$bag bytes=$size"
      continue
    fi
    echo "cached bag invalid; re-downloading bag=$bag"
    rm -f "$target"
  fi
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$target" "$part"
  fi
  check_remote "$bag" "$url" "$size" "$md5"
  if [ -f "$part" ] && [ "$(file_size "$part")" -gt "$size" ]; then
    rm -f "$part"
  fi
  attempt=0
  while [ ! -f "$part" ] || [ "$(file_size "$part")" -lt "$size" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 8 ]; then
      echo "FATAL: could not complete bag=$bag after $((attempt - 1)) attempts" >&2
      exit 1
    fi
    echo "fetch bag=$bag unit=$unit floor=$floor attempt=$attempt have=$( [ -f "$part" ] && file_size "$part" || echo 0)/$size"
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$url" || {
        echo "curl attempt $attempt for bag=$bag exited non-zero; resuming" >&2
        sleep 5
      }
  done
  if ! validate_local "$bag" "$part" "$size" "$md5"; then
    echo "FATAL: downloaded bag failed validation; removing partial bag=$bag" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  echo "downloaded bag=$bag bytes=$size scans=$scans"
done < "$SOURCES"

if [ "$rows" != "$EXPECTED_BAGS" ] || [ "$total" != "$EXPECTED_TOTAL_BYTES" ]; then
  echo "FATAL: sources.tsv lists $rows bags / $total bytes; expected $EXPECTED_BAGS / $EXPECTED_TOTAL_BYTES" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID bags=$rows bytes=$total"
