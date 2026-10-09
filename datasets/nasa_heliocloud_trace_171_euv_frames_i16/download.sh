#!/usr/bin/env bash
# Fetch the pinned TRACE 171 A full-frame FITS files (1998-04-20..1998-10-31, header regime incl.
# the near-lossless FRM_NAM allowlist applied by scripts/discover.py) listed in sources.tsv from the anonymous NASA
# GSFC HelioCloud bucket (gov-nasa-hdrl-data1), plus, best effort, the TRACE data policy page
# and the NASA SMD science information policy page as rights evidence.
# The data-level checks (ringing, empty near-zero bins, degeneracy) are applied later by build.sh;
# the large sdac/trace/indices/*.csv files are never fetched.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_heliocloud_trace_171_euv_frames_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FITS_DIR="$DOWNLOAD_DIR/fits"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BUCKET_URL="https://gov-nasa-hdrl-data1.s3.amazonaws.com"
EXPECTED_FILES=95
EXPECTED_BYTES=200001600
TRACE_POLICY_URL="https://sdowww.lmsal.com/TRACE/Data/DataArchive/dapolicy.htm"
SMD_URL="https://science.nasa.gov/researchers/science-data/science-information-policy/"
UA="openzl-public-datasets-trace-171/1.0"

mkdir -p "$FITS_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Inventory sanity: count, total size, key shape, filename = key basename, MD5-shaped ETag.
SOURCES="$SOURCES" EXPECTED_FILES="$EXPECTED_FILES" EXPECTED_BYTES="$EXPECTED_BYTES" python3 - <<'PY'
import csv, os, re
rows = list(csv.DictReader(open(os.environ["SOURCES"], newline=""), delimiter="\t"))
key_re = re.compile(r"^sdac/trace/1998/(0[4-9]|10)/\d{2}/trac_171____a0_1998\d{4}_\d{6}\.fts$")
if len(rows) != int(os.environ["EXPECTED_FILES"]) or len({r["key"] for r in rows}) != len(rows):
    raise SystemExit("pinned source count changed or duplicated")
if sum(int(r["size_bytes"]) for r in rows) != int(os.environ["EXPECTED_BYTES"]):
    raise SystemExit("pinned aggregate size changed")
for r in rows:
    if not key_re.match(r["key"]) or r["key"].rsplit("/", 1)[1] != r["filename"]:
        raise SystemExit(f"unsafe or malformed pinned key: {r['key']}")
    if r["size_bytes"] != "2105280" or not re.fullmatch(r"[0-9a-f]{32}", r["md5_etag"]):
        raise SystemExit(f"malformed size/ETag pin for {r['filename']}")
print(f"source_inventory=ok files={len(rows)} bytes={sum(int(r['size_bytes']) for r in rows)}")
PY

# Rights evidence (best effort, warn-only).
fetch_evidence() {
  local url="$1" out="$2" phrase="$3"
  if curl --fail --silent --show-error --location --retry 2 --retry-delay 3 \
    --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
    --output "$out.part" "$url"; then
    mv "$out.part" "$out"
    if grep -qi "$phrase" "$out"; then
      echo "evidence_ok url=$url phrase='$phrase' sha256=$(sha256sum "$out" | awk '{print $1}')"
    else
      echo "WARNING evidence fetched but the phrase '$phrase' was not found; review $out"
    fi
  else
    rm -f "$out.part"
    echo "WARNING evidence_unavailable url=$url (transport failure); rights rest on the manifest citation"
  fi
}
fetch_evidence "$TRACE_POLICY_URL" "$DOWNLOAD_DIR/evidence/trace_dapolicy.htm" "equally available to everyone"
fetch_evidence "$SMD_URL" "$DOWNLOAD_DIR/evidence/nasa_smd_science_information_policy.html" "public trust"

# Liveness: one-byte range GET on the first pinned object.
first_key="$(awk -F'\t' 'NR==2 {print $2}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$BUCKET_URL/$first_key"
echo "liveness_ok key=$first_key"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'filename\tsize_bytes\tmd5_etag\tsha256\n' > "$plan.part"
count=0
bytes=0
fetched=0
while IFS='|' read -r filename key size_bytes md5; do
  target="$FITS_DIR/$filename"
  sha=""
  if [[ -s "$target" ]]; then
    if [[ "$(stat -c %s "$target")" != "$size_bytes" ]] \
      || ! sha="$(python3 "$CHECK" "$target" "$SOURCES" "$filename" </dev/null)"; then
      echo "stale_or_invalid_cache file=$filename; refetching"
      rm -f "$target"
    fi
  fi
  if [[ ! -s "$target" ]]; then
    if [[ -s "$target.part" ]] && (( $(stat -c %s "$target.part") > size_bytes )); then
      rm -f "$target.part"
    fi
    # A .part that already has the pinned size is validated as-is (resuming would 416).
    if [[ ! -s "$target.part" ]] || (( $(stat -c %s "$target.part") < size_bytes )); then
      curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --max-filesize 3000000 \
        --user-agent "$UA" --output "$target.part" "$BUCKET_URL/$key" </dev/null
    fi
    actual="$(stat -c %s "$target.part")"
    if [[ "$actual" != "$size_bytes" ]]; then
      echo "FATAL size mismatch file=$filename expected=$size_bytes actual=$actual" >&2
      rm -f "$target.part"
      exit 1
    fi
    if ! sha="$(python3 "$CHECK" "$target.part" "$SOURCES" "$filename" </dev/null)"; then
      echo "FATAL semantic validation failed file=$filename" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
    fetched=$((fetched + 1))
    echo "fetched file=$filename md5=$md5 sha256=$sha"
  fi
  printf '%s\t%s\t%s\t%s\n' "$filename" "$size_bytes" "$md5" "$sha" >> "$plan.part"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2 "|" $3 "|" $4}' "$SOURCES")
mv "$plan.part" "$plan"

# Drop FITS files in this recipe's own download directory that are no longer pinned.
while IFS= read -r stale; do
  echo "removing_unpinned file=$(basename "$stale")"
  rm -f "$stale"
done < <(SOURCES="$SOURCES" FITS_DIR="$FITS_DIR" python3 - <<'PY'
import csv, os
from pathlib import Path
pinned = {r["filename"] for r in csv.DictReader(open(os.environ["SOURCES"], newline=""), delimiter="\t")}
for p in sorted(Path(os.environ["FITS_DIR"]).glob("trac_*.fts*")):
    if p.name.removesuffix(".part") not in pinned:
        print(p)
PY
)

if [[ "$count" != "$EXPECTED_FILES" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL unexpected selection totals files=$count bytes=$bytes (expected $EXPECTED_FILES / $EXPECTED_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_now=$fetched"
