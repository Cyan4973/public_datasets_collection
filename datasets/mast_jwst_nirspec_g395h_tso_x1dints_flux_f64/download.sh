#!/usr/bin/env bash
# Fetch only the FLUX column of the EXTRACT1D table of the 66 pinned JWST NIRSpec BOTS
# G395H/NRS1 seg001 x1dints products listed in sources.tsv, using HTTP Range requests against
# the anonymous MAST download endpoint:
#   1. sparse header walk (57,600-byte range pieces) up to the EXTRACT1D header; the layout,
#      FLUX column offset and units are parsed from the TTYPEn/TFORMn/TUNITn cards
#   2. one multi-range request per batch of <= 150 integrations (one range per table row,
#      exactly the 8*nbins FLUX bytes), answered as 206 multipart/byteranges
#   3. every part is checked against the plan (offset, length, ETag, total size) and the
#      FLUX rows are concatenated as big-endian float64 into flux/<stem>.flux.be
# Whole-file downloads are never made: --max-filesize aborts any response larger than the
# requested ranges (a server that ignored Range would answer 200 with the full 20-270 MB file).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mast_jwst_nirspec_g395h_tso_x1dints_flux_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
HDR_DIR="$DOWNLOAD_DIR/headers"
LAYOUT_DIR="$DOWNLOAD_DIR/layouts"
FLUX_DIR="$DOWNLOAD_DIR/flux"
WORK_DIR="$DOWNLOAD_DIR/work"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
X1D="$RECIPE_DIR/scripts/x1dints.py"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
EXPECTED_FILES=66
MAX_TOTAL_FLUX_BYTES=600000000
BATCH_ROWS=150
EVIDENCE_URL="https://archive.stsci.edu/publishing/data-use"
UA="openzl-public-datasets-jwst-nirspec-x1dints/1.0"

mkdir -p "$HDR_DIR" "$LAYOUT_DIR" "$FLUX_DIR" "$WORK_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 -I "$RECIPE_DIR/scripts/selftest.py"

# Rights evidence (best effort: a transport failure warns, a changed page is fatal).
evidence="$DOWNLOAD_DIR/evidence/mast_data_use.html"
if curl --fail --silent --show-error --location --retry 3 --retry-delay 3 \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
  --output "$evidence.part" "$EVIDENCE_URL"; then
  mv "$evidence.part" "$evidence"
  python3 -I "$CHECK" evidence "$evidence"
else
  rm -f "$evidence.part"
  echo "WARNING evidence_unavailable url=$EVIDENCE_URL (transport failure); rights rest on the README citation"
fi

# Liveness: one-byte range GET on the first pinned product.
first_url="$(awk -F'\t' 'NR==2 {print $2}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

fetch_headers() {  # $1 = filename, $2 = url
  local dir="$HDR_DIR/$1" verdict start end i
  rm -rf "$dir"
  mkdir -p "$dir"
  for i in $(seq 1 12); do
    read -r verdict start end < <(python3 -I "$X1D" next-header "$dir")
    if [[ "$verdict" == "DONE" ]]; then
      return 0
    fi
    curl --fail --silent --show-error --location --retry 8 --retry-delay 15 --retry-all-errors \
      --max-time 300 --max-filesize 200000 --range "$start-$end" --user-agent "$UA" \
      --dump-header "$dir/$start.http" --output "$dir/$start.bin" "$2" </dev/null
  done
  echo "FATAL header walk did not reach EXTRACT1D for $1" >&2
  return 1
}

fetch_file() {  # $1 = filename, $2 = url; returns 4 if the product changed mid-download
  local filename="$1" url="$2" stem="${1%.fits}"
  local work="$WORK_DIR/$stem" layout="$LAYOUT_DIR/$stem.json" final="$FLUX_DIR/$stem.flux.be"
  local status etag size k row0 row1 spec nbins maxbytes try rc nbatch
  fetch_headers "$filename" "$url"
  read -r status etag size < <(python3 -I "$CHECK" header "$HDR_DIR/$filename" "$SOURCES" "$filename" "$layout")
  [[ -n "${status:-}" ]] || { echo "FATAL header check failed for $filename" >&2; return 1; }
  mkdir -p "$work"
  if [[ -f "$work/etag" && "$(cat "$work/etag")" != "$etag" ]]; then
    echo "discarding partial batches of $filename (ETag changed)"
    rm -f "$work"/b*.be
  fi
  printf '%s\n' "$etag" > "$work/etag"
  python3 -I "$X1D" ranges "$layout" "$BATCH_ROWS" > "$work/ranges.txt"
  nbins="$(python3 -I -c 'import json,sys; c=[c for c in json.load(open(sys.argv[1]))["extract1d"]["columns"] if c["name"]=="FLUX"][0]; print(c["repeat"])' "$layout")"
  nbatch=0
  while read -r k row0 row1 spec; do
    nbatch=$((nbatch + 1))
    [[ -s "$work/b$k.be" ]] && continue
    maxbytes=$(( (row1 - row0) * (8 * nbins + 256) + 8192 ))
    rc=1
    for try in 1 2 3 4 5; do
      if curl --fail --silent --show-error --location --retry 8 --retry-delay 15 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --max-filesize "$maxbytes" \
        --range "$spec" --user-agent "$UA" \
        --dump-header "$work/b$k.http" --output "$work/b$k.body" "$url" </dev/null; then
        set +e
        python3 -I "$X1D" ingest "$layout" "$k" "$row0" "$row1" "$work/b$k.http" "$work/b$k.body" \
          "$work/b$k.be" "$etag" "$size"
        rc=$?
        set -e
      else
        rc=1
      fi
      rm -f "$work/b$k.body"
      [[ "$rc" == 0 || "$rc" == 4 ]] && break
      echo "retrying batch=$k of $filename (attempt $try rc=$rc)"
      sleep $((try * 20))
    done
    rm -f "$work/b$k.http"
    [[ "$rc" == 4 ]] && return 4
    [[ "$rc" == 0 ]] || { echo "FATAL batch $k of $filename failed" >&2; return 1; }
  done < "$work/ranges.txt"
  : > "$final.part"
  for k in $(seq 0 $((nbatch - 1))); do
    cat "$work/b$k.be" >> "$final.part"
  done
  mv "$final.part" "$final"
  rm -rf "$work"
  echo "fetched file=$filename status=$status etag=$etag batches=$nbatch flux_bytes=$(stat -c %s "$final")"
}

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'filename\tstatus\tetag\tsize_bytes\tcal_ver\tcrds_ctx\tsdp_ver\tnaxis2\tnbins\tflux_bytes\tsha256\n' > "$plan.part"
count=0
total=0
reprocessed=0
while IFS='|' read -r filename url; do
  stem="${filename%.fits}"
  final="$FLUX_DIR/$stem.flux.be"
  layout="$LAYOUT_DIR/$stem.json"
  sha=""
  if [[ -s "$final" && -s "$layout" ]]; then
    if sha="$(python3 -I "$CHECK" flux "$layout" "$final" </dev/null)"; then
      echo "cached file=$filename sha256=$sha"
    else
      echo "invalid cached flux for $filename; refetching"
      rm -f "$final"
      sha=""
    fi
  fi
  if [[ -z "$sha" ]]; then
    rc=1
    for attempt in 1 2 3; do
      # Subshell with errexit so any failing step inside fetch_file aborts it with its status.
      set +e
      (set -e; fetch_file "$filename" "$url")
      rc=$?
      set -e
      [[ "$rc" == 0 ]] && break
      [[ "$rc" == 4 ]] || { echo "FATAL could not fetch $filename" >&2; exit 1; }
      echo "product $filename changed during download; re-walking headers (attempt $attempt)"
    done
    [[ "$rc" == 0 ]] || { echo "FATAL $filename kept changing during download" >&2; exit 1; }
    if ! sha="$(python3 -I "$CHECK" flux "$layout" "$final" </dev/null)"; then
      echo "FATAL FLUX payload validation failed for $filename" >&2
      rm -f "$final"
      exit 1
    fi
  fi
  python3 -I - "$layout" "$filename" "$sha" >> "$plan.part" <<'PY'
import json, sys
lay = json.load(open(sys.argv[1]))
p, e, r = lay["primary"], lay["extract1d"], lay["remote"]
flux = [c for c in e["columns"] if c["name"] == "FLUX"][0]
print("\t".join(str(v) for v in (
    sys.argv[2], r["status"], r["etag"], r["size"], p["CAL_VER"], p["CRDS_CTX"], p["SDP_VER"],
    e["naxis2"], flux["repeat"], 8 * flux["repeat"] * e["naxis2"], sys.argv[3])))
PY
  [[ "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote"]["status"])' "$layout")" == "reprocessed" ]] \
    && reprocessed=$((reprocessed + 1))
  count=$((count + 1))
  total=$((total + $(stat -c %s "$final")))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FILES" ]] || (( total > MAX_TOTAL_FLUX_BYTES )); then
  echo "FATAL unexpected selection totals files=$count flux_bytes=$total (expected $EXPECTED_FILES files, <= $MAX_TOTAL_FLUX_BYTES bytes)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count flux_bytes=$total reprocessed_since_discovery=$reprocessed"
