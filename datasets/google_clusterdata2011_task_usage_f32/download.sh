#!/usr/bin/env bash
# Download the pinned Google cluster trace clusterdata-2011-2 task_usage parts
# 0-4 of 500 (sha256-pinned from the bucket's SHA256SUM), plus a 256 KiB head
# range of part 5 whose first start time shows that the last 5-minute window
# of part 4 continues into part 5 (so build.sh drops it). Network I/O is curl
# only; Python only parses what curl fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="google_clusterdata2011_task_usage_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-google-clusterdata2011/1.0"

BUCKET="clusterdata-2011-2"
BASE="https://storage.googleapis.com/$BUCKET"
LISTING_API="https://storage.googleapis.com/storage/v1/b/$BUCKET/o?prefix=task_usage/&maxResults=1000&fields=items(name,size,md5Hash),nextPageToken"
LICENSE_URL="https://raw.githubusercontent.com/google/cluster-data/master/ClusterData2011_2.md"

# name|bytes|sha256
SMALL_FILES=(
  "schema.csv|3963|b3490ab5ad8806ef30eb5bdf432b662bc4e280abdec549bb3c3edb4b1ab6baeb"
  "README|407|34ed43fef528d8c972b0559790d9c149755c8acc683b764cc5e2fdf5e77d4008"
  "SHA256SUM|211870|b68993eefffd34d42f2fc6613187048112602d185ffe61992292bacf2c2e9940"
)
# part|bytes|sha256 (bucket SHA256SUM)|md5 (GCS listing, base64)|first start time (us)
FULL_PARTS=(
  "part-00000-of-00500.csv.gz|91723415|841254d3bc4199c26c82890dcd6bc87fcfb1ff23d75be8e39f0337f0ed1c6e28|oS3MledPC4Vjdy5+WElnhA==|600000000"
  "part-00001-of-00500.csv.gz|87188987|1fa83e39536baac92a1646dbe750541c6504e4c26a85b7f45d9259fd16d3919c|gV5es57eCrvoJ4qp0bmpVg==|5612000000"
  "part-00002-of-00500.csv.gz|90861131|7d217e976b9d380635f7330e1c75719858daa636efb2f35b8507823476c7b235|qjQxTFfX9rne+Gt8FZhhvQ==|10623000000"
  "part-00003-of-00500.csv.gz|85937819|4145a0bbd4cce2effc376f6e1204019bfeca49e635dfd358c2ead4be9e7c6416|NtEfxJyM19refjZ5mIA4Gg==|15634000000"
  "part-00004-of-00500.csv.gz|91924797|7b05867afe28b7b829a1fe17b8ed052ac67f4d9242c2714e41fe7046b73fbffd|v6r38p/Y+t44haYwldhzBA==|20645000000"
)
NEXT_NAME="part-00005-of-00500.csv.gz"
NEXT_BYTES=94523727
NEXT_SHA256="dfd03c13513847e6ba81f91fb25950f1922d17da72b386b15b020b0ba5e14e43"
NEXT_MD5="gH4/eL+cXE8jkEMqByt4MQ=="
NEXT_RANGE_END=262143
NEXT_RANGE_BYTES=262144
NEXT_RANGE_SHA256="fd0faf8889ac93caf308e3627f036de4d15801ab9c41d8f4e60510625f05ba59"
NEXT_FIRST_START=25656000000

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

sha_ok() {  # path bytes sha256
  [[ -f "$1" ]] && [[ "$(stat -c %s "$1")" == "$2" ]] \
    && printf '%s  %s\n' "$3" "$1" | sha256sum --check --status
}

small_get() {  # url output [extra curl args...]
  local url="$1" out="$2"
  shift 2
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 6 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
    --max-time 300 --user-agent "$UA" "$@" --output "$out.part" "$url" || return 1
  [[ -s "$out.part" ]] || return 1
  mv "$out.part" "$out" || return 1
}

# 1. License page of the trace (content-checked, not hash-pinned).
license_file="$DOWNLOAD_DIR/ClusterData2011_2.md"
small_get "$LICENSE_URL" "$license_file" --max-filesize 200000
if ! grep -q "The data and trace documentation are made available under the" "$license_file" \
    || ! grep -q "creativecommons.org/licenses/by/4.0" "$license_file" \
    || ! grep -q "clusterdata-2011-2" "$license_file"; then
  echo "FATAL: ClusterData2011_2.md no longer states the CC-BY 4.0 grant for clusterdata-2011-2" >&2
  exit 1
fi
echo "license_validation=ok CC-BY-4.0 bytes=$(stat -c %s "$license_file")"

# 2. Bucket metadata files (pinned).
for spec in "${SMALL_FILES[@]}"; do
  IFS='|' read -r name size sha <<< "$spec"
  target="$DOWNLOAD_DIR/$name"
  if ! sha_ok "$target" "$size" "$sha"; then
    small_get "$BASE/$name" "$target" --max-filesize 1000000
    sha_ok "$target" "$size" "$sha" || { echo "FATAL: $name size/sha256 mismatch" >&2; exit 1; }
  fi
  echo "file_validation=ok $name bytes=$size"
done
for field in "1,start time,INTEGER" "2,end time,INTEGER" "6,CPU rate,FLOAT" \
    "16,cycles per instruction,FLOAT" "17,memory accesses per instruction,FLOAT" "20,sampled CPU usage,FLOAT"; do
  grep -q "^task_usage/part-?????-of-?????.csv.gz,$field," "$DOWNLOAD_DIR/schema.csv" \
    || { echo "FATAL: schema.csv lacks task_usage field $field" >&2; exit 1; }
done
[[ "$(grep -c '^task_usage/' "$DOWNLOAD_DIR/schema.csv")" == 20 ]] \
  || { echo "FATAL: schema.csv does not declare exactly 20 task_usage fields" >&2; exit 1; }
for spec in "${FULL_PARTS[@]}" "$NEXT_NAME|$NEXT_BYTES|$NEXT_SHA256"; do
  IFS='|' read -r name size sha _ <<< "$spec"
  grep -qx "$sha \*task_usage/$name" "$DOWNLOAD_DIR/SHA256SUM" \
    || { echo "FATAL: bucket SHA256SUM does not list $sha for task_usage/$name" >&2; exit 1; }
done
echo "schema_and_checksum_list_validation=ok"

# 3. GCS JSON listing (best effort; the sha256 pins are authoritative).
listing="$DOWNLOAD_DIR/task_usage_listing.json"
if small_get "$LISTING_API" "$listing" --max-filesize 5000000; then
  python3 - "$listing" "${FULL_PARTS[@]}" "$NEXT_NAME|$NEXT_BYTES|$NEXT_SHA256|$NEXT_MD5" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("nextPageToken"):
    raise SystemExit("listing unexpectedly paginated")
items = {i["name"]: i for i in data.get("items", [])}
if len(items) != 500:
    raise SystemExit(f"expected 500 task_usage parts, listing has {len(items)}")
for spec in sys.argv[2:]:
    name, size, _sha, md5 = spec.split("|")[:4]
    item = items.get(f"task_usage/{name}")
    if item is None:
        raise SystemExit(f"listing lacks task_usage/{name}")
    if int(item["size"]) != int(size) or item.get("md5Hash") != md5:
        raise SystemExit(f"listing size/md5 changed for {name}: {item}")
print(f"listing_validation=ok parts={len(items)}")
PY
else
  echo "WARN: GCS JSON listing unavailable; relying on pinned sizes and sha256"
fi

first_start_of_gzip() {  # path -> prints the first row's start time (us) of a (partial) gzip
  python3 - "$1" <<'PY'
import math
import sys
import zlib

with open(sys.argv[1], "rb") as handle:
    raw = handle.read(262144)
text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
line = text.split(b"\n", 1)[0]
fields = line.split(b",")
if len(fields) != 20 or not fields[0].isdigit() or not fields[1].isdigit():
    raise SystemExit(f"unexpected first task_usage row: {line[:160]!r}")
if int(fields[1]) <= int(fields[0]):
    raise SystemExit(f"first row end <= start: {line[:160]!r}")
for col in (5, 15, 16):
    if fields[col] and not math.isfinite(float(fields[col])):
        raise SystemExit(f"first row field {col + 1} not finite: {line[:160]!r}")
print(int(fields[0]))
PY
}

# 4. Full task_usage parts: resumable .part with stall detection, sha256 check,
#    first start time check.
for spec in "${FULL_PARTS[@]}"; do
  IFS='|' read -r name size sha _md5 first_start <<< "$spec"
  target="$DOWNLOAD_DIR/$name"
  if sha_ok "$target" "$size" "$sha"; then
    echo "cache_hit $name"
  else
    rm -f "$target"
    attempt=0
    while :; do
      if [[ -f "$target.part" ]] && [[ "$(stat -c %s "$target.part")" -ge "$size" ]]; then
        if sha_ok "$target.part" "$size" "$sha"; then
          break
        fi
        echo "discarding full-size or oversized .part with wrong sha256: $name"
        rm -f "$target.part"
      fi
      attempt=$((attempt + 1))
      if (( attempt > 20 )); then
        echo "FATAL: giving up on $name after 20 attempts" >&2
        exit 1
      fi
      echo "[$(date -Is)] fetch attempt=$attempt $name have=$(stat -c %s "$target.part" 2>/dev/null || echo 0)/$size"
      curl --fail --silent --show-error --location \
        --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$target.part" "$BASE/task_usage/$name" \
        || { echo "curl exit $? for $name; retrying"; sleep 10; }
    done
    mv "$target.part" "$target"
  fi
  sha_ok "$target" "$size" "$sha" || { echo "FATAL: sha256 mismatch for $name" >&2; exit 1; }
  got="$(first_start_of_gzip "$target")"
  [[ "$got" == "$first_start" ]] || { echo "FATAL: $name starts at $got us, expected $first_start" >&2; exit 1; }
  echo "file_validation=ok $name bytes=$size sha256=$sha first_start_us=$got"
done

# 5. Head range of part 5: its first start time (25,656 s) lies in the window
#    [25,500 s, 25,800 s), so part 4's trailing rows in that window are a
#    partial window continued in part 5 (dropped by build.sh).
next_range="$DOWNLOAD_DIR/${NEXT_NAME%.csv.gz}.head-0-$NEXT_RANGE_END.gz"
if ! sha_ok "$next_range" "$NEXT_RANGE_BYTES" "$NEXT_RANGE_SHA256"; then
  headers="$next_range.headers"
  small_get "$BASE/task_usage/$NEXT_NAME" "$next_range" --range "0-$NEXT_RANGE_END" \
    --max-filesize "$((NEXT_RANGE_BYTES + 1024))" --dump-header "$headers"
  grep -qiE "^content-range: bytes 0-$NEXT_RANGE_END/$NEXT_BYTES" "$headers" \
    || { echo "FATAL: server did not honor the part-5 head range" >&2; exit 1; }
  sha_ok "$next_range" "$NEXT_RANGE_BYTES" "$NEXT_RANGE_SHA256" \
    || { echo "FATAL: part-5 head range sha256 mismatch" >&2; exit 1; }
fi
got="$(first_start_of_gzip "$next_range")"
[[ "$got" == "$NEXT_FIRST_START" ]] || { echo "FATAL: part 5 starts at $got us, expected $NEXT_FIRST_START" >&2; exit 1; }
echo "next_part_head_validation=ok $NEXT_NAME first_start_us=$got"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
