#!/usr/bin/env bash
# Metadata-only discovery that produced the pins in download.sh (2026-10-05).
# For each month 2025-10 .. 2026-09 it runs a STAC search for GOES-18 FULL DISK
# goes-cmi items between 19:30 and 20:30 UTC on the 15th, takes the 20:00 slot,
# reads the C13_2km asset href, and HEADs the blob (with an anonymous SAS) for
# Content-Length and Content-MD5. No raster payload is downloaded.
# Output: $DATA_DIR/logs/<id>/discover.<ts>.tsv (compare with download.sh plan).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_goes18_abi_cmi_c13_fulldisk_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
OUT="$LOG_DIR/discover.$RUN_TS.tsv"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STAC="https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/goeseuwest/noaa-goes-cogs"
SAS_QS="$(curl -fsSL --max-time 60 "$SAS_ENDPOINT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"].lstrip("?"))')"

printf 'month\tscan_start_utc\tscan_end_utc\titem_id\tsource_netcdf\turl\tsize_bytes\tcontent_md5_b64\n' > "$OUT"
for ym in 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03 2026-04 2026-05 2026-06 2026-07 2026-08 2026-09; do
  body="{\"collections\":[\"goes-cmi\"],\"datetime\":\"${ym}-15T19:30:00Z/${ym}-15T20:30:00Z\",\"query\":{\"platform\":{\"eq\":\"GOES-18\"},\"goes:image-type\":{\"eq\":\"FULL DISK\"}},\"limit\":20}"
  curl -fsS --max-time 60 -X POST -H 'Content-Type: application/json' -d "$body" "$STAC" -o "$WORK/search.json"
  line="$(python3 - "$WORK/search.json" "$ym" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
ym = sys.argv[2]
hits = [f for f in doc["features"] if f["properties"]["datetime"].startswith(ym + "-15T20:00:")]
if len(hits) != 1:
    raise SystemExit(f"{ym}: expected one 20:00 full-disk item, found {len(hits)}")
f = hits[0]
asset = f["assets"]["C13_2km"]
href = asset["href"]
netcdf = href.rsplit("/", 1)[1].replace("_CMI_C13.tif", ".nc")
print("\t".join([ym, f["properties"]["datetime"], asset["goes:end_observation_time"], f["id"], netcdf, href]))
PY
)"
  url="$(printf '%s' "$line" | cut -f6)"
  headers="$(curl -fsSI --max-time 60 "${url}?${SAS_QS}" | tr -d '\r')"
  size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:" {print $2}' | tail -1)"
  md5="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-md5:" {print $2}' | tail -1)"
  printf '%s\t%s\t%s\n' "$line" "$size" "$md5" | tee -a "$OUT"
done
SAS_QS=""
echo "wrote $OUT"
