#!/usr/bin/env bash
# Fetch a pinned byte-range prefix of the ATMega8515_raw_traces.h5 DEFLATE
# member inside the official ANSSI ASCAD_data.zip (data.gouv.fr, fr-lo).
# Never downloads the 4.4 GB archive: only the 4 KB zip tail (central
# directory) and the first RANGE_BYTES of the member.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ascad_atmega8515_raw_power_traces_i8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

API_URL="https://www.data.gouv.fr/api/1/datasets/5aaa829dc751df2fbd43eacb/"
ARCHIVE_URL="https://static.data.gouv.fr/resources/ascad/20180530-163000/ASCAD_data.zip"
ARCHIVE_BYTES=4435199469
ARCHIVE_SHA1="fb8c8a71423c80795b4f8592c50891134902666a"
TAIL_BYTES=4096
TAIL_SHA256="bbc7bb44cf87abee4de79b7625dfe26d6325b769ec83ca529cdd5323418db0d3"
MEMBER_OFFSET=72006934
RANGE_BYTES=92000000
# Pinned from the first driver download (2026-10-08).
RANGE_SHA256="256f0a930c6521befbc7ab72352c6d7e6d1535f140a09c5b0a85466caf65cc41"
UA="openzl-public-datasets-ascad/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Dataset identity + license from the data.gouv.fr API.
api_json="$DOWNLOAD_DIR/dataset_api.json"
curl -fsSL --retry 5 --retry-delay 3 --max-time 120 --max-filesize 5000000 \
  -A "$UA" -H "Accept: application/json" -o "$api_json.part" "$API_URL"
mv "$api_json.part" "$api_json"
python3 -I - "$api_json" "$ARCHIVE_URL" "$ARCHIVE_BYTES" "$ARCHIVE_SHA1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
url, size, sha1 = sys.argv[2], int(sys.argv[3]), sys.argv[4]
if d.get("slug") != "ascad" or d.get("title") != "ASCAD":
    raise SystemExit(f"unexpected dataset identity: {d.get('slug')!r} {d.get('title')!r}")
if d.get("license") != "fr-lo":
    raise SystemExit(f"license changed: {d.get('license')!r} (expected fr-lo)")
org = (d.get("organization") or {}).get("name", "")
if "Sécurité des Systèmes" not in org:
    raise SystemExit(f"unexpected publisher: {org!r}")
res = [r for r in d.get("resources", []) if r.get("url") == url]
if len(res) != 1:
    raise SystemExit(f"resource {url} not listed exactly once")
r = res[0]
if int(r.get("filesize") or 0) != size:
    raise SystemExit(f"archive size changed: {r.get('filesize')!r}")
ck = r.get("checksum") or {}
if ck.get("type") != "sha1" or ck.get("value") != sha1:
    raise SystemExit(f"archive checksum changed: {ck!r}")
print(f"api_validation=ok slug=ascad license=fr-lo archive_bytes={size} archive_sha1={sha1}")
PY

# 2. Zip tail (zip64 EOCD + central directory): confirm member offset, method, sizes.
tail_file="$DOWNLOAD_DIR/ASCAD_data.zip.tail4096"
tail_start=$((ARCHIVE_BYTES - TAIL_BYTES))
if ! printf '%s  %s\n' "$TAIL_SHA256" "$tail_file" | sha256sum --check --status 2>/dev/null; then
  curl -fsSL --retry 5 --retry-delay 3 --max-time 120 --max-filesize $((TAIL_BYTES + 1024)) \
    -A "$UA" -r "$tail_start-$((ARCHIVE_BYTES - 1))" -D "$tail_file.headers" \
    -o "$tail_file.part" "$ARCHIVE_URL"
  grep -qiE "^content-range: bytes $tail_start-$((ARCHIVE_BYTES - 1))/$ARCHIVE_BYTES" "$tail_file.headers" \
    || { echo "FATAL: tail Content-Range mismatch" >&2; exit 1; }
  mv "$tail_file.part" "$tail_file"
  printf '%s  %s\n' "$TAIL_SHA256" "$tail_file" | sha256sum --check --status \
    || { echo "FATAL: zip tail sha256 mismatch" >&2; exit 1; }
fi
python3 -I "$RECIPE_DIR/scripts/ascad_traces.py" check-tail --tail "$tail_file"

# 3. Member prefix, resumable by appending explicit sub-ranges to a .part file.
range_file="$DOWNLOAD_DIR/ATMega8515_raw_traces.h5.deflate_prefix"
range_end=$((MEMBER_OFFSET + RANGE_BYTES - 1))
if [ -s "$range_file" ] && [ "$(stat -c %s "$range_file")" != "$RANGE_BYTES" ]; then
  echo "discarding wrong-sized cached prefix"; rm -f "$range_file"
fi
if [ ! -s "$range_file" ]; then
  part="$range_file.part"
  touch "$part"
  attempts=0
  while :; do
    have=$(stat -c %s "$part")
    if [ "$have" -gt "$RANGE_BYTES" ]; then
      echo "FATAL: .part larger than pinned range ($have)" >&2; rm -f "$part"; exit 1
    fi
    [ "$have" -eq "$RANGE_BYTES" ] && break
    attempts=$((attempts + 1))
    if [ "$attempts" -gt 30 ]; then echo "FATAL: range download did not complete" >&2; exit 1; fi
    start=$((MEMBER_OFFSET + have))
    echo "fetching bytes $start-$range_end (have=$have of $RANGE_BYTES, attempt $attempts)"
    # --max-filesize rejects a 200 full-archive response before any body is appended.
    if ! curl -fsSL --speed-limit 1024 --speed-time 120 --connect-timeout 60 \
        --max-filesize $((RANGE_BYTES - have + 1024)) -A "$UA" \
        -r "$start-$range_end" -D "$part.headers" "$ARCHIVE_URL" >> "$part"; then
      echo "curl interrupted; will resume"; sleep 5; continue
    fi
    grep -qiE "^content-range: bytes $start-$range_end/$ARCHIVE_BYTES" "$part.headers" \
      || { echo "FATAL: server did not honor range $start-$range_end" >&2; rm -f "$part"; exit 1; }
  done
  mv "$part" "$range_file"
  rm -f "$part.headers"
fi
range_sha="$(sha256sum "$range_file" | cut -d' ' -f1)"
echo "range_bytes=$RANGE_BYTES range_sha256=$range_sha"
if [ -n "$RANGE_SHA256" ] && [ "$range_sha" != "$RANGE_SHA256" ]; then
  echo "FATAL: member prefix sha256 mismatch (expected $RANGE_SHA256)" >&2; exit 1
fi

# 4. Semantic validation: local header, DEFLATE prefix, HDF5 superblock and
#    'traces' layout, and that the prefix inflates past the last needed trace.
python3 -I "$RECIPE_DIR/scripts/ascad_traces.py" check-range --range "$range_file"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
