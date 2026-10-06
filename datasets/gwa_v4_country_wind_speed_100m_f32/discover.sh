#!/usr/bin/env bash
# Documents how countries.tsv was resolved on 2026-10-06. Not part of the
# acceptance path (download.sh/build.sh/verify.sh never call it) and it only
# makes small metadata requests:
#   * one HEAD per pool country on the CDN (status, size, ETag, Last-Modified)
#   * one 64 KiB range read of the BigTIFF header (IFD chain + tile tables)
#   * range reads of the tiles of the smallest overview IFD (a few KB) to
#     estimate the non-NaN share of the raster
#   * for the selected countries only, one no-follow request to the official
#     GWA GIS API to confirm it 302-redirects to the pinned CDN object
# Network I/O is curl only; python parses the fetched bytes.
#
# Selection rule used for countries.tsv:
#   pool  = 77 hand-picked small and medium countries on all inhabited
#           continents (never an enumeration of all countries; see README)
#   keep  = HEAD 200, single-part S3 ETag (plain MD5), size <= 17,000,000 B,
#           smallest-overview valid share >= 0.45
#   then a regional spread of 31 of the 43 qualifying countries was pinned,
#   leaving out MKD PRT LUX LBR BDI BIH HTI ALB SYR SLE SVK TUN to keep the
#   primary output under ~400 MB (screener guidance).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwa_v4_country_wind_speed_100m_f32"
OUT_DIR="${DISCOVER_DIR:-$DATA_ROOT/logs/$DATASET_ID/discover}"
mkdir -p "$OUT_DIR/heads"
export PYTHONDONTWRITEBYTECODE=1

CDN="https://gwa.cdn.nazkamapps.com/country_tifs_v4"
API="https://globalwindatlas.info/api/gis/country"
TIFF="$RECIPE_DIR/scripts/gwa_tiff.py"
UA="openzl-public-datasets/1.0 (recipe discovery; few small requests)"

POOL="${DISCOVER_POOL:-LBN SVN ARM ISR BEL CHE SVK SLV JOR SRB LTU NLD CZE GEO HUN EST AUT HRV LVA BGR DNK
LUX CYP MNE MKD ALB BIH MDA KWT QAT ARE TUN RWA BDI MWI LSO SWZ BTN NPL LKA CRI PAN JAM HTI
DOM URY BLZ GTM HND NIC TGO BEN SLE LBR GMB SEN IRL PRT TWN KOR BGD KHM LAO TJK KGZ AZE ERI
DJI UGA SYR GHA ECU PRY ZWE ISL NZL}"

RESULTS="$OUT_DIR/pool_probe.tsv"
printf 'iso3\tstatus\tsize_bytes\tetag\tlast_modified\twidth\theight\tupper_left_lon\tupper_left_lat\toverview_valid_share\toverview_min\toverview_max\n' > "$RESULTS"
for iso in $POOL; do
  url="$CDN/${iso}_wind-speed_100m.tif"
  hdr="$(curl -sSI --max-time 30 -A "$UA" "$url" | tr -d '\r' || true)"
  status="$(printf '%s\n' "$hdr" | awk '/^HTTP\//{s=$2} END{print s}')"
  size="$(printf '%s\n' "$hdr" | awk 'tolower($1)=="content-length:"{print $2}' | tail -1)"
  etag="$(printf '%s\n' "$hdr" | awk 'tolower($1)=="etag:"{gsub(/"/,"",$2); print $2}' | tail -1)"
  lastmod="$(printf '%s\n' "$hdr" | sed -n 's/^[Ll]ast-[Mm]odified: //p' | tail -1)"
  geom='{}'
  if [ "$status" = "200" ] && [ -n "$size" ] && [ "$size" -le 17000000 ] && [[ "$etag" != *-* ]]; then
    head_bin="$OUT_DIR/heads/${iso}_head.bin"
    curl -sS --max-time 60 -A "$UA" -r 0-65535 -o "$head_bin" "$url"
    tiles=()
    k=0
    for range in $(python3 "$TIFF" overview-ranges "$head_bin"); do
      tile="$OUT_DIR/heads/${iso}_ov_${k}.bin"
      curl -sS --max-time 60 -A "$UA" -r "$range" -o "$tile" "$url"
      tiles+=("$tile")
      k=$((k + 1))
    done
    geom="$(python3 "$TIFF" overview-share "$head_bin" "${tiles[@]}")"
    rm -f "$head_bin" "${tiles[@]}"
  fi
  python3 - "$iso" "$status" "${size:-}" "${etag:-}" "${lastmod:-}" "$geom" >> "$RESULTS" <<'PY'
import json, sys
iso, status, size, etag, lastmod, geom = sys.argv[1:7]
g = json.loads(geom)
lon, lat = g.get("tiepoint_lon_lat", ["", ""])
print("\t".join(str(x) for x in [iso, status, size, etag, lastmod, g.get("width", ""), g.get("height", ""),
                                 f"{lon:.6f}" if lon != "" else "", f"{lat:.6f}" if lat != "" else "",
                                 g.get("overview_valid_share", ""), g.get("overview_min", ""), g.get("overview_max", "")]))
PY
  echo "probed $iso status=$status size=${size:-?}"
  sleep 0.5
done

# Confirm the official GIS API URL redirects to each pinned CDN object.
REDIRECTS="$OUT_DIR/api_redirects.tsv"
printf 'iso3\tapi_url\tlocation\n' > "$REDIRECTS"
tail -n +2 "$RECIPE_DIR/countries.tsv" | cut -f1 | while read -r iso; do
  api="$API/$iso/wind-speed/100"
  loc="$(curl -sS -o /dev/null --max-time 30 -A "$UA" -w '%{redirect_url}' "$api")"
  printf '%s\t%s\t%s\n' "$iso" "$api" "$loc" >> "$REDIRECTS"
  sleep 0.5
done

python3 - "$RESULTS" "$REDIRECTS" "$RECIPE_DIR/countries.tsv" <<'PY'
import csv, sys
probe = {r["iso3"]: r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8"), delimiter="\t")}
redirects = {r["iso3"]: r["location"] for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"), delimiter="\t")}
pinned = list(csv.DictReader(open(sys.argv[3], encoding="utf-8"), delimiter="\t"))
qualifying = sorted(i for i, r in probe.items() if r["overview_valid_share"] and float(r["overview_valid_share"]) >= 0.45)
print(f"qualifying={len(qualifying)}: {' '.join(qualifying)}")
problems = []
for row in pinned:
    p = probe.get(row["iso3"])
    for key in ("size_bytes", "width", "height", "upper_left_lon", "upper_left_lat", "overview_valid_share"):
        if p is None or str(p[key]) != str(row[key]):
            problems.append(f"{row['iso3']}: {key} probe={p and p[key]!r} pinned={row[key]!r}")
    if p is not None and p["etag"] != row["etag_md5"]:
        problems.append(f"{row['iso3']}: etag probe={p['etag']} pinned={row['etag_md5']}")
    if row["iso3"] not in qualifying:
        problems.append(f"{row['iso3']}: pinned but not qualifying")
    if redirects.get(row["iso3"]) != row["url"]:
        problems.append(f"{row['iso3']}: API redirect {redirects.get(row['iso3'])!r} != pinned {row['url']}")
print("pinned countries consistent with probe" if not problems else "\n".join(problems))
PY
