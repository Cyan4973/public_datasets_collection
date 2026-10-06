#!/usr/bin/env bash
# Download the 51 pinned ASTER L1T TIR COGs (asset `TIR` of the Planetary
# Computer aster-l1t collection) listed in $RECIPE_DIR/sources.tsv.
#
# The plan (item id, TIR href, Content-Length, Azure Content-MD5 per scene) was
# resolved on 2026-10-05 by discover.sh (metadata-only STAC search + HEAD, kept
# for documentation and re-checking) and pinned in sources.tsv.
#
# Rights evidence is captured first (blocking): the USGS data policy page (the
# grant), the Planetary Computer collection JSON (license link, licensors, TIR
# band typing) and, optionally, the NASA Earthdata ASTER no-charge notice are
# saved under downloads/<id>/rights/, phrase-checked by scripts/rights_check.py,
# and recorded with sha256 in downloads/<id>/rights_receipts.tsv.
#
# Access: the astersa/aster container needs a short-lived read-only SAS that
# the Planetary Computer issues anonymously (no account, key or login) at
# /api/sas/v1/token/astersa/aster. It is held in a shell variable, refreshed
# every 20 minutes, and never logged. Network I/O is curl only; Python only
# validates the plan and the downloaded TIFFs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_aster_l1t_tir_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/tir"
mkdir -p "$LOG_DIR" "$RASTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets/1.0 ($DATASET_ID)"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/astersa/aster"
PINNED="$RECIPE_DIR/sources.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
VALIDATOR="$RECIPE_DIR/scripts/aster_tir_cog.py"
HELPER="$RECIPE_DIR/scripts/stac_select.py"
MIN_SCENES=40
MAX_PLAN_BYTES=700000000
# Exact pinned scope (sources.tsv, resolved 2026-10-05).
EXPECTED_SCENES="51"
EXPECTED_BYTES="157104582"
export PYTHONDONTWRITEBYTECODE=1

# The TIFF parser is self-tested on synthetic 5-band predictor-2 tiles first.
python3 "$VALIDATOR" selftest

if [ ! -f "$PINNED" ]; then
  echo "FATAL: missing pinned plan $PINNED (discover.sh documents how it was resolved)" >&2
  exit 1
fi
mode="pinned"
cp "$PINNED" "$PLAN.tmp"

python3 - "$PLAN.tmp" "$MIN_SCENES" "$MAX_PLAN_BYTES" "$EXPECTED_SCENES" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
path, min_scenes, max_bytes, want_n, want_bytes = sys.argv[1:6]
header = ["region_id", "region_label", "window", "year", "item_id", "datetime", "cloud_cover", "sun_elevation",
          "sun_azimuth", "candidates", "url", "size_bytes", "content_md5_b64"]
with open(path, encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter="\t")
    got = next(reader)
    if got != header:
        raise SystemExit(f"FATAL: plan header {got} != {header}")
    rows = [dict(zip(header, r)) for r in reader if r]
href = re.compile(r"^https://astersa\.blob\.core\.windows\.net/aster/images/L1T/(\d{4})/(\d{2})/(\d{2})/(AST_L1T_[0-9A-Za-z_]+)\.TIR\.tif$")
windows = {"feb_apr": ("02-15", "04-30"), "jul_sep": ("07-01", "09-15")}
for r in rows:
    if any(v == "" for v in r.values()):
        raise SystemExit(f"FATAL: empty plan field in {r['item_id']}")
    m = href.match(r["url"])
    if not m:
        raise SystemExit(f"FATAL: unexpected URL {r['url']}")
    if not (2000 <= int(r["year"]) <= 2006) or not r["datetime"].startswith(r["year"] + "-"):
        raise SystemExit(f"FATAL: {r['item_id']} datetime {r['datetime']} outside year {r['year']}")
    lo, hi = windows[r["window"]]
    if not (lo <= r["datetime"][5:10] <= hi):
        raise SystemExit(f"FATAL: {r['item_id']} datetime {r['datetime']} outside window {r['window']}")
    if not (0.0 <= float(r["cloud_cover"]) < 10.0) or float(r["sun_elevation"]) <= 20.0:
        raise SystemExit(f"FATAL: {r['item_id']} violates cloud/daytime rule")
    if not (200000 <= int(r["size_bytes"]) <= 60000000):
        raise SystemExit(f"FATAL: {r['item_id']} implausible size {r['size_bytes']}")
    if r["content_md5_b64"] != "NA" and not re.fullmatch(r"[A-Za-z0-9+/]{22}==", r["content_md5_b64"]):
        raise SystemExit(f"FATAL: {r['item_id']} malformed Content-MD5 {r['content_md5_b64']}")
if len({r["item_id"] for r in rows}) != len(rows) or len({r["url"] for r in rows}) != len(rows):
    raise SystemExit("FATAL: duplicate item or URL in plan")
if len({(r["region_id"], r["window"]) for r in rows}) != len(rows):
    raise SystemExit("FATAL: more than one scene for a region/window")
total = sum(int(r["size_bytes"]) for r in rows)
if len(rows) < int(min_scenes):
    raise SystemExit(f"FATAL: plan has {len(rows)} scenes, minimum {min_scenes}")
if total > int(max_bytes):
    raise SystemExit(f"FATAL: plan bytes {total} exceed {max_bytes}")
if want_n and (len(rows) != int(want_n) or total != int(want_bytes)):
    raise SystemExit(f"FATAL: pinned plan {len(rows)} scenes/{total} bytes != expected {want_n}/{want_bytes}")
print(f"plan_ok scenes={len(rows)} regions={len({r['region_id'] for r in rows})} bytes={total} "
      f"with_md5={sum(r['content_md5_b64'] != 'NA' for r in rows)}")
PY
mv "$PLAN.tmp" "$PLAN"
echo "plan_mode=$mode plan=$PLAN"

# ---- rights evidence (blocking; runs before any raster transfer) -----------
# The grant is the USGS data policy page that the Planetary Computer collection
# links as its "Public Domain" license. It is captured, phrase-checked offline
# (scripts/rights_check.py), and its sha256 is recorded in rights_receipts.tsv;
# verify.sh re-runs the same checks on the saved files without network.
RIGHTS_DIR="$DOWNLOAD_DIR/rights"
RIGHTS_CHECK="$RECIPE_DIR/scripts/rights_check.py"
RIGHTS_RECEIPTS="$DOWNLOAD_DIR/rights_receipts.tsv"
USGS_POLICY_URLS=(
  "https://www.usgs.gov/core-science-systems/hdds/data-policy"
  "https://www.usgs.gov/emergency-operations-portal/data-policy"
)
MPC_COLLECTION_URL="https://planetarycomputer.microsoft.com/api/stac/v1/collections/aster-l1t"
EARTHDATA_URL="https://www.earthdata.nasa.gov/news/aster-data-available-no-charge"
mkdir -p "$RIGHTS_DIR"

# fetch_page <url> <out>: curl into <out>.part and record requested URL,
# effective URL and HTTP code in <out>.part.meta.
fetch_page() {
  local url="$1" out="$2" meta=""
  rm -f "$out.part" "$out.part.meta"
  if meta="$(curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 120 \
      --max-filesize 20000000 -A "$UA" -o "$out.part" -w '%{http_code} %{url_effective}' "$url")"; then
    printf '%s\t%s\t%s\n' "$url" "${meta#* }" "${meta%% *}" > "$out.part.meta"
    echo "rights_fetch url=$url effective=${meta#* } http=${meta%% *} bytes=$(stat -c %s "$out.part")"
    return 0
  fi
  echo "WARN: rights fetch failed url=$url (${meta:-no response})" >&2
  rm -f "$out.part" "$out.part.meta"
  return 1
}

# accept_page <out> <kind>: offline check of <out>.part, then move into place.
accept_page() {
  local out="$1" kind="$2"
  if python3 "$RIGHTS_CHECK" "$kind" "$out.part"; then
    mv "$out.part.meta" "$out.meta"
    mv "$out.part" "$out"
    return 0
  fi
  echo "WARN: $kind check failed for $(cut -f1 "$out.part.meta")" >&2
  rm -f "$out.part" "$out.part.meta"
  return 1
}

# capture_required <file> <kind> <url>...: reuse a saved copy that still
# passes the check, else fetch the URLs in order until one passes.
capture_required() {
  local name="$1" kind="$2" out url
  shift 2
  out="$RIGHTS_DIR/$name"
  if [ -s "$out" ] && [ -s "$out.meta" ] && python3 "$RIGHTS_CHECK" "$kind" "$out"; then
    echo "rights_reuse file=$name"
    return 0
  fi
  rm -f "$out" "$out.meta"
  for url in "$@"; do
    if fetch_page "$url" "$out" && accept_page "$out" "$kind"; then
      return 0
    fi
  done
  echo "FATAL: could not capture a $kind rights document that passes its check ($name)" >&2
  exit 1
}

capture_required "usgs_data_policy.html" usgs "${USGS_POLICY_URLS[@]}"
capture_required "mpc_collection_aster-l1t.json" mpc "$MPC_COLLECTION_URL"

# Optional supporting evidence (never fatal).
EARTHDATA_PAGE="$RIGHTS_DIR/earthdata_aster_no_charge.html"
if ! { [ -s "$EARTHDATA_PAGE" ] && [ -s "$EARTHDATA_PAGE.meta" ]; }; then
  if fetch_page "$EARTHDATA_URL" "$EARTHDATA_PAGE"; then
    mv "$EARTHDATA_PAGE.part.meta" "$EARTHDATA_PAGE.meta"
    mv "$EARTHDATA_PAGE.part" "$EARTHDATA_PAGE"
  else
    echo "note: optional Earthdata ASTER no-charge page not captured"
  fi
fi

printf 'file\trequested_url\teffective_url\thttp_code\tsize_bytes\tsha256\tcheck\n' > "$RIGHTS_RECEIPTS.tmp"
for entry in "usgs_data_policy.html:usgs" "mpc_collection_aster-l1t.json:mpc" "earthdata_aster_no_charge.html:earthdata"; do
  name="${entry%%:*}"
  kind="${entry##*:}"
  out="$RIGHTS_DIR/$name"
  [ -s "$out" ] || continue
  IFS=$'\t' read -r requested effective code < "$out.meta"
  if [ "$kind" = "earthdata" ]; then
    check="$(python3 "$RIGHTS_CHECK" earthdata "$out" | tee /dev/stderr | sed -n 's/^earthdata_check=\([a-z_]*\).*/\1/p')"
    check="supporting_${check:-unknown}"
  elif python3 "$RIGHTS_CHECK" "$kind" "$out" > /dev/null; then
    check="ok"
  else
    echo "FATAL: saved $name no longer passes its check" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$requested" "$effective" "$code" "$(stat -c %s "$out")" \
    "$(sha256sum "$out" | cut -d ' ' -f1)" "$check" >> "$RIGHTS_RECEIPTS.tmp"
done
mv "$RIGHTS_RECEIPTS.tmp" "$RIGHTS_RECEIPTS"
echo "rights_receipts:"
cat "$RIGHTS_RECEIPTS"

sas_query=""
sas_time=0
refresh_sas() {
  local now
  now="$(date +%s)"
  if [ -z "$sas_query" ] || [ $((now - sas_time)) -gt 1200 ]; then
    curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
      -A "$UA" -o "$DOWNLOAD_DIR/.sas.json" "$SAS_ENDPOINT"
    sas_query="$(python3 "$HELPER" sas "$DOWNLOAD_DIR/.sas.json")"
    rm -f "$DOWNLOAD_DIR/.sas.json"
    sas_time="$now"
    echo "sas_ok account=astersa container=aster"
  fi
}

md5_b64() {
  python3 - "$1" <<'PY'
import base64, hashlib, sys
h = hashlib.md5()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
print(base64.b64encode(h.digest()).decode())
PY
}

# file_ok PATH SIZE MD5_B64|NA: exact size, Azure Content-MD5 when published,
# classic little-endian TIFF magic, and the TIR structure (5 x uint16 chunky,
# Deflate, ImageData10..14) with every primary tile inflating to full size.
file_ok() {
  local path="$1" size="$2" md5="$3"
  [ -f "$path" ] || return 1
  [ "$(stat -c %s "$path")" = "$size" ] || { echo "size mismatch $path" >&2; return 1; }
  [ "$(od -An -tx1 -N4 "$path" | tr -d ' \n')" = "49492a00" ] || { echo "not a little-endian TIFF $path" >&2; return 1; }
  if [ "$md5" != "NA" ] && [ "$(md5_b64 "$path")" != "$md5" ]; then
    echo "md5 mismatch $path" >&2
    return 1
  fi
  python3 "$VALIDATOR" validate "$path" > "$path.validation.json.tmp" || { rm -f "$path.validation.json.tmp"; return 1; }
  mv "$path.validation.json.tmp" "$path.validation.json"
}

fetched=0
cached=0
while IFS=$'\t' read -r region label window year item_id when cloud sun azimuth candidates url size md5; do
  [ "$region" != "region_id" ] || continue
  out="$RASTER_DIR/${url##*/}"
  if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && file_ok "$out" "$size" "$md5"; then
    cached=$((cached + 1))
    echo "cache_hit item=$item_id bytes=$size"
    continue
  fi
  rm -f "$out" "$out.validation.json"
  part="$out.part"
  for attempt in 1 2 3; do
    part_size=0
    [ -f "$part" ] && part_size="$(stat -c %s "$part")"
    if [ "$part_size" -gt "$size" ]; then
      rm -f "$part"
      part_size=0
    fi
    if [ "$part_size" -lt "$size" ]; then
      refresh_sas
      echo "fetch item=$item_id region=$region window=$window bytes=$size resume_from=$part_size attempt=$attempt"
      curl --globoff -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
        -sS -o "$part" "${url}?${sas_query}" \
        || echo "WARN: curl exited non-zero item=$item_id attempt=$attempt (partial kept for resume)" >&2
      part_size=0
      [ -f "$part" ] && part_size="$(stat -c %s "$part")"
      if [ "$part_size" -lt "$size" ]; then
        sas_query=""  # force a fresh SAS for the retry
      fi
    fi
    if [ "$part_size" -eq "$size" ]; then
      if file_ok "$part" "$size" "$md5"; then
        mv "$part.validation.json" "$out.validation.json"
        mv "$part" "$out"
        break
      fi
      echo "WARN: complete file failed validation item=$item_id attempt=$attempt; discarding" >&2
      rm -f "$part" "$part.validation.json"
    fi
    sleep 5
  done
  if ! [ -f "$out" ] || ! [ -f "$out.validation.json" ]; then
    echo "FATAL: could not obtain a valid copy of item=$item_id (rerun resumes any partial)" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "validated item=$item_id bytes=$size md5=$md5 structure=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("%sx%s predictor=%s tile=%s sparse=%s nodata=%s" % (d["width"], d["height"], d["predictor"], d["tile_width"], d["sparse_tiles"], d["gdal_nodata"]))' "$out.validation.json")"
done < "$PLAN"
sas_query=""

# Receipts (sha256 of every validated COG) for build provenance.
receipts="$DOWNLOAD_DIR/download_receipts.tsv"
printf 'item_id\tfile\tsize_bytes\tcontent_md5_b64\tsha256\n' > "$receipts.tmp"
count=0
total=0
while IFS=$'\t' read -r region label window year item_id when cloud sun azimuth candidates url size md5; do
  [ "$region" != "region_id" ] || continue
  out="$RASTER_DIR/${url##*/}"
  printf '%s\t%s\t%s\t%s\t%s\n' "$item_id" "${url##*/}" "$size" "$md5" "$(sha256sum "$out" | cut -d ' ' -f1)" >> "$receipts.tmp"
  count=$((count + 1))
  total=$((total + size))
done < "$PLAN"
mv "$receipts.tmp" "$receipts"

present="$(find "$RASTER_DIR" -maxdepth 1 -type f -name 'AST_L1T_*.TIR.tif' | wc -l | tr -d ' ')"
on_disk="$(find "$RASTER_DIR" -maxdepth 1 -type f -name 'AST_L1T_*.TIR.tif' -printf '%s\n' | awk '{s += $1} END {print s + 0}')"
if [ "$present" -ne "$count" ] || [ "$on_disk" -ne "$total" ]; then
  echo "FATAL: plan has $count files / $total bytes but $present files / $on_disk bytes are present" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID mode=$mode files=$count fetched=$fetched cached=$cached bytes=$total"
