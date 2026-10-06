#!/usr/bin/env bash
# Fetch exactly one ZIP member per in-scope Valve Index sequence,
# <seq>/mav0/imu0/data.csv, by HTTP byte range from the pinned Hugging Face
# revision. sources.tsv pins the part file, its size and LFS SHA-256, the
# local-header offset and length, the member size and the central-directory
# CRC-32 for the 30 sequences whose published data.csv carries the Basalt IMU
# correction exactly once.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="monado_msd_valve_index_imu_f64"
REVISION="74c07d42d980c55775dd0edc06e58c486b848be1"
REPO_URL="https://huggingface.co/datasets/collabora/monado-slam-datasets"
API_URL="https://huggingface.co/api/datasets/collabora/monado-slam-datasets"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
ZIPTOOL="$RECIPE_DIR/scripts/msd_zip.py"
UA="openzl-public-datasets-monado-msd-imu/1.0"
EXPECTED_SEQUENCES=30
# The other 19 Valve Index sequences are out of scope: their published
# imu0/data.csv has the Basalt accel/gyro correction applied more than once
# (accel-x count lattice step 0.0022610797 = 0.971802^2 x base for MIC02-MIC16
# and MIO01-MIO03, 0.0021973218 = 0.971802^3 x base for MIC01, versus
# 0.0023266877 for the kept 30; gyro rest offsets of about -1x / -2x the
# published calib_gyro_bias). They are pinned here so upstream drift is still
# detected: tree sequences must equal sources plus EXCLUDED.
EXCLUDED="MIC01_camcalib1 MIC02_camcalib2 MIC03_camcalib3 MIC04_imucalib1 MIC05_imucalib2 MIC06_imucalib3 MIC07_camcalib4 MIC08_camcalib5 MIC09_imucalib4 MIC10_imucalib5 MIC11_camcalib6 MIC12_imucalib6 MIC13_camcalib7 MIC14_camcalib8 MIC15_imucalib7 MIC16_imucalib8 MIO01_hand_puncher_1 MIO02_hand_puncher_2 MIO03_hand_shooter_easy"
EXPECTED_HEADER='#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]'
MAX_ATTEMPTS=12

mkdir -p "$DOWNLOAD_DIR/meta" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

small_get() {  # small_get <url> <out>: bounded metadata request
  curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --max-time 300 --max-filesize 20000000 --user-agent "$UA" \
    --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. Repository identity, access and license at the pinned revision.
small_get "$API_URL/revision/$REVISION" "$DOWNLOAD_DIR/meta/revision.json"
small_get "$API_URL/tree/$REVISION/M_monado_datasets/MI_valve_index?recursive=true" "$DOWNLOAD_DIR/meta/tree_MI_valve_index.json"
small_get "$REPO_URL/resolve/$REVISION/README.md" "$DOWNLOAD_DIR/meta/README.md"
python3 - "$DOWNLOAD_DIR/meta" "$SOURCES" "$REVISION" "$EXPECTED_SEQUENCES" "$EXCLUDED" <<'PY'
import csv, json, sys
from pathlib import Path, PurePosixPath
meta, sources, revision, expected = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
excluded = set(sys.argv[5].split())
if len(excluded) != 19:
    raise SystemExit(f"EXCLUDED must pin 19 sequences, got {len(excluded)}")
info = json.loads((meta / "revision.json").read_text())
if info.get("sha") != revision or info.get("id") != "collabora/monado-slam-datasets":
    raise SystemExit(f"unexpected repository identity: {info.get('id')} {info.get('sha')}")
if info.get("gated") not in (False, None) or info.get("private") or info.get("disabled"):
    raise SystemExit("repository is gated, private or disabled; public anonymous access required")
if str((info.get("cardData") or {}).get("license", "")).lower() != "cc-by-4.0":
    raise SystemExit(f"card license changed: {info.get('cardData')}")
readme = (meta / "README.md").read_text(encoding="utf-8")
if not readme.startswith("---\nlicense: cc-by-4.0\n") or "Creative Commons Attribution 4.0 International License" not in readme:
    raise SystemExit("README license statement changed")
tree = {e["path"]: e for e in json.loads((meta / "tree_MI_valve_index.json").read_text()) if e.get("type") == "file"}
rows = list(csv.DictReader(open(sources, encoding="utf-8"), delimiter="\t"))
if len(rows) != expected or len({r["sequence"] for r in rows}) != expected:
    raise SystemExit(f"sources.tsv must list {expected} distinct sequences")
zips = {PurePosixPath(p).stem for p in tree if p.endswith(".zip") and "/extras/" not in p}
kept = {r["sequence"] for r in rows}
if kept & excluded:
    raise SystemExit(f"sources.tsv lists excluded sequences: {sorted(kept & excluded)}")
if zips != kept | excluded:
    raise SystemExit(f"sequence set drifted: {sorted(zips ^ (kept | excluded))}")
for r in rows:
    e = tree.get(r["part_path"])
    if e is None:
        raise SystemExit(f"{r['part_path']} missing from tree")
    if int(e["size"]) != int(r["part_size_bytes"]) or (e.get("lfs") or {}).get("oid") != r["part_lfs_sha256"]:
        raise SystemExit(f"{r['part_path']} size or LFS SHA-256 drifted")
    if r["member"] != f"{r['sequence']}/mav0/imu0/data.csv":
        raise SystemExit(f"unexpected member {r['member']}")
print(f"metadata_validation=ok revision={revision} license=cc-by-4.0 gated=false sequences={len(rows)} excluded={len(excluded)}")
PY

# 2. Exact member ranges. curl's -C - must not be combined with --range (curl
# then ignores the range and streams to the end of the multi-GB object), so a
# stalled transfer is resumed by requesting only the missing tail of the range
# and appending it to the .part file.
fetch_range() {  # fetch_range <url> <start> <end> <object_size> <out.part>
  local url="$1" start="$2" end="$3" total="$4" out="$5"
  local want=$((end - start + 1)) have from attempt=0 rc got
  while :; do
    have=0
    [ -f "$out" ] && have="$(stat -c %s "$out")"
    if [ "$have" -eq "$want" ]; then return 0; fi
    if [ "$have" -gt "$want" ]; then
      echo "oversized partial $out ($have > $want); restarting"
      rm -f "$out"
      have=0
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: range $start-$end not complete after $MAX_ATTEMPTS attempts" >&2
      return 1
    fi
    from=$((start + have))
    rm -f "$out.chunk" "$out.headers"
    rc=0
    # --max-filesize also applies to the ~1.2 KB HF 302 redirect body, hence
    # the 1 MiB margin; it still aborts a range-ignoring full-object 200.
    curl --fail --silent --show-error --location --connect-timeout 30 \
      --speed-limit 1024 --speed-time 120 --max-filesize "$((end - from + 1 + 1048576))" \
      --user-agent "$UA" --range "$from-$end" \
      --dump-header "$out.headers" --output "$out.chunk" "$url" || rc=$?
    got=0
    [ -f "$out.chunk" ] && got="$(stat -c %s "$out.chunk")"
    if [ "$got" -gt 0 ]; then
      if ! python3 "$ZIPTOOL" check206 "$out.headers" "$from" "$end" "$total"; then
        rm -f "$out.chunk"
        return 1
      fi
      if [ "$got" -gt "$((end - from + 1))" ]; then
        echo "FATAL: server sent $got bytes for a $((end - from + 1))-byte range" >&2
        rm -f "$out.chunk"
        return 1
      fi
      cat "$out.chunk" >> "$out" || return 1
    fi
    rm -f "$out.chunk" "$out.headers"
    if [ "$rc" -ne 0 ]; then
      echo "curl rc=$rc after $got bytes (attempt $attempt); retrying from $((from + got))"
      sleep $((attempt * 5))
    fi
  done
}

check_csv() {  # check_csv <member.csv> <size> <crc32>: cheap re-check of a cached member
  python3 - "$1" "$2" "$3" "$EXPECTED_HEADER" <<'PY'
import sys, zlib
from pathlib import Path
path, size, crc, header = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3], 16), sys.argv[4]
if not path.is_file() or path.stat().st_size != size:
    raise SystemExit(1)
value = 0
with path.open("rb") as handle:
    first = handle.readline()
    value = zlib.crc32(first, value)
    while block := handle.read(8 << 20):
        value = zlib.crc32(block, value)
if value & 0xFFFFFFFF != crc:
    raise SystemExit(f"CRC-32 mismatch for {path}")
if first.rstrip(b"\r\n").decode("ascii") != header:
    raise SystemExit(f"unexpected IMU CSV header in {path}: {first[:200]!r}")
PY
}

# Members of excluded sequences cached by an earlier revision of this recipe
# (which fetched all 49) are this recipe's own generated downloads; drop them so
# the download directory holds exactly the declared resources.
for seq in $EXCLUDED; do
  if [ -f "$DOWNLOAD_DIR/$seq.imu0_data.csv" ] || [ -f "$DOWNLOAD_DIR/$seq.zipentry.part" ]; then
    echo "removing out-of-scope cached member seq=$seq"
    rm -f "$DOWNLOAD_DIR/$seq.imu0_data.csv" "$DOWNLOAD_DIR/$seq.zipentry.part"
  fi
done

done_count=0
fetched_bytes=0
while IFS=$'\t' read -r -u 3 seq group part_path part_size part_sha disk total_disks member lho lhb csz usz crc method; do
  [ "$seq" = "sequence" ] && continue
  out_csv="$DOWNLOAD_DIR/$seq.imu0_data.csv"
  if [ -s "$out_csv" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if check_csv "$out_csv" "$usz" "$crc"; then
      done_count=$((done_count + 1))
      echo "cache_hit seq=$seq bytes=$usz crc32=$crc"
      continue
    fi
    echo "cached member for $seq failed validation; refetching"
    rm -f "$out_csv"
  fi
  start="$lho"
  end=$((lho + lhb + csz - 1))
  range_part="$DOWNLOAD_DIR/$seq.zipentry.part"
  [ "${FORCE_DOWNLOAD:-0}" = "1" ] && rm -f "$range_part"
  echo "fetch seq=$seq part=${part_path##*/} disk=$disk range=$start-$end bytes=$((end - start + 1))"
  if ! fetch_range "$REPO_URL/resolve/$REVISION/$part_path" "$start" "$end" "$part_size" "$range_part"; then
    echo "FATAL: could not fetch the exact member range for $seq" >&2
    exit 1
  fi
  expect="{\"member\": \"$member\", \"local_header_bytes\": $lhb, \"compressed_size\": $csz, \"uncompressed_size\": $usz, \"crc32\": \"$crc\", \"method\": $method}"
  if ! python3 "$ZIPTOOL" member "$range_part" "$out_csv" "$expect"; then
    echo "FATAL: $seq member failed validation; discarding the fetched range" >&2
    rm -f "$range_part" "$out_csv"
    exit 1
  fi
  rm -f "$range_part"
  check_csv "$out_csv" "$usz" "$crc"
  done_count=$((done_count + 1))
  fetched_bytes=$((fetched_bytes + end - start + 1))
done 3< "$SOURCES"

if [ "$done_count" -ne "$EXPECTED_SEQUENCES" ]; then
  echo "FATAL: validated $done_count members, expected $EXPECTED_SEQUENCES" >&2
  exit 1
fi
echo "members_validated=$done_count fetched_this_run=$fetched_bytes"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
