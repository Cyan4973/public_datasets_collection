#!/usr/bin/env bash
# Download the pinned Azure Public Dataset V2 (2019) VM CPU readings files
# 1 and 2 of 195, plus a 64 KiB head range of file 3 whose first timestamp
# shows where the snapshot that file 2 ends inside continues. Network I/O is
# curl only; Python only parses what curl fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="azure_vm2019_cpu_utilization_readings_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-azure-vm2019-cpu/1.0"

REPO="Azure/AzurePublicDataset"
TAG="dataset-v2"
RELEASE_API="https://api.github.com/repos/$REPO/releases/tags/$TAG"
RELEASE_BASE="https://github.com/$REPO/releases/download/$TAG"
LICENSE_URL="https://raw.githubusercontent.com/$REPO/master/LICENSE"

SCHEMA_NAME="schema.csv"
SCHEMA_BYTES=1485
SCHEMA_SHA256="638f5ed7792e9a3bb7e04120d92e4164c20e17adff34a84ff5b996adcbd6c518"

# name|bytes|sha256|first timestamp (s)
FULL_FILES=(
  "trace_data_vm_cpu_readings_vm_cpu_readings-file-1-of-195.csv.gz|856259637|010c375e5e69624c300a2dad1460762364b89b8ca030e1de05dcd808e9d7032a|0"
  "trace_data_vm_cpu_readings_vm_cpu_readings-file-2-of-195.csv.gz|856805928|26d03dee50b36ae4d572d17206431905b3ebb18faa9851efb985d2239eb43389|13200"
)
NEXT_NAME="trace_data_vm_cpu_readings_vm_cpu_readings-file-3-of-195.csv.gz"
NEXT_BYTES=856709133
NEXT_SHA256="497c73bf85d026286b113d62e4a775637c7c9792ccfd406cc9b74c077f185637"
NEXT_RANGE_END=65535
NEXT_RANGE_BYTES=65536
NEXT_RANGE_SHA256="93b3b6f50f0fc9bcdda1ec1e6ed00101fdab3bb2f6883d790c334de799282291"
NEXT_FIRST_TS=26400

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

# 1. Release metadata (best effort: the anonymous GitHub API is rate limited;
#    the sha256 pins below are authoritative either way).
release_json="$DOWNLOAD_DIR/release_dataset-v2.json"
if small_get "$RELEASE_API" "$release_json" --max-filesize 20000000 \
    --header "Accept: application/vnd.github+json"; then
  python3 - "$release_json" "$TAG" "$SCHEMA_NAME|$SCHEMA_BYTES|$SCHEMA_SHA256" \
      "${FULL_FILES[@]}" "$NEXT_NAME|$NEXT_BYTES|$NEXT_SHA256|$NEXT_FIRST_TS" <<'PY'
import json
import sys

release = json.load(open(sys.argv[1], encoding="utf-8"))
if release.get("tag_name") != sys.argv[2]:
    raise SystemExit(f"unexpected release tag: {release.get('tag_name')!r}")
assets = {a.get("name"): a for a in release.get("assets", [])}
cpu = [n for n in assets if "vm_cpu_readings-file-" in str(n)]
if len(cpu) != 195:
    raise SystemExit(f"expected 195 vm_cpu_readings assets, found {len(cpu)}")
for spec in sys.argv[3:]:
    name, size, sha = spec.split("|")[:3]
    asset = assets.get(name)
    if asset is None:
        raise SystemExit(f"release lacks asset {name}")
    if int(asset.get("size") or -1) != int(size):
        raise SystemExit(f"asset size changed for {name}: {asset.get('size')}")
    digest = str(asset.get("digest") or "")
    if digest and digest != f"sha256:{sha}":
        raise SystemExit(f"asset digest changed for {name}: {digest}")
print(f"release_validation=ok tag={release['tag_name']} id={release.get('id')} cpu_assets={len(cpu)}")
PY
else
  echo "WARN: release API unavailable; relying on pinned sizes and sha256"
fi

# 2. License text of the repository that hosts the release assets.
license_file="$DOWNLOAD_DIR/LICENSE"
small_get "$LICENSE_URL" "$license_file" --max-filesize 200000
if ! grep -q "Attribution 4.0 International" "$license_file" \
    || ! grep -q "Creative Commons Attribution 4.0 International Public License" "$license_file"; then
  echo "FATAL: repository LICENSE is no longer CC BY 4.0" >&2
  exit 1
fi
echo "license_validation=ok CC-BY-4.0 bytes=$(stat -c %s "$license_file")"

# 3. schema.csv (pinned).
schema_file="$DOWNLOAD_DIR/$SCHEMA_NAME"
if ! sha_ok "$schema_file" "$SCHEMA_BYTES" "$SCHEMA_SHA256"; then
  small_get "$RELEASE_BASE/$SCHEMA_NAME" "$schema_file" --max-filesize 100000
  sha_ok "$schema_file" "$SCHEMA_BYTES" "$SCHEMA_SHA256" || { echo "FATAL: schema.csv mismatch" >&2; exit 1; }
fi
for field in "3,min cpu,DOUBLE" "4,max cpu,DOUBLE" "5,avg cpu,DOUBLE" "1,timestamp,INTEGER"; do
  grep -q "^vm_cpu_readings/vm_cpu_readings-file-\*-of-195.csv.gz,$field" "$schema_file" \
    || { echo "FATAL: schema.csv lacks field $field" >&2; exit 1; }
done
echo "schema_validation=ok"

# 4. Full CPU-readings files. Always invoke curl on the stable github.com URL
#    (the release-assets redirect is signed and expires); resume the .part.
first_ts_of_gzip() {  # path -> prints first CSV timestamp of a (partial) gzip
  python3 - "$1" <<'PY'
import sys
import zlib

with open(sys.argv[1], "rb") as handle:
    raw = handle.read(65536)
text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
line = text.split(b"\n", 1)[0].rstrip(b"\r")
fields = line.split(b",")
if len(fields) != 5 or len(fields[1]) != 64:
    raise SystemExit(f"unexpected first CSV row: {line[:120]!r}")
for token in fields[2:]:
    value = float(token)
    if not 0.0 <= value <= 100.0:
        raise SystemExit(f"first row CPU value out of range: {token!r}")
print(int(fields[0]))
PY
}

for spec in "${FULL_FILES[@]}"; do
  IFS='|' read -r name size sha first_ts <<< "$spec"
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
        --user-agent "$UA" --output "$target.part" "$RELEASE_BASE/$name" \
        || { echo "curl exit $? for $name; retrying"; sleep 10; }
    done
    mv "$target.part" "$target"
  fi
  sha_ok "$target" "$size" "$sha" || { echo "FATAL: sha256 mismatch for $name" >&2; exit 1; }
  got_ts="$(first_ts_of_gzip "$target")"
  [[ "$got_ts" == "$first_ts" ]] || { echo "FATAL: $name starts at t=$got_ts, expected $first_ts" >&2; exit 1; }
  echo "file_validation=ok $name bytes=$size sha256=$sha first_ts=$got_ts"
done

# 5. Head range of file 3: its first timestamp (26,400) shows that snapshot
#    t = 26,100 is complete and that file 2's trailing t = 26,400 rows are a
#    partial snapshot continued in file 3 (dropped by build.sh).
next_range="$DOWNLOAD_DIR/${NEXT_NAME%.csv.gz}.head-0-$NEXT_RANGE_END.gz"
if ! sha_ok "$next_range" "$NEXT_RANGE_BYTES" "$NEXT_RANGE_SHA256"; then
  headers="$next_range.headers"
  small_get "$RELEASE_BASE/$NEXT_NAME" "$next_range" --range "0-$NEXT_RANGE_END" \
    --max-filesize "$((NEXT_RANGE_BYTES + 1024))" --dump-header "$headers"
  grep -qiE "^content-range: bytes 0-$NEXT_RANGE_END/$NEXT_BYTES" "$headers" \
    || { echo "FATAL: server did not honor the file-3 head range" >&2; exit 1; }
  sha_ok "$next_range" "$NEXT_RANGE_BYTES" "$NEXT_RANGE_SHA256" \
    || { echo "FATAL: file-3 head range sha256 mismatch" >&2; exit 1; }
fi
got_ts="$(first_ts_of_gzip "$next_range")"
[[ "$got_ts" == "$NEXT_FIRST_TS" ]] || { echo "FATAL: file 3 starts at t=$got_ts, expected $NEXT_FIRST_TS" >&2; exit 1; }
echo "next_file_head_validation=ok $NEXT_NAME first_ts=$got_ts"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
