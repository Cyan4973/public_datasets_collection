#!/usr/bin/env bash
# Download the 12 pinned LUMO SHMTS .mat members (one per state folder of the
# six exemplary ZIPs) by exact ZIP byte range, never the full 3.8 GB of ZIPs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="luh_lumo_tower_acceleration_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
PACKAGE_URL="https://data.uni-hannover.de/api/3/action/package_show?id=lumo"
PACKAGE_ID="93b52576-6a5a-4ce9-8c27-a0372590f7b0"
BASE_URL="https://data.uni-hannover.de/dataset/$PACKAGE_ID/resource"
UA="openzl-public-datasets-lumo/1.0"
TAIL_BYTES=65536
MAX_ATTEMPTS=40
EXPECTED_MEMBERS=12

mkdir -p "$DOWNLOAD_DIR/zip_tails" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# ---------------------------------------------------------------- metadata
pkg="$DOWNLOAD_DIR/package_show.json"
rm -f "$pkg.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
  --output "$pkg.part" "$PACKAGE_URL"
mv "$pkg.part" "$pkg"

python3 - "$pkg" "$SOURCES" "$PACKAGE_ID" <<'PY'
import json, sys
pkg, sources, package_id = sys.argv[1], sys.argv[2], sys.argv[3]
doc = json.load(open(pkg, encoding="utf-8"))
if not doc.get("success"):
    raise SystemExit("CKAN package_show did not succeed")
r = doc["result"]
if r.get("id") != package_id or r.get("name") != "lumo":
    raise SystemExit(f"unexpected CKAN package {r.get('id')!r} {r.get('name')!r}")
if r.get("license_id") != "CC-BY-3.0" or r.get("isopen") is not True:
    raise SystemExit(f"license changed: {r.get('license_id')!r} isopen={r.get('isopen')!r}")
if r.get("doi") != "10.25835/0027803":
    raise SystemExit(f"DOI changed: {r.get('doi')!r}")
resources = {res["id"]: res for res in r.get("resources", [])}
lines = [l.split("\t") for l in open(sources, encoding="utf-8").read().splitlines() if l and not l.startswith("#")]
header, rows = lines[0], [dict(zip(lines[0], l)) for l in lines[1:]]
seen = set()
for row in rows:
    if row["resource_id"] in seen:
        continue
    seen.add(row["resource_id"])
    res = resources.get(row["resource_id"])
    if res is None:
        raise SystemExit(f"resource {row['resource_id']} missing from CKAN package")
    if not res.get("url", "").endswith("/" + row["zip_name"]) or int(res.get("size") or 0) != int(row["zip_size"]):
        raise SystemExit(f"resource {row['zip_name']} url/size changed: {res.get('url')!r} {res.get('size')!r}")
print(f"metadata_validation=ok license=CC-BY-3.0 isopen=true doi=10.25835/0027803 zips={len(seen)} members={len(rows)}")
PY

# validate_headers <header_file> <from> <to> <zip_size>: final response must be
# 206 with exactly the requested Content-Range (proxy CONNECT blocks skipped).
validate_headers() {
  python3 - "$@" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="iso-8859-1").read()
start, end, total = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.M) if b.strip()]
final = blocks[-1] if blocks else ""
status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.M)
crange = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)", final, flags=re.M | re.I)
if not status or status.group(1) != "206" or not crange:
    raise SystemExit(f"range request not honored (status={status.group(1) if status else None})")
if tuple(map(int, crange.groups())) != (start, end, total):
    raise SystemExit(f"unexpected Content-Range {crange.groups()} for {start}-{end}/{total}")
PY
}

# fetch_range <url> <start> <end> <zip_size> <out>: resumable exact byte range.
fetch_range() {
  local url="$1" start="$2" end="$3" zsize="$4" out="$5"
  local total=$((end - start + 1)) attempt=0 have from got
  while :; do
    have=0
    [ -f "$out.part" ] && have="$(stat -c %s "$out.part")"
    if [ "$have" -eq "$total" ]; then break; fi
    if [ "$have" -gt "$total" ]; then echo "oversized partial $out.part; restarting"; rm -f "$out.part"; continue; fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: range $start-$end of $url incomplete after $MAX_ATTEMPTS attempts" >&2
      exit 1
    fi
    from=$((start + have))
    rm -f "$out.chunk" "$out.hdr"
    if ! curl --fail --silent --show-error --location --connect-timeout 60 \
        --speed-limit 1024 --speed-time 120 --max-filesize $((end - from + 1 + 4096)) \
        --range "$from-$end" --user-agent "$UA" \
        --dump-header "$out.hdr" --output "$out.chunk" "$url"; then
      echo "curl interrupted at offset $from (attempt $attempt); resuming"
    fi
    if [ -s "$out.chunk" ]; then
      validate_headers "$out.hdr" "$from" "$end" "$zsize"
      got="$(stat -c %s "$out.chunk")"
      if [ $((have + got)) -gt "$total" ]; then
        echo "FATAL: server sent more bytes than requested for $out" >&2
        exit 1
      fi
      cat "$out.chunk" >> "$out.part"
    else
      sleep 5
    fi
    rm -f "$out.chunk"
  done
  rm -f "$out.hdr"
  mv "$out.part" "$out"
}

# ------------------------------------------------- live central directories
# Re-read each ZIP's central directory and confirm every pinned member's CRC32,
# sizes and byte range are unchanged before transferring member bytes.
grep -v '^#' "$SOURCES" | tail -n +2 | cut -f1-4 | sort -u | while IFS=$'\t' read -r tag rid zname zsize; do
  tail_file="$DOWNLOAD_DIR/zip_tails/$tag.tail"
  rm -f "$tail_file.part" "$tail_file.hdr"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 300 --range "$((zsize - TAIL_BYTES))-$((zsize - 1))" --user-agent "$UA" \
    --dump-header "$tail_file.hdr" --output "$tail_file.part" "$BASE_URL/$rid/download/$zname"
  validate_headers "$tail_file.hdr" "$((zsize - TAIL_BYTES))" "$((zsize - 1))" "$zsize"
  mv "$tail_file.part" "$tail_file"
  rm -f "$tail_file.hdr"
  python3 - "$RECIPE_DIR" "$tail_file" "$zsize" "$tag" "$SOURCES" <<'PY'
import json, subprocess, sys
recipe, tail, zsize, tag, sources = sys.argv[1:6]
entries = json.loads(subprocess.check_output([sys.executable, f"{recipe}/probe.py", "zipdir", tail, zsize]))
by_name = {e["name"]: e for e in entries}
mats = [e for e in entries if e["name"].endswith(".mat")]
if len(entries) != 12 or len(mats) != 10:
    raise SystemExit(f"{tag}: unexpected ZIP layout ({len(entries)} entries, {len(mats)} .mat)")
lines = [l.split("\t") for l in open(sources, encoding="utf-8").read().splitlines() if l and not l.startswith("#")]
rows = [dict(zip(lines[0], l)) for l in lines[1:] if l[0] == tag]
for row in rows:
    e = by_name.get(row["member"])
    if e is None:
        raise SystemExit(f"{tag}: member {row['member']} missing from central directory")
    got = (e["crc32"], e["csize"], e["usize"], e["lho"], e["range_end"], e["method"])
    want = (row["crc32"], int(row["csize"]), int(row["usize"]), int(row["range_start"]), int(row["range_end"]), 8)
    if got != want:
        raise SystemExit(f"{tag}: {row['member']} central-directory entry changed: {got} != {want}")
print(f"central_directory_validation=ok zip={tag} pinned_members={len(rows)}")
PY
done

# ------------------------------------------------------------ member ranges
extract_member() {
  python3 - "$@" <<'PY'
import struct, sys, zlib
range_path, out_path, member, crc_hex, csize, usize = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
payload = open(range_path, "rb").read()
f = struct.unpack_from("<4s5H3I2H", payload, 0)
if f[0] != b"PK\x03\x04":
    raise SystemExit("range does not start with a ZIP local file header")
flags, method, nlen, xlen = f[2], f[3], f[9], f[10]
name = payload[30:30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
if name != member or method != 8 or not flags & 0x8:
    raise SystemExit(f"local header mismatch: name={name!r} method={method} flags={flags:#x}")
data_offset = 30 + nlen + xlen
dec = zlib.decompressobj(-zlib.MAX_WBITS)
crc = 0
written = 0
fed = 0
view = memoryview(payload)[data_offset:]
with open(out_path, "wb") as out:
    for i in range(0, len(view), 1 << 20):
        chunk = view[i:i + (1 << 20)]
        block = dec.decompress(chunk)
        fed += len(chunk)
        out.write(block)
        crc = zlib.crc32(block, crc)
        written += len(block)
        if dec.eof:
            break
    block = dec.flush()
    out.write(block)
    crc = zlib.crc32(block, crc)
    written += len(block)
if not dec.eof:
    raise SystemExit("DEFLATE stream truncated")
consumed = fed - len(dec.unused_data)
trailer = bytes(view[consumed:])
want_crc = int(crc_hex, 16)
if consumed != csize or written != usize or crc & 0xFFFFFFFF != want_crc:
    raise SystemExit(f"member mismatch: consumed={consumed} written={written} crc={crc & 0xFFFFFFFF:08x}")
desc = struct.pack("<III", want_crc, csize, usize)
if trailer not in (b"PK\x07\x08" + desc, desc):
    raise SystemExit(f"unexpected data descriptor / trailing bytes ({len(trailer)} bytes)")
print(f"zip_member_validation=ok member={member} bytes={written} crc32={crc & 0xFFFFFFFF:08x}")
PY
}

mat_ok() {
  python3 - "$1" "$2" "$3" <<'PY'
import os, sys, zlib
path, crc_hex, usize = sys.argv[1], sys.argv[2], int(sys.argv[3])
if not os.path.isfile(path) or os.path.getsize(path) != usize:
    raise SystemExit(1)
crc = 0
with open(path, "rb") as fh:
    while block := fh.read(1 << 22):
        crc = zlib.crc32(block, crc)
raise SystemExit(0 if f"{crc & 0xFFFFFFFF:08x}" == crc_hex else 1)
PY
}

n_done=0
while IFS=$'\t' read -r tag rid zname zsize member state crc csize usize rstart rend; do
  out="$DOWNLOAD_DIR/$tag/$member"
  mkdir -p "$(dirname "$out")"
  if mat_ok "$out" "$crc" "$usize"; then
    echo "cache_hit member=$member"
  else
    rm -f "$out" "$out.part"
    range_file="$out.zip-range"
    if [ -s "$range_file" ] && [ "$(stat -c %s "$range_file")" -ne $((rend - rstart + 1)) ]; then
      rm -f "$range_file"
    fi
    if [ ! -s "$range_file" ]; then
      echo "[$(date -Is)] fetching member=$member state=$state bytes=$((rend - rstart + 1))"
      fetch_range "$BASE_URL/$rid/download/$zname" "$rstart" "$rend" "$zsize" "$range_file"
    fi
    extract_member "$range_file" "$out.part" "$member" "$crc" "$csize" "$usize"
    python3 "$RECIPE_DIR/scripts/lumo_mat.py" check --mat "$out.part"
    mv "$out.part" "$out"
    if [ "${KEEP_ZIP_RANGES:-0}" != "1" ]; then rm -f "$range_file"; fi
  fi
  n_done=$((n_done + 1))
done < <(grep -v '^#' "$SOURCES" | tail -n +2)

if [ "$n_done" -ne "$EXPECTED_MEMBERS" ]; then
  echo "FATAL: expected $EXPECTED_MEMBERS pinned members, processed $n_done" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID members=$n_done"
