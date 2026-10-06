#!/usr/bin/env bash
# Fetch only the 51 EcoManagerTxPlug (IAM) channel members of houses 2-5 from
# the pinned UK-DALE 2017 ukdale.zip on CEDA, by exact byte ranges.
#
# 1. Live license check (CEDA ReadMe) and, when the catalogue front end is
#    reachable, listing JSON check (size + md5).
# 2. One 64 KiB tail range: ZIP64 end records, central directory and the
#    in-archive metadata YAML; the EcoManagerTxPlug selection re-derived from
#    metadata/building{2..5}.yaml must equal the pinned members.tsv.
# 3. One range GET per member (local header + DEFLATE data, ending exactly at
#    the next member). Each range is checked for HTTP 206, exact
#    Content-Range, pinned ETag/Last-Modified, local header, DEFLATE boundary,
#    CRC32, uncompressed size and '<ts> <watts>' text shape.
# Members are stored compressed as fetched; build.sh inflates them locally.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ceda_ukdale_iam_appliance_power_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/members"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PINNED="$RECIPE_DIR/members.tsv"
HELPER="$RECIPE_DIR/scripts/ukdale_zip.py"

# Files are served by dap.ceda.ac.uk (data.ceda.ac.uk only 302-redirects there
# and its front end intermittently answers 503); the JSON catalogue listing
# exists only on data.ceda.ac.uk.
DAP_BASE="https://dap.ceda.ac.uk/edc/efficiency/residential/EnergyConsumption/Domestic/UK-DALE-2017"
CATALOGUE_BASE="https://data.ceda.ac.uk/edc/efficiency/residential/EnergyConsumption/Domestic/UK-DALE-2017"
README_URL="$DAP_BASE/ReadMe_DALE-2017.html"
LISTING_URL="$CATALOGUE_BASE/UK-DALE-FULL-disaggregated?json"
ARCHIVE_URL="$DAP_BASE/UK-DALE-FULL-disaggregated/ukdale.zip"
ARCHIVE_BYTES=3585155959
ARCHIVE_ETAG='"59425b9c-d5b12377"'
ARCHIVE_LAST_MODIFIED="Thu, 15 Jun 2017 10:04:12 GMT"
ARCHIVE_LISTING_MD5="a870331dc3f296ae187133dc3f954df2"
TAIL_BYTES=65536
EXPECTED_MEMBERS=51
EXPECTED_RANGE_BYTES=221188825
UA="openzl-public-datasets-ukdale-iam/1.0"

mkdir -p "$DOWNLOAD_DIR" "$MEMBER_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

small_get() {  # small_get URL OUTPUT MAXBYTES
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 60 --max-time 300 \
    --max-filesize "$3" --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. License page (required) and catalogue listing (checked when reachable;
#    a reachable-but-different listing is fatal). Archive identity itself is
#    enforced on every range response below (size, ETag, Last-Modified) and by
#    the per-member CRC32 values from the central directory.
small_get "$README_URL" "$DOWNLOAD_DIR/ReadMe_DALE-2017.html" 1000000
listing="$DOWNLOAD_DIR/UK-DALE-FULL-disaggregated.listing.json"
rm -f "$listing" "$listing.part"
if ! curl --fail --silent --show-error --location \
  --retry 4 --retry-delay 10 --retry-all-errors --connect-timeout 60 --max-time 120 \
  --max-filesize 1000000 --user-agent "$UA" --output "$listing.part" "$LISTING_URL"; then
  rm -f "$listing.part"
  echo "WARNING: catalogue listing unreachable ($LISTING_URL); relying on pinned size/ETag/Last-Modified/CRC32"
else
  mv "$listing.part" "$listing"
fi
python3 - "$DOWNLOAD_DIR/ReadMe_DALE-2017.html" "$listing" "$ARCHIVE_BYTES" "$ARCHIVE_LISTING_MD5" <<'PY'
import html
import json
import os
import re
import sys

readme_path, listing_path, size, md5 = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
text = html.unescape(re.sub(r"<[^>]+>", " ", open(readme_path, encoding="utf-8", errors="replace").read()))
text = re.sub(r"\s+", " ", text)
section = text.find("Disaggregated (6s) appliance power and aggregated (1s) whole house power Field Description")
if section < 0:
    raise SystemExit("FATAL: ReadMe no longer has the disaggregated (6s) dataset section")
rights = re.search(r"Rights (Creative Commons Attribution 4\.0 International \(CC BY 4\.0\))", text[section:])
if not rights:
    raise SystemExit("FATAL: ReadMe disaggregated section no longer states CC BY 4.0")
print(f"license=ok rights={rights.group(1)!r}")
if os.path.exists(listing_path):
    listing = json.load(open(listing_path, encoding="utf-8"))
    items = [item for item in listing.get("items", []) if item.get("name") == "ukdale.zip"]
    if len(items) != 1:
        raise SystemExit(f"FATAL: listing has {len(items)} ukdale.zip entries")
    item = items[0]
    if int(item.get("size") or 0) != size or item.get("md5") != md5:
        raise SystemExit(f"FATAL: catalogue entry changed: size={item.get('size')} md5={item.get('md5')}")
    print(f"catalogue=ok size={size} md5={md5} last_audit={item.get('last_audit')}")
else:
    print("catalogue=skipped (unreachable)")
PY

# 2. Tail range: central directory + metadata; re-derive and compare selection.
tail_start=$((ARCHIVE_BYTES - TAIL_BYTES))
rm -f "$DOWNLOAD_DIR/zip_tail.bin.part" "$DOWNLOAD_DIR/zip_tail.headers.part"
curl --fail --silent --show-error --location \
  --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 60 --max-time 300 \
  --max-filesize "$((TAIL_BYTES + 1024))" --user-agent "$UA" \
  --range "$tail_start-$((ARCHIVE_BYTES - 1))" \
  --dump-header "$DOWNLOAD_DIR/zip_tail.headers.part" --output "$DOWNLOAD_DIR/zip_tail.bin.part" "$ARCHIVE_URL"
mv "$DOWNLOAD_DIR/zip_tail.headers.part" "$DOWNLOAD_DIR/zip_tail.headers"
mv "$DOWNLOAD_DIR/zip_tail.bin.part" "$DOWNLOAD_DIR/zip_tail.bin"
python3 "$HELPER" resolve \
  --headers "$DOWNLOAD_DIR/zip_tail.headers" --tail "$DOWNLOAD_DIR/zip_tail.bin" \
  --archive-bytes "$ARCHIVE_BYTES" --etag "$ARCHIVE_ETAG" --last-modified "$ARCHIVE_LAST_MODIFIED" \
  --members-out "$DOWNLOAD_DIR/selection.tsv" --metadata-out "$DOWNLOAD_DIR/metadata" \
  --pinned "$PINNED"

member_count=$(($(wc -l < "$PINNED") - 1))
range_total="$(awk -F'\t' 'NR > 1 { s += $7 } END { print s }' "$PINNED")"
if [ "$member_count" != "$EXPECTED_MEMBERS" ] || [ "$range_total" != "$EXPECTED_RANGE_BYTES" ]; then
  echo "FATAL: pinned table has $member_count members / $range_total bytes" >&2
  exit 1
fi

# 3. Member ranges (resumable per member: validated members are kept).
fetched=0
cached=0
while IFS=$'\t' read -r -u 3 house channel member appliance range_start range_end range_bytes _csz _usz _crc; do
  [ "$house" = "house" ] && continue
  stem="house_${house}_channel_$(printf '%02d' "$channel")"
  out="$MEMBER_DIR/$stem.zipmember"
  hdr="$MEMBER_DIR/$stem.headers"
  validate() {
    python3 "$HELPER" member --headers "$hdr" --range-file "$out" --member "$member" --pinned "$PINNED" \
      --archive-bytes "$ARCHIVE_BYTES" --etag "$ARCHIVE_ETAG" --last-modified "$ARCHIVE_LAST_MODIFIED"
  }
  if [ -s "$out" ] && [ -s "$hdr" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if validate; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached $stem failed validation; refetching"
  fi
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$out.part" "$hdr.part"
    if curl --fail --silent --show-error --location \
      --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 60 \
      --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((range_bytes + 1024))" --user-agent "$UA" \
      --range "$range_start-$range_end" \
      --dump-header "$hdr.part" --output "$out.part" "$ARCHIVE_URL"; then
      mv "$hdr.part" "$hdr"
      mv "$out.part" "$out"
      if validate; then
        ok=1
        break
      fi
    fi
    echo "attempt $attempt for $stem ($appliance) failed; retrying"
    rm -f "$out" "$hdr"
    sleep $((attempt * attempt * 15))
  done
  if [ "$ok" != "1" ]; then
    echo "FATAL: could not fetch a valid range for $member" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
done 3< "$PINNED"

python3 - "$MEMBER_DIR" "$PINNED" <<'PY'
import csv
import sys
from pathlib import Path

member_dir, pinned = Path(sys.argv[1]), Path(sys.argv[2])
rows = list(csv.DictReader(pinned.open(encoding="utf-8", newline=""), delimiter="\t"))
expected = {f"house_{r['house']}_channel_{int(r['channel']):02d}.zipmember": int(r["range_bytes"]) for r in rows}
present = {p.name: p.stat().st_size for p in member_dir.glob("*.zipmember")}
if present != expected:
    extra = sorted(set(present) - set(expected))
    missing = sorted(set(expected) - set(present))
    raise SystemExit(f"FATAL: member set mismatch missing={missing} extra={extra}")
print(f"members=ok count={len(present)} bytes={sum(present.values())}")
PY
echo "fetched=$fetched cached=$cached"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
