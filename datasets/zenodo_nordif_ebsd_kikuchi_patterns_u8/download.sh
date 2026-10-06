#!/usr/bin/env bash
# Download the pinned Zenodo 6634354 record metadata, the two NORDIF
# Setting.txt files for maps II and III, and every 8th scan row of
# II_EBSD.dat and III_EBSD.dat as exact HTTP byte ranges.
#
# Each scan row is fetched as its own ranged request: row r of a map with C
# columns spans bytes [r*C*57600, (r+1)*C*57600) of the headerless NORDIF
# pattern stack. curl -C - does not compose with -r, so a failed row is
# discarded and re-requested (up to ROW_ATTEMPTS times) instead of resumed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_nordif_ebsd_kikuchi_patterns_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
RECORD_ID=6634354
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
PINS_FILE="$RECIPE_DIR/row_sha256.tsv"
UA="openzl-public-datasets-nordif-ebsd/1.0"

PATTERN_BYTES=57600   # 240 x 240 uint8 per Kikuchi pattern
ROW_STRIDE=8          # keep scan rows 0, 8, 16, ... of each map
ROW_ATTEMPTS="${ROW_ATTEMPTS:-5}"        # whole-row re-requests per row
RETRY_BACKOFF_S="${RETRY_BACKOFF_S:-10}"  # sleep attempt*backoff between row attempts

# map  rows cols  dat_bytes   dat_md5                           setting_bytes setting_md5                       setting_sha256
MAPS=(
  "II  59 208 706867200  bf5446ab3566b5d47fa9c1205c399e60 1553 a896c97384fff105b92c435bee81472e 4a6a03e53da49e1682a59d4d4b6e92f9d2f2c5a755a562864039128e7a3b4ec3"
  "III 64 323 1190707200 bc44c9a44ffd04185300783fd986cf64 1518 409290e8e3559e17eb91bd2f0c7c6a97 f138321cb1433c9095202da8cb44453da0cde237661dc5bd2f133214219ee4f0"
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID stride=$ROW_STRIDE"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$DOWNLOAD_DIR"/record.json "$DOWNLOAD_DIR"/*_Setting.txt \
    "$DOWNLOAD_DIR"/*_EBSD.row*.bin "$DOWNLOAD_DIR"/*_EBSD.row*.bin.part \
    "$DOWNLOAD_DIR"/*_EBSD.row*.headers "$DOWNLOAD_DIR"/row_sha256.tsv
fi

# ---------------------------------------------------------------- metadata
metadata="$DOWNLOAD_DIR/record.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --connect-timeout 30 --max-time 180 --max-filesize 20000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

map_specs="$(printf '%s\n' "${MAPS[@]}")"
python3 - "$metadata" "$RECORD_ID" "$map_specs" <<'PY'
import json
import re
import sys

path, record_id, specs = sys.argv[1], int(sys.argv[2]), sys.argv[3]
record = json.loads(open(path, encoding="utf-8").read())
if int(record.get("id") or 0) != record_id:
    raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
meta = record.get("metadata") or {}
title = str(meta.get("title") or "")
if "EBSD" not in title or "cold metal transfer" not in title.lower():
    raise SystemExit(f"record title no longer identifies the CMT Al-steel EBSD deposit: {title!r}")
lic = meta.get("license")
lic_id = str((lic.get("id") if isinstance(lic, dict) else lic) or "").lower()
if lic_id != "cc-by-4.0":
    raise SystemExit(f"record license changed: {lic!r}")
access = meta.get("access_right") or (record.get("access") or {}).get("record")
if access not in ("open", "public"):
    raise SystemExit(f"record access changed: {access!r}")
files = {f.get("key"): f for f in record.get("files") or [] if isinstance(f, dict)}
for line in specs.strip().splitlines():
    name, _rows, _cols, dat_bytes, dat_md5, set_bytes, set_md5, _set_sha = line.split()
    for key, size, md5 in (
        (f"{name}_EBSD.dat", int(dat_bytes), dat_md5),
        (f"{name}_Setting.txt", int(set_bytes), set_md5),
    ):
        item = files.get(key)
        if item is None:
            raise SystemExit(f"record no longer lists {key}")
        if int(item.get("size") or -1) != size:
            raise SystemExit(f"{key} size changed: {item.get('size')!r} != {size}")
        if str(item.get("checksum") or "").lower() != f"md5:{md5}":
            raise SystemExit(f"{key} checksum changed: {item.get('checksum')!r}")
print(f"metadata_validation=ok record={record_id} license=cc-by-4.0 access={access} title={title[:80]!r}")
PY

# ---------------------------------------------------------- Setting.txt
for spec in "${MAPS[@]}"; do
  read -r name rows cols dat_bytes _dat_md5 set_bytes set_md5 set_sha <<<"$spec"
  setting="$DOWNLOAD_DIR/${name}_Setting.txt"
  if [ ! -s "$setting" ] || ! printf '%s  %s\n' "$set_sha" "$setting" | sha256sum --check --status; then
    rm -f "$setting" "$setting.part"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 3 --retry-all-errors \
      --connect-timeout 30 --max-time 120 --max-filesize 100000 \
      --user-agent "$UA" --output "$setting.part" \
      "$FILE_BASE/${name}_Setting.txt/content"
    mv "$setting.part" "$setting"
  fi
  actual_size="$(wc -c < "$setting" | tr -d ' ')"
  [ "$actual_size" = "$set_bytes" ] || { echo "FATAL: $setting size $actual_size != $set_bytes" >&2; exit 1; }
  printf '%s  %s\n' "$set_md5" "$setting" | md5sum --check --status \
    || { echo "FATAL: $setting md5 mismatch" >&2; exit 1; }
  printf '%s  %s\n' "$set_sha" "$setting" | sha256sum --check --status \
    || { echo "FATAL: $setting sha256 mismatch" >&2; exit 1; }

  # Semantic check: the acquisition geometry declared by NORDIF must match
  # the pinned grid and the upstream .dat size.
  python3 - "$setting" "$rows" "$cols" "$dat_bytes" "$PATTERN_BYTES" <<'PY'
import sys

path, rows, cols, dat_bytes, pattern_bytes = sys.argv[1], *map(int, sys.argv[2:])
sections: dict[str, dict[str, str]] = {}
current = None
for raw in open(path, encoding="latin-1").read().splitlines():
    parts = raw.rstrip("\r").split("\t")
    head = parts[0].strip()
    if head.startswith("[") and head.endswith("]"):
        current = sections.setdefault(head[1:-1], {})
    elif head and current is not None:
        current[head] = parts[1].strip() if len(parts) > 1 else ""
acq = sections.get("Acquisition settings") or {}
area = sections.get("Area") or {}
if sections.get("EBSD detector", {}).get("Model") != "UF1100":
    raise SystemExit("Setting.txt does not describe a NORDIF UF1100 detector")
if acq.get("Resolution") != "240x240":
    raise SystemExit(f"acquisition resolution {acq.get('Resolution')!r} != 240x240")
if acq.get("Gain") != "10" or acq.get("Frame rate") != "20" or acq.get("Exposure time") != "49950":
    raise SystemExit(f"acquisition gain/frame rate/exposure changed: {acq!r}")
n_rows, n_cols = (int(v) for v in area.get("Number of samples", "0x0").split("x"))
step = float(area["Step size"])
height = float(area["Height"].split()[0])
width = float(area["Width"].split()[0])
if (n_rows, n_cols) != (rows, cols):
    raise SystemExit(f"Number of samples {n_rows}x{n_cols} != pinned {rows}x{cols}")
if round(height / step) != rows or round(width / step) != cols:
    raise SystemExit("Area height/width/step do not imply rows x columns")
if rows * cols * pattern_bytes != dat_bytes:
    raise SystemExit("rows * cols * 57600 does not equal the pinned EBSD.dat size")
print(f"setting_validation=ok file={path.rsplit('/', 1)[-1]} grid={rows}x{cols} "
      f"step_um={step} acquisition=240x240 gain=10 fps=20 exposure_us=49950")
PY
done

# ------------------------------------------------------------ row ranges
validate_row() {
  # args: payload headers_or_empty start end total cols name
  python3 - "$@" "$PINS_FILE" <<'PY'
import hashlib
import os
import re
import sys

payload, headers, start, end, total, cols, name, pins_file = sys.argv[1:9]
start, end, total, cols = int(start), int(end), int(total), int(cols)
pattern_bytes = 57600
if headers:
    text = open(headers, encoding="iso-8859-1").read()
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    final = blocks[-1] if blocks else ""
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    crange = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final,
                       flags=re.IGNORECASE | re.MULTILINE)
    if not status or status.group(1) != "206" or not crange:
        raise SystemExit(f"{name}: server did not answer with 206 + Content-Range")
    if tuple(map(int, crange.groups())) != (start, end, total):
        raise SystemExit(f"{name}: unexpected Content-Range {crange.groups()} != {(start, end, total)}")
size = os.path.getsize(payload)
if size != end - start + 1 or size != cols * pattern_bytes:
    raise SystemExit(f"{name}: payload size {size} != {cols} * {pattern_bytes}")
data = open(payload, "rb").read()
for col in range(cols):
    pattern = data[col * pattern_bytes:(col + 1) * pattern_bytes]
    distinct = len(set(pattern))
    if distinct < 16:
        raise SystemExit(f"{name}: pattern at column {col} has only {distinct} distinct values")
digest = hashlib.sha256(data).hexdigest()
if os.path.isfile(pins_file):
    pins = {}
    for line in open(pins_file, encoding="utf-8"):
        fields = line.split()
        if fields and not fields[0].startswith("#"):
            pins[fields[0]] = fields[-1]
    if name not in pins:
        raise SystemExit(f"{name}: no pinned sha256 in {pins_file}")
    if pins[name] != digest:
        raise SystemExit(f"{name}: sha256 {digest} != pinned {pins[name]}")
print(f"row_validation=ok {name} bytes={size} sha256={digest}")
PY
}

fetch_row() {
  local name="$1" row="$2" cols="$3" total="$4"
  local row_bytes=$((cols * PATTERN_BYTES))
  local start=$((row * row_bytes))
  local end=$((start + row_bytes - 1))
  local file; file="$(printf '%s_EBSD.row%03d.bin' "$name" "$row")"
  local out="$DOWNLOAD_DIR/$file"
  local headers="$DOWNLOAD_DIR/$file.headers"
  if [ -s "$out" ]; then
    if validate_row "$out" "$( [ -s "$headers" ] && echo "$headers" )" "$start" "$end" "$total" "$cols" "$file"; then
      echo "cache_hit $file"
      return 0
    fi
    echo "cached $file failed validation; refetching"
    rm -f "$out" "$headers"
  fi
  local attempt
  for attempt in $(seq 1 "$ROW_ATTEMPTS"); do
    rm -f "$out.part" "$headers.part"
    echo "fetch $file range=$start-$end attempt=$attempt"
    if curl --fail --silent --show-error --location \
         --retry 10 --retry-delay 5 --retry-all-errors \
         --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
         --max-filesize "$((row_bytes + 1024))" \
         --range "$start-$end" --user-agent "$UA" \
         --dump-header "$headers.part" --output "$out.part" \
         "$FILE_BASE/${name}_EBSD.dat/content"; then
      if validate_row "$out.part" "$headers.part" "$start" "$end" "$total" "$cols" "$file"; then
        mv "$headers.part" "$headers"
        mv "$out.part" "$out"
        return 0
      fi
    fi
    echo "row $file attempt $attempt failed" >&2
    sleep $((attempt * RETRY_BACKOFF_S))
  done
  rm -f "$out.part" "$headers.part"
  echo "FATAL: could not fetch a valid $file after $ROW_ATTEMPTS attempts" >&2
  return 1
}

for spec in "${MAPS[@]}"; do
  read -r name rows cols dat_bytes _rest <<<"$spec"
  for ((row = 0; row < rows; row += ROW_STRIDE)); do
    fetch_row "$name" "$row" "$cols" "$dat_bytes"
  done
done

# Record realized row checksums (the recipe pins these in row_sha256.tsv).
(
  cd "$DOWNLOAD_DIR"
  printf '# file\tbytes\tsha256\n'
  for f in II_EBSD.row*.bin III_EBSD.row*.bin; do
    printf '%s\t%s\t%s\n' "$f" "$(wc -c < "$f" | tr -d ' ')" "$(sha256sum "$f" | cut -d' ' -f1)"
  done
) > "$DOWNLOAD_DIR/row_sha256.tsv.part"
mv "$DOWNLOAD_DIR/row_sha256.tsv.part" "$DOWNLOAD_DIR/row_sha256.tsv"
row_files="$(grep -vc '^#' "$DOWNLOAD_DIR/row_sha256.tsv")"
row_total="$(awk -F'\t' '!/^#/ {s += $2} END {print s}' "$DOWNLOAD_DIR/row_sha256.tsv")"
echo "rows=$row_files row_bytes=$row_total"
[ "$row_files" = "16" ] && [ "$row_total" = "244684800" ] \
  || { echo "FATAL: expected 16 rows / 244684800 bytes" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID"
