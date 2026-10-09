#!/usr/bin/env bash
# Download the 30 pinned Sentinel-2 Collection-1 L2A SNW_20m (snow probability)
# COGs listed in sources.tsv from the public anonymous Element84
# bucket e84-earth-search-sentinel-data (collection sentinel-2-c1-l2a only).
# No live STAC search: item IDs, URLs, sizes and SHA-256 (from the STAC
# file:checksum multihash) are pinned in sources.tsv; scripts/discover.py and
# scripts/select_plan.py document how they were resolved.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="earthsearch_s2c1_l2a_snow_probability_u8"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/snw_20m"
SOURCES="$RECIPE_DIR/sources.tsv"
mkdir -p "$LOG_DIR" "$RASTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets/1.0 ($DATASET_ID)"
EXPECTED_FILES=30
EXPECTED_BYTES=274844184

# ---- validate the pinned plan before any network access -------------------
python3 -I -B - "$SOURCES" "$EXPECTED_FILES" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
path, n_expected, bytes_expected = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = list(csv.DictReader(open(path, encoding="utf-8", newline=""), delimiter="\t"))
assert len(rows) == n_expected, f"plan rows {len(rows)} != {n_expected}"
assert sum(int(r["size_bytes"]) for r in rows) == bytes_expected, "plan byte total mismatch"
assert len({r["item_id"] for r in rows}) == n_expected, "duplicate item IDs"
assert len({r["grid_code"] for r in rows}) == n_expected, "more than one scene per MGRS tile"
assert len({r["cell"] for r in rows}) == n_expected, "more than one scene per selection cell"
for r in rows:
    item = r["item_id"]
    m = re.fullmatch(r"S2[AB]_T(\d{1,2})([A-Z])([A-Z]{2})_(2024)(\d\d)(\d\d)T\d{6}_L2A", item)
    assert m, item
    zone, band, sq, year, month, _ = m.groups()
    assert month in ("03", "04"), f"outside the Mar-Apr 2024 window: {item}"
    assert r["grid_code"] == f"MGRS-{int(zone)}{band}{sq}", item
    assert r["processing_baseline"] == "05.10", item
    assert float(r["cloud_cover"]) < 15 and 25 <= float(r["snow_ice_percentage"]) <= 75, item
    want = (f"https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/"
            f"{int(zone)}/{band}/{sq}/{year}/{int(month)}/{item}/SNW_20m.tif")
    assert r["url"] == want, f"unexpected URL for {item}: {r['url']}"
    assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]), item
    assert 100_000 < int(r["size_bytes"]) < 60_000_000, item
print(f"plan_ok rows={len(rows)} tiles={len({r['grid_code'] for r in rows})} bytes={bytes_expected}")
PY

file_ok() {
  # file_ok PATH SIZE SHA256 -> 0 when size, SHA-256 and TIFF magic all match
  local path="$1" size="$2" sha="$3"
  [ -f "$path" ] || return 1
  [ "$(stat -c %s "$path")" = "$size" ] || return 1
  [ "$(od -An -tx1 -N4 "$path" | tr -d ' \n')" = "49492a00" ] || return 1
  [ "$(sha256sum "$path" | cut -d ' ' -f1)" = "$sha" ] || return 1
}

fetched=0
cached=0
while IFS=$'\t' read -r item_id grid_code datetime platform baseline lat lon cloud snow hdr_nz hdr_mean cell size_bytes sha256 url; do
  [ "$item_id" != "item_id" ] || continue
  out="$RASTER_DIR/${item_id}_SNW_20m.tif"
  if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && file_ok "$out" "$size_bytes" "$sha256"; then
    cached=$((cached + 1))
    echo "cache_hit item=$item_id bytes=$size_bytes"
    continue
  fi
  rm -f "$out"
  part="$out.part"
  ok=0
  for attempt in 1 2 3 4; do
    if [ -f "$part" ] && [ "$(stat -c %s "$part")" = "$size_bytes" ]; then
      ok=1
      break
    fi
    echo "fetch item=$item_id attempt=$attempt bytes=$size_bytes"
    if curl -fsSL -C - --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
        --connect-timeout 30 -A "$UA" -o "$part" "$url"; then
      if [ "$(stat -c %s "$part")" = "$size_bytes" ]; then
        ok=1
        break
      fi
      echo "WARN: size mismatch for $item_id: got $(stat -c %s "$part") want $size_bytes" >&2
      if [ "$(stat -c %s "$part")" -gt "$size_bytes" ]; then rm -f "$part"; fi
    else
      echo "WARN: curl failed for $item_id (attempt $attempt); resuming" >&2
    fi
    sleep $((attempt * 10))
  done
  [ "$ok" = 1 ] || { echo "FATAL: could not fetch $url" >&2; exit 1; }
  mv "$part" "$out"
  if ! file_ok "$out" "$size_bytes" "$sha256"; then
    echo "FATAL: $item_id failed size/SHA-256/TIFF-magic validation" >&2
    rm -f "$out"
    exit 1
  fi
  fetched=$((fetched + 1))
done < "$SOURCES"
echo "transfer_done fetched=$fetched cached=$cached"

# ---- semantic validation: exact SNW_20m TIFF layout -----------------------
python3 -I -B - "$RECIPE_DIR/scripts" "$SOURCES" "$RASTER_DIR" "$DOWNLOAD_DIR/download_inventory.json" <<'PY'
import csv, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import snw_cog
rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8", newline=""), delimiter="\t"))
raster_dir = Path(sys.argv[3])
records = []
for r in rows:
    path = raster_dir / f"{r['item_id']}_SNW_20m.tif"
    lay = snw_cog.layout(path.read_bytes())  # raises on any unexpected layout
    st = lay["stats"]
    if not (st.get("MAXIMUM", 0) <= 100 and 0.0 < st.get("VALID_PERCENT", 0) < 100.0):
        raise SystemExit(f"{path.name}: implausible GDAL statistics {st}")
    records.append({"item_id": r["item_id"], "file": path.name, "bytes": path.stat().st_size,
                    "sha256": r["sha256"], "url": r["url"], "gdal_statistics": st})
Path(sys.argv[4]).write_text(json.dumps({"dataset_id": "earthsearch_s2c1_l2a_snow_probability_u8",
                                         "files": len(records), "source_bytes": sum(x["bytes"] for x in records),
                                         "records": records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} bytes={sum(x['bytes'] for x in records)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
