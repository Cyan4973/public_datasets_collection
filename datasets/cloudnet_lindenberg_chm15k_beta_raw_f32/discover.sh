#!/usr/bin/env bash
# Documents how sources.tsv was produced (run once at authoring time; not part
# of the download/build path).  Lists every 2024 Cloudnet "lidar" product file
# of the Lindenberg CHM15k, keeps the instrument cdf99c53-... (DWD CHM 15k,
# serial CHM100110), and for each month picks the 1st and the 15th day, or the
# next later day of that month if the target day is not errorLevel "pass" with
# coverage >= 0.99.  The per-file API record then pins uuid, filename, size,
# sha256 and the cloudnetpy version.
#
#   bash discover.sh > /tmp/autocollect/cloudnet_lindenberg_chm15k_beta_raw_f32/sources.tsv
set -euo pipefail

API="https://cloudnet.fmi.fi/api"
WORK="$(mktemp -d /tmp/cloudnet_discover.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

curl --fail --silent --show-error --max-time 120 \
  --output "$WORK/files2024.json" \
  "$API/files?product=lidar&instrument=chm15k&site=lindenberg&dateFrom=2024-01-01&dateTo=2024-12-31"

python3 -I - "$WORK/files2024.json" > "$WORK/picked.tsv" <<'PY'
import json, sys
INSTRUMENT = "cdf99c53-6bd0-4146-be2a-604cf1164c30"
rows = json.load(open(sys.argv[1]))
by_date = {}
for r in rows:
    if r["instrument"]["uuid"] != INSTRUMENT or r["site"]["id"] != "lindenberg" or r["product"]["id"] != "lidar":
        continue
    if r["volatile"] or r["tombstoneReason"] is not None or r["legacy"]:
        continue
    if r["errorLevel"] != "pass" or float(r["coverage"]) < 0.99:
        continue
    by_date[r["measurementDate"]] = r
for month in range(1, 13):
    for target in (1, 15):
        for day in range(target, target + 7):
            date = f"2024-{month:02d}-{day:02d}"
            if date in by_date:
                r = by_date[date]
                print("\t".join([date, r["uuid"], r["filename"], str(r["size"]), r["checksum"], str(r["coverage"])]))
                break
        else:
            raise SystemExit(f"no eligible day near 2024-{month:02d}-{target:02d}")
PY

printf 'date\tuuid\tfilename\tsize\tsha256\tcloudnetpy_version\n'
while IFS=$'\t' read -r date uuid filename size sha coverage; do
  curl --fail --silent --show-error --max-time 60 --output "$WORK/$uuid.json" "$API/files/$uuid"
  version="$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print([s["version"] for s in d["software"] if s["id"]=="cloudnetpy"][0])' "$WORK/$uuid.json")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$date" "$uuid" "$filename" "$size" "$sha" "$version"
done < "$WORK/picked.tsv"
