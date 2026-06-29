#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openfda_device_event"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
ZIP_DIR="$DOWNLOAD_DIR/bulk_zips"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$ZIP_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

INDEX_URL="${OPENFDA_DEVICE_EVENT_DOWNLOAD_INDEX_URL:-https://api.fda.gov/download.json}"
MAX_RECORDS="${OPENFDA_DEVICE_EVENT_MAX_RECORDS:-10000}"
MIN_RECORDS="${OPENFDA_DEVICE_EVENT_MIN_RECORDS:-5000}"
MAX_PARTITIONS="${OPENFDA_DEVICE_EVENT_MAX_PARTITIONS:-8}"
PARTITION_FILTER="${OPENFDA_DEVICE_EVENT_PARTITION_FILTER:-}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
OUT="$DOWNLOAD_DIR/events.json"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"

if [ -s "$OUT" ] && [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_RECORDS"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
records = int(obj.get("record_count", 0))
if records < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit record_count={records} partitions={obj.get('partition_count')}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

case "$MAX_RECORDS" in
  ''|*[!0-9]*) echo "OPENFDA_DEVICE_EVENT_MAX_RECORDS must be an integer" >&2; exit 1 ;;
esac
case "$MIN_RECORDS" in
  ''|*[!0-9]*) echo "OPENFDA_DEVICE_EVENT_MIN_RECORDS must be an integer" >&2; exit 1 ;;
esac
case "$MAX_PARTITIONS" in
  ''|*[!0-9]*) echo "OPENFDA_DEVICE_EVENT_MAX_PARTITIONS must be an integer" >&2; exit 1 ;;
esac
if [ "$MAX_RECORDS" -le 0 ] || [ "$MIN_RECORDS" -le 0 ] || [ "$MAX_PARTITIONS" -le 0 ]; then
  echo "OPENFDA_DEVICE_EVENT_MAX_RECORDS, OPENFDA_DEVICE_EVENT_MIN_RECORDS, and OPENFDA_DEVICE_EVENT_MAX_PARTITIONS must be positive" >&2
  exit 1
fi
if [ "$MIN_RECORDS" -gt "$MAX_RECORDS" ]; then
  echo "OPENFDA_DEVICE_EVENT_MIN_RECORDS cannot exceed OPENFDA_DEVICE_EVENT_MAX_RECORDS" >&2
  exit 1
fi

TMP_ROOT="$DOWNLOAD_DIR/tmp.$$"
TMP_INDEX="$TMP_ROOT/download_index.json"
TMP_SELECTED="$TMP_ROOT/selected_partitions.tsv"
TMP_ZIPS="$TMP_ROOT/bulk_zips"
TMP_OUT="$TMP_ROOT/events.json"
TMP_INVENTORY="$TMP_ROOT/download_inventory.json"
mkdir -p "$TMP_ROOT" "$TMP_ZIPS"
trap 'rm -rf "$TMP_ROOT"' EXIT

if [ -n "${OPENFDA_DEVICE_EVENT_BULK_URLS:-}" ]; then
  echo "using explicit OPENFDA_DEVICE_EVENT_BULK_URLS"
  python3 - <<'PY' "$TMP_SELECTED" $OPENFDA_DEVICE_EVENT_BULK_URLS
from pathlib import Path
import sys

out = Path(sys.argv[1])
urls = sys.argv[2:]
if not urls:
    raise SystemExit("OPENFDA_DEVICE_EVENT_BULK_URLS was set but empty")
with out.open("w", encoding="utf-8") as fh:
    for index, url in enumerate(urls):
        if not url.startswith(("http://", "https://")):
            raise SystemExit(f"bad bulk URL: {url}")
        fh.write(f"{index}\t-1\t-1\tmanual\t{url}\n")
PY
else
  echo "resolve_bulk_index url=$INDEX_URL"
  if ! curl --globoff --fail --location --retry 3 --retry-delay 2 --retry-all-errors --silent --show-error \
      -A "$UA" -o "$TMP_INDEX" "$INDEX_URL"; then
    echo "failed to resolve openFDA bulk download index: $INDEX_URL" >&2
    exit 1
  fi
  python3 - <<'PY' "$TMP_INDEX" "$TMP_SELECTED" "$MIN_RECORDS" "$MAX_PARTITIONS" "$PARTITION_FILTER"
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

index_path = Path(sys.argv[1])
selected_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
max_partitions = int(sys.argv[4])
partition_filter = sys.argv[5]
pattern = re.compile(partition_filter) if partition_filter else None

obj = json.loads(index_path.read_text(encoding="utf-8"))
root = (((obj.get("results") or {}).get("device") or {}).get("event") or {})
if not root:
    raise SystemExit("download index does not contain results.device.event")

partitions: list[dict] = []

def walk(value: object) -> None:
    if isinstance(value, dict):
        file_url = value.get("file")
        if isinstance(file_url, str) and file_url.endswith(".json.zip"):
            display = str(value.get("display_name") or value.get("name") or "")
            if pattern and not (pattern.search(display) or pattern.search(file_url)):
                return
            try:
                records = int(value.get("records") or -1)
            except Exception:
                records = -1
            try:
                size_mb = float(value.get("size_mb") or value.get("sizeMB") or -1)
            except Exception:
                size_mb = -1.0
            partitions.append(
                {
                    "file": file_url,
                    "records": records,
                    "size_mb": size_mb,
                    "display": display.replace("\t", " ").replace("\n", " "),
                }
            )
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)

walk(root)
if not partitions:
    raise SystemExit("no device/event bulk JSON zip partitions found in openFDA download index")

partitions.sort(key=lambda row: (row["records"] <= 0, -row["records"], row["size_mb"] < 0, row["size_mb"]))
selected: list[dict] = []
expected = 0
for row in partitions:
    selected.append(row)
    if row["records"] > 0:
        expected += row["records"]
    if len(selected) >= max_partitions or expected >= min_records:
        break
if expected > 0 and expected < min_records:
    print(
        f"warning selected partitions advertise only {expected} records < minimum {min_records}; "
        "continuing because bulk index record counts may be stale",
        file=sys.stderr,
    )

with selected_path.open("w", encoding="utf-8") as fh:
    for index, row in enumerate(selected):
        fh.write(f"{index}\t{row['records']}\t{row['size_mb']}\t{row['display']}\t{row['file']}\n")
print(f"selected_partitions={len(selected)} advertised_records={expected} available_partitions={len(partitions)}")
PY
fi

while IFS=$'\t' read -r index records size_mb display url; do
  zip_path="$TMP_ZIPS/partition_$(printf '%05d' "$index").json.zip"
  echo "fetch_bulk_partition index=$index records=$records size_mb=$size_mb display=$display"
  curl --globoff --fail --location --retry 3 --retry-delay 2 --retry-all-errors --silent --show-error \
    -A "$UA" -o "$zip_path.tmp" "$url"
  mv "$zip_path.tmp" "$zip_path"
  echo "fetch_bulk_partition_ok index=$index bytes=$(stat -c '%s' "$zip_path")"
done < "$TMP_SELECTED"

python3 - <<'PY' "$TMP_ZIPS" "$TMP_SELECTED" "$TMP_OUT" "$TMP_INVENTORY" "$INDEX_URL" "$MAX_RECORDS" "$MIN_RECORDS"
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Iterator

zip_dir = Path(sys.argv[1])
selected_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])
inventory_path = Path(sys.argv[4])
index_url = sys.argv[5]
max_records = int(sys.argv[6])
min_records = int(sys.argv[7])


def iter_results(text) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    buffer = ""
    pos = 0
    eof = False

    def fill() -> bool:
        nonlocal buffer, eof
        if eof:
            return False
        chunk = text.read(1024 * 1024)
        if not chunk:
            eof = True
            return False
        buffer += chunk
        return True

    while True:
        idx = buffer.find('"results"', pos)
        if idx < 0:
            if not fill():
                raise ValueError("missing results array")
            if pos > 1024 * 1024:
                buffer = buffer[pos:]
                pos = 0
            continue
        cursor = idx + len('"results"')
        while True:
            while cursor >= len(buffer) and fill():
                pass
            while cursor < len(buffer) and buffer[cursor].isspace():
                cursor += 1
            if cursor >= len(buffer):
                if not fill():
                    raise ValueError("truncated after results key")
                continue
            break
        if buffer[cursor] != ":":
            pos = idx + 1
            continue
        cursor += 1
        while True:
            while cursor >= len(buffer) and fill():
                pass
            while cursor < len(buffer) and buffer[cursor].isspace():
                cursor += 1
            if cursor >= len(buffer):
                if not fill():
                    raise ValueError("truncated after results colon")
                continue
            break
        if buffer[cursor] == "[":
            pos = cursor + 1
            break
        pos = idx + 1

    while True:
        while True:
            while pos >= len(buffer) and fill():
                pass
            while pos < len(buffer) and (buffer[pos].isspace() or buffer[pos] == ","):
                pos += 1
            if pos >= len(buffer):
                if not fill():
                    raise ValueError("truncated results array")
                continue
            break
        if buffer[pos] == "]":
            return
        while True:
            try:
                value, end = decoder.raw_decode(buffer, pos)
                break
            except json.JSONDecodeError:
                if not fill():
                    raise
        if isinstance(value, dict):
            yield value
        pos = end
        if pos > 4 * 1024 * 1024:
            buffer = buffer[pos:]
            pos = 0


def iter_zip_rows(path: Path) -> Iterator[dict]:
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if name.endswith(".json")]
        if len(names) != 1:
            raise ValueError(f"expected one JSON member in {path}, found {names}")
        with zf.open(names[0]) as raw:
            import io

            with io.TextIOWrapper(raw, encoding="utf-8") as text:
                yield from iter_results(text)


selected = []
with selected_path.open(encoding="utf-8") as fh:
    for line in fh:
        index, records, size_mb, display, url = line.rstrip("\n").split("\t", 4)
        selected.append(
            {
                "index": int(index),
                "records": int(float(records)),
                "size_mb": float(size_mb),
                "display": display,
                "url": url,
            }
        )

combined = []
seen = set()
partition_counts = {}
for zip_path in sorted(zip_dir.glob("partition_*.json.zip")):
    kept_from_partition = 0
    for row in iter_zip_rows(zip_path):
        key = row.get("mdr_report_key") or row.get("event_key") or json.dumps(row, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        combined.append(row)
        kept_from_partition += 1
        if len(combined) >= max_records:
            break
    partition_counts[zip_path.name] = kept_from_partition
    if len(combined) >= max_records:
        break

record_count = len(combined)
if record_count < min_records:
    raise SystemExit(f"only {record_count} unique events < OPENFDA_DEVICE_EVENT_MIN_RECORDS={min_records}")

payload = {
    "format": "openfda_device_event_combined_v1",
    "source": index_url,
    "source_kind": "openFDA bulk download index",
    "record_count": record_count,
    "results": combined,
}
out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
inventory = {
    "dataset_id": "openfda_device_event",
    "index_url": index_url,
    "max_records": max_records,
    "min_records": min_records,
    "partition_count": len(selected),
    "partitions": selected,
    "partition_counts": partition_counts,
    "record_count": record_count,
    "source_bytes": out_path.stat().st_size,
}
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok unique_records={record_count} partitions={len(selected)}")
PY

rm -rf "$ZIP_DIR"
mv "$TMP_ZIPS" "$ZIP_DIR"
mv "$TMP_OUT" "$OUT"
mv "$TMP_INVENTORY" "$INVENTORY"
trap - EXIT
rm -rf "$TMP_ROOT"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
