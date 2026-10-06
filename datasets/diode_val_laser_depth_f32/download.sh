#!/usr/bin/env bash
# Download the pinned DIODE Depth validation archive (val.tar.gz, 2,774,625,282
# bytes, publisher MD5 5c895d09201b88973c8fe4552a67dd85) with resumable curl,
# after re-checking the MIT license statement on the official dataset page.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="diode_val_laser_depth_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ARCHIVE_URL="https://diode-dataset.s3.amazonaws.com/val.tar.gz"
SITE_URL="https://diode-dataset.org/"
ARCHIVE="$DOWNLOAD_DIR/val.tar.gz"
PART="$ARCHIVE.part"
SITE_PAGE="$DOWNLOAD_DIR/diode-dataset.org.html"
EXPECTED_BYTES=2774625282
EXPECTED_MD5="5c895d09201b88973c8fe4552a67dd85"
UA="openzl-public-datasets-diode-depth/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. License and checksum statement on the official dataset page (small HTML page).
rm -f "$SITE_PAGE.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
  --output "$SITE_PAGE.part" "$SITE_URL"
mv "$SITE_PAGE.part" "$SITE_PAGE"
python3 - "$SITE_PAGE" "$EXPECTED_MD5" <<'PY'
import html
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
sentence = "The DIODE dataset and the code is released using the MIT license."
if sentence not in plain:
    raise SystemExit("FATAL: diode-dataset.org no longer carries the MIT license statement")
if "diode-dataset.s3.amazonaws.com/val.tar.gz" not in text or sys.argv[2] not in plain:
    raise SystemExit("FATAL: diode-dataset.org no longer lists val.tar.gz with the pinned MD5")
print(f"site_validation=ok license=MIT val_md5={sys.argv[2]}")
PY

validate_archive() {
  # size + publisher MD5 + gzip/tar/NPY head structure.
  # Prints the checker's status: 0 valid, 1 corrupt/wrong (delete), 2 MD5-exact
  # but structurally unexpected (keep the file, fail, fix the recipe).
  local rc=0
  python3 "$RECIPE_DIR/scripts/check_archive.py" "$1" "$EXPECTED_BYTES" "$EXPECTED_MD5" >&2 || rc=$?
  echo "$rc"
}

if [ -f "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  rc="$(validate_archive "$ARCHIVE")"
  if [ "$rc" = "0" ]; then
    echo "cache_hit archive=$ARCHIVE"
    echo "[$(date -Is)] download done dataset=$DATASET_ID"
    exit 0
  elif [ "$rc" = "1" ]; then
    echo "cached archive is corrupt or wrong; re-downloading" >&2
    rm -f "$ARCHIVE"
  else
    echo "FATAL: cached archive matches the pinned MD5 but failed the structure check; kept for diagnosis" >&2
    exit 1
  fi
fi
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$ARCHIVE" "$PART"
fi

# 2. Liveness and size: one-byte range GET.
headers="$DOWNLOAD_DIR/val.tar.gz.range.headers"
curl --fail --silent --show-error --location --max-time 60 \
  --retry 5 --retry-delay 3 --retry-all-errors --user-agent "$UA" \
  --range 0-0 --dump-header "$headers" --output /dev/null "$ARCHIVE_URL"
total="$(tr -d '\r' < "$headers" | sed -n 's#^[Cc]ontent-[Rr]ange: bytes 0-0/\([0-9]*\)$#\1#p' | tail -1)"
if [ "$total" != "$EXPECTED_BYTES" ]; then
  echo "FATAL: upstream size '$total' != pinned $EXPECTED_BYTES" >&2
  exit 1
fi
echo "liveness=ok upstream_bytes=$total"

# 3. Resumable transfer into a .part file; stall-based abort, outer retry loop.
part_size() { if [ -f "$PART" ]; then stat -c %s "$PART"; else echo 0; fi; }
if [ "$(part_size)" -gt "$EXPECTED_BYTES" ]; then
  echo "partial file larger than expected; discarding" >&2
  rm -f "$PART"
fi
attempt=0
while [ "$(part_size)" -lt "$EXPECTED_BYTES" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 30 ]; then
    echo "FATAL: transfer incomplete after 30 attempts ($(part_size) of $EXPECTED_BYTES bytes)" >&2
    exit 1
  fi
  echo "[$(date -Is)] transfer attempt $attempt resume_from=$(part_size)"
  if ! curl --fail --show-error --location --silent \
      --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
      --output "$PART" "$ARCHIVE_URL"; then
    echo "curl exited non-zero at $(part_size) bytes; retrying in 10 s" >&2
    sleep 10
  fi
done

rc="$(validate_archive "$PART")"
if [ "$rc" = "1" ]; then
  echo "FATAL: downloaded archive has the wrong size or MD5; removing it" >&2
  rm -f "$PART"
  exit 1
elif [ "$rc" != "0" ]; then
  echo "FATAL: downloaded archive matches the pinned MD5 but failed the structure check; kept as $PART for diagnosis" >&2
  exit 1
fi
mv "$PART" "$ARCHIVE"
printf '%s  %s\n' "$EXPECTED_MD5" "val.tar.gz" > "$DOWNLOAD_DIR/val.tar.gz.md5"
rm -f "$headers"
echo "[$(date -Is)] download done dataset=$DATASET_ID archive=$ARCHIVE bytes=$EXPECTED_BYTES md5=$EXPECTED_MD5"
