#!/usr/bin/env bash
# Download the 13 pinned Landsat-5 MSS Collection 2 Level-1 (L1TP, Tier 1)
# scenes listed in $RECIPE_DIR/sources.tsv from the Microsoft Planetary
# Computer landsat-c2-l1 collection: per scene the four uint8 band COGs B1
# green, B2 red, B3 nir08, B4 nir09 (52 files) plus the small MTL.json
# metadata (13 files). The uint16 QA_PIXEL / QA_RADSAT assets are not fetched.
#
# The plan (item id, product id, href, Content-Length, Azure Content-MD5 and
# IFD-0 shape per file) was resolved on 2026-10-06 by discover.sh
# (metadata-only STAC search + HEAD + 64 KiB header probes) and pinned in
# sources.tsv. Asset hrefs embed the USGS processing date, so they are pinned
# verbatim rather than rebuilt from item ids.
#
# Rights evidence is captured first (blocking): the Planetary Computer
# collection JSON (required) plus at least one grant document (the USGS data
# policy page that MPC links as its "Public Domain" license, or the
# USGS-managed AWS Open Data Registry "USGS Landsat" entry), phrase-checked by
# scripts/rights_check.py and recorded with sha256 in rights_receipts.tsv.
#
# Access: the landsateuwest/landsat-c2 container needs a short-lived read-only
# SAS that the Planetary Computer issues anonymously (no account, key or
# login) at /api/sas/v1/token/landsateuwest/landsat-c2. It is fetched per run,
# held in a shell variable, refreshed every 15 minutes or after a failed
# transfer, and never logged. Network I/O is curl only; Python only validates.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_landsat_c2_l1_mss_dn_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/scenes"
mkdir -p "$LOG_DIR" "$RASTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets/1.0 ($DATASET_ID)"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/landsateuwest/landsat-c2"
PINNED="$RECIPE_DIR/sources.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
COG="$RECIPE_DIR/scripts/mss_cog.py"
MTL_CHECK="$RECIPE_DIR/scripts/mtl_check.py"
HELPER="$RECIPE_DIR/scripts/stac_select.py"
# Exact pinned scope (sources.tsv, resolved 2026-10-06).
EXPECTED_SCENES=13
EXPECTED_FILES=65
EXPECTED_BYTES=411160598
export PYTHONDONTWRITEBYTECODE=1

# The TIFF parser is self-tested on synthetic tiles first.
python3 "$COG" selftest

if [ ! -f "$PINNED" ]; then
  echo "FATAL: missing pinned plan $PINNED (discover.sh documents how it was resolved)" >&2
  exit 1
fi
cp "$PINNED" "$PLAN.tmp"
python3 - "$PLAN.tmp" "$EXPECTED_SCENES" "$EXPECTED_FILES" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
path, want_scenes, want_files, want_bytes = sys.argv[1], *map(int, sys.argv[2:5])
header = ["region_id", "region_label", "wrs_path", "wrs_row", "item_id", "product_id", "datetime", "cloud_cover",
          "sun_elevation", "sun_azimuth", "proj_rows", "proj_cols", "candidates", "asset", "band", "url",
          "size_bytes", "content_md5_b64", "tiff_width", "tiff_height", "tiff_predictor"]
with open(path, encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter="\t")
    got = next(reader)
    if got != header:
        raise SystemExit(f"FATAL: plan header {got} != {header}")
    rows = [dict(zip(header, r)) for r in reader if r]
bands = {"green": "B1", "red": "B2", "nir08": "B3", "nir09": "B4", "mtl.json": "MTL"}
for r in rows:
    if any(v == "" for v in r.values()):
        raise SystemExit(f"FATAL: empty plan field in {r['item_id']} {r['band']}")
    p, w = r["product_id"], f"{r['wrs_path']}{r['wrs_row']}"
    if not re.fullmatch(rf"LM05_L1TP_{w}_(\d{{8}})_\d{{8}}_02_T1", p) or r["item_id"] != p[:25] + "_02_T1":
        raise SystemExit(f"FATAL: product {p} / item {r['item_id']} is not a Landsat-5 MSS L1TP T1 C2 product of {w}")
    if bands.get(r["asset"]) != r["band"]:
        raise SystemExit(f"FATAL: asset {r['asset']} mapped to band {r['band']}")
    suffix = "MTL.json" if r["band"] == "MTL" else f"{r['band']}.TIF"
    want_url = (f"https://landsateuwest.blob.core.windows.net/landsat-c2/level-1/standard/mss/"
                f"{p[17:21]}/{r['wrs_path']}/{r['wrs_row']}/{p}/{p}_{suffix}")
    if r["url"] != want_url:
        raise SystemExit(f"FATAL: unexpected URL {r['url']}")
    if not ("1984-03-01" <= r["datetime"][:10] <= "1993-12-31") or r["datetime"][:10].replace("-", "") != p[17:25]:
        raise SystemExit(f"FATAL: {p} datetime {r['datetime']} outside 1984-03-01..1993-12-31 or not the product date")
    if not (0.0 <= float(r["cloud_cover"]) < 5.0) or float(r["sun_elevation"]) <= 30.0:
        raise SystemExit(f"FATAL: {p} violates the cloud/sun rule")
    size = int(r["size_bytes"])
    lo, hi = (2000, 200000) if r["band"] == "MTL" else (500000, 40000000)
    if not lo <= size <= hi:
        raise SystemExit(f"FATAL: {p} {r['band']} implausible size {size}")
    if not re.fullmatch(r"[A-Za-z0-9+/]{22}==", r["content_md5_b64"]):
        raise SystemExit(f"FATAL: {p} {r['band']} missing or malformed Content-MD5 {r['content_md5_b64']}")
    if r["band"] != "MTL" and (r["tiff_width"] != r["proj_cols"] or r["tiff_height"] != r["proj_rows"]
                               or r["tiff_predictor"] not in ("1", "2")):
        raise SystemExit(f"FATAL: {p} {r['band']} pinned IFD0 shape/predictor inconsistent")
scenes = {}
for r in rows:
    scenes.setdefault(r["item_id"], []).append(r["band"])
if any(sorted(v) != ["B1", "B2", "B3", "B4", "MTL"] for v in scenes.values()):
    raise SystemExit(f"FATAL: every scene needs exactly B1..B4 + MTL: {scenes}")
if len({r["url"] for r in rows}) != len(rows) or len({(r["wrs_path"], r["wrs_row"]) for r in rows}) != len(scenes):
    raise SystemExit("FATAL: duplicate URL or more than one scene per path/row")
total = sum(int(r["size_bytes"]) for r in rows)
if (len(scenes), len(rows), total) != (want_scenes, want_files, want_bytes):
    raise SystemExit(f"FATAL: plan has {len(scenes)} scenes/{len(rows)} files/{total} bytes, "
                     f"pinned {want_scenes}/{want_files}/{want_bytes}")
print(f"plan_ok scenes={len(scenes)} files={len(rows)} bytes={total}")
PY
mv "$PLAN.tmp" "$PLAN"

# ---- rights evidence (blocking; runs before any raster transfer) -----------
RIGHTS_DIR="$DOWNLOAD_DIR/rights"
RIGHTS_CHECK="$RECIPE_DIR/scripts/rights_check.py"
RIGHTS_RECEIPTS="$DOWNLOAD_DIR/rights_receipts.tsv"
MPC_COLLECTION_URL="https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l1"
USGS_POLICY_URLS=(
  "https://www.usgs.gov/core-science-systems/hdds/data-policy"
  "https://www.usgs.gov/emergency-operations-portal/data-policy"
)
AWS_REGISTRY_URLS=(
  "https://registry.opendata.aws/usgs-landsat/"
  "https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/usgs-landsat.yaml"
)
mkdir -p "$RIGHTS_DIR"

# fetch_page <url> <out> <max_time>: curl into <out>.part and record requested
# URL, effective URL and HTTP code in <out>.part.meta.
fetch_page() {
  local url="$1" out="$2" max_time="$3" meta=""
  rm -f "$out.part" "$out.part.meta"
  if meta="$(curl --globoff -fsSL --retry 2 --retry-all-errors --retry-delay 5 --connect-timeout 20 \
      --max-time "$max_time" --max-filesize 20000000 -A "$UA" -o "$out.part" -w '%{http_code} %{url_effective}' "$url")"; then
    printf '%s\t%s\t%s\n' "$url" "${meta#* }" "${meta%% *}" > "$out.part.meta"
    echo "rights_fetch url=$url effective=${meta#* } http=${meta%% *} bytes=$(stat -c %s "$out.part")"
    return 0
  fi
  echo "WARN: rights fetch failed url=$url (${meta:-no response})" >&2
  rm -f "$out.part" "$out.part.meta"
  return 1
}

# capture <file> <kind> <max_time> <url>...: reuse a saved copy that still
# passes its check, else fetch the URLs in order until one passes. Returns 1
# (without exiting) when none passes.
capture() {
  local name="$1" kind="$2" max_time="$3" out url
  shift 3
  out="$RIGHTS_DIR/$name"
  if [ -s "$out" ] && [ -s "$out.meta" ] && python3 "$RIGHTS_CHECK" "$kind" "$out" > /dev/null; then
    echo "rights_reuse file=$name"
    return 0
  fi
  rm -f "$out" "$out.meta"
  for url in "$@"; do
    if fetch_page "$url" "$out" "$max_time"; then
      if python3 "$RIGHTS_CHECK" "$kind" "$out.part"; then
        mv "$out.part.meta" "$out.meta"
        mv "$out.part" "$out"
        return 0
      fi
      echo "WARN: $kind check failed for $url" >&2
      rm -f "$out.part" "$out.part.meta"
    fi
  done
  return 1
}

if ! capture "mpc_collection_landsat-c2-l1.json" mpc 120 "$MPC_COLLECTION_URL"; then
  echo "FATAL: could not capture a Planetary Computer collection JSON that passes its check" >&2
  exit 1
fi
grants=0
# usgs.gov intermittently times out or refuses curl (504/403 seen on 2026-10-06);
# it is tried with a short timeout and the USGS-managed AWS registry entry is
# the reachable alternative grant document. At least one must pass.
if capture "usgs_data_policy.html" usgs 45 "${USGS_POLICY_URLS[@]}"; then
  grants=$((grants + 1))
else
  echo "note: USGS data policy page not captured this run (usgs.gov unreachable or changed)"
fi
if capture "usgs_landsat_open_data_registry.txt" aws 60 "${AWS_REGISTRY_URLS[@]}"; then
  grants=$((grants + 1))
else
  echo "note: AWS Open Data Registry USGS Landsat entry not captured this run"
fi
if [ "$grants" -lt 1 ]; then
  echo "FATAL: no grant document (USGS data policy or USGS Landsat registry entry) passed its check" >&2
  exit 1
fi

printf 'file\tkind\trequested_url\teffective_url\thttp_code\tsize_bytes\tsha256\tcheck\n' > "$RIGHTS_RECEIPTS.tmp"
for entry in "mpc_collection_landsat-c2-l1.json:mpc" "usgs_data_policy.html:usgs" "usgs_landsat_open_data_registry.txt:aws"; do
  name="${entry%%:*}"
  kind="${entry##*:}"
  out="$RIGHTS_DIR/$name"
  [ -s "$out" ] || continue
  IFS=$'\t' read -r requested effective code < "$out.meta"
  if ! python3 "$RIGHTS_CHECK" "$kind" "$out" > /dev/null; then
    echo "FATAL: saved $name no longer passes its check" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tok\n' "$name" "$kind" "$requested" "$effective" "$code" \
    "$(stat -c %s "$out")" "$(sha256sum "$out" | cut -d ' ' -f1)" >> "$RIGHTS_RECEIPTS.tmp"
done
mv "$RIGHTS_RECEIPTS.tmp" "$RIGHTS_RECEIPTS"
echo "rights_receipts:"
cat "$RIGHTS_RECEIPTS"

# ---- band COGs and MTL.json -------------------------------------------------
sas_query=""
sas_time=0
refresh_sas() {
  local now attempt
  now="$(date +%s)"
  if [ -n "$sas_query" ] && [ $((now - sas_time)) -le 900 ]; then
    return 0
  fi
  for attempt in 1 2 3 4 5; do
    if curl --globoff -fsSL --retry 3 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
        -A "$UA" -o "$DOWNLOAD_DIR/.sas.json" "$SAS_ENDPOINT" \
        && sas_query="$(python3 "$HELPER" sas "$DOWNLOAD_DIR/.sas.json")"; then
      rm -f "$DOWNLOAD_DIR/.sas.json"
      sas_time="$now"
      echo "sas_ok account=landsateuwest container=landsat-c2"
      return 0
    fi
    rm -f "$DOWNLOAD_DIR/.sas.json"
    echo "WARN: SAS token request failed (attempt $attempt); backing off" >&2
    sleep $((attempt * 10))
  done
  echo "FATAL: could not obtain an anonymous Planetary Computer SAS token" >&2
  exit 1
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

# file_ok PATH BAND SIZE MD5 PRODUCT PATH ROW ROWS COLS: exact size and Azure
# Content-MD5, then for COGs the TIFF structure (uint8, Deflate, tiled,
# GDAL_NODATA 0, IFD0 = pinned shape, every tile inflates) and for MTL.json
# the semantic product check.
file_ok() {
  local f="$1" band="$2" size="$3" md5="$4" product="$5" wpath="$6" wrow="$7" rows="$8" cols="$9" report
  [ -f "$f" ] || return 1
  [ "$(stat -c %s "$f")" = "$size" ] || { echo "size mismatch $f" >&2; return 1; }
  [ "$(md5_b64 "$f")" = "$md5" ] || { echo "md5 mismatch $f" >&2; return 1; }
  if [ "$band" = "MTL" ]; then
    python3 "$MTL_CHECK" "$f" "$product" "$wpath" "$wrow" "$rows" "$cols" > "$f.validation.json.tmp" \
      || { rm -f "$f.validation.json.tmp"; return 1; }
  else
    [ "$(od -An -tx1 -N4 "$f" | tr -d ' \n')" = "49492a00" ] || { echo "not a little-endian TIFF $f" >&2; return 1; }
    python3 "$COG" validate "$f" > "$f.validation.json.tmp" || { rm -f "$f.validation.json.tmp"; return 1; }
    report="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["width"], d["height"])' "$f.validation.json.tmp")"
    if [ "$report" != "$cols $rows" ]; then
      echo "IFD0 shape $report != pinned $cols $rows for $f" >&2
      rm -f "$f.validation.json.tmp"
      return 1
    fi
  fi
  mv "$f.validation.json.tmp" "$f.validation.json"
}

fetched=0
cached=0
while IFS=$'\t' read -r region label wpath wrow item_id product when cloud sun azimuth prows pcols candidates asset band url size md5 tw th tp; do
  [ "$region" != "region_id" ] || continue
  out="$RASTER_DIR/${url##*/}"
  if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && file_ok "$out" "$band" "$size" "$md5" "$product" "$wpath" "$wrow" "$prows" "$pcols"; then
    cached=$((cached + 1))
    echo "cache_hit product=$product band=$band bytes=$size"
    continue
  fi
  rm -f "$out" "$out.validation.json"
  part="$out.part"
  for attempt in 1 2 3 4; do
    part_size=0
    [ -f "$part" ] && part_size="$(stat -c %s "$part")"
    if [ "$part_size" -gt "$size" ]; then
      rm -f "$part"
      part_size=0
    fi
    if [ "$part_size" -lt "$size" ]; then
      refresh_sas
      echo "fetch product=$product band=$band region=$region bytes=$size resume_from=$part_size attempt=$attempt"
      curl --globoff -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
        -sS -o "$part" "${url}?${sas_query}" \
        || echo "WARN: curl exited non-zero product=$product band=$band attempt=$attempt (partial kept for resume)" >&2
      part_size=0
      [ -f "$part" ] && part_size="$(stat -c %s "$part")"
      if [ "$part_size" -lt "$size" ]; then
        sas_query=""  # force a fresh SAS for the retry
      fi
    fi
    if [ "$part_size" -eq "$size" ]; then
      if file_ok "$part" "$band" "$size" "$md5" "$product" "$wpath" "$wrow" "$prows" "$pcols"; then
        mv "$part.validation.json" "$out.validation.json"
        mv "$part" "$out"
        break
      fi
      echo "WARN: complete file failed validation product=$product band=$band attempt=$attempt; discarding" >&2
      rm -f "$part" "$part.validation.json"
    fi
    sleep $((attempt * 10))
  done
  if ! [ -f "$out" ] || ! [ -f "$out.validation.json" ]; then
    echo "FATAL: could not obtain a valid copy of product=$product band=$band (rerun resumes any partial)" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "validated product=$product band=$band bytes=$size md5=$md5"
done < "$PLAN"
sas_query=""

# Receipts (sha256 of every validated file) for build provenance.
receipts="$DOWNLOAD_DIR/download_receipts.tsv"
printf 'product_id\tband\tfile\tsize_bytes\tcontent_md5_b64\tsha256\n' > "$receipts.tmp"
count=0
total=0
while IFS=$'\t' read -r region label wpath wrow item_id product when cloud sun azimuth prows pcols candidates asset band url size md5 tw th tp; do
  [ "$region" != "region_id" ] || continue
  out="$RASTER_DIR/${url##*/}"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$product" "$band" "${url##*/}" "$size" "$md5" "$(sha256sum "$out" | cut -d ' ' -f1)" >> "$receipts.tmp"
  count=$((count + 1))
  total=$((total + size))
done < "$PLAN"
mv "$receipts.tmp" "$receipts"

present="$(find "$RASTER_DIR" -maxdepth 1 -type f \( -name 'LM05_*_B[1-4].TIF' -o -name 'LM05_*_MTL.json' \) | wc -l | tr -d ' ')"
on_disk="$(find "$RASTER_DIR" -maxdepth 1 -type f \( -name 'LM05_*_B[1-4].TIF' -o -name 'LM05_*_MTL.json' \) -printf '%s\n' | awk '{s += $1} END {print s + 0}')"
if [ "$present" -ne "$count" ] || [ "$on_disk" -ne "$total" ]; then
  echo "FATAL: plan has $count files / $total bytes but $present files / $on_disk bytes are present" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count fetched=$fetched cached=$cached bytes=$total"
