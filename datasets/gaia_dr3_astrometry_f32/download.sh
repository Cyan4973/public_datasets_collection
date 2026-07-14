#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gaia_dr3_astrometry_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# ESA Gaia DR3 bulk gaia_source CSV files. Source path is resolved by discovery
# (checksum manifest, then autoindex HTML) so we do not hard-code drifting file
# names; both can be overridden.
BASE_URL="${GAIA_BASE_URL:-https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/}"
case "$BASE_URL" in */) ;; *) BASE_URL="$BASE_URL/";; esac
MAX_FILES="${GAIA_MAX_FILES:-2}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
SEL="$DOWNLOAD_DIR/selected_urls.txt"
: > "$SEL"

PARSE_NAMES='
import sys, re
base, maxf = sys.argv[1], int(sys.argv[2])
seen=set(); names=[]
for line in sys.stdin:
    for m in re.findall(r"GaiaSource[A-Za-z0-9_\-]*\.csv\.gz", line):
        if m not in seen:
            seen.add(m); names.append(m)
for n in sorted(names)[:maxf]:
    print(base + n)
'

if [ -n "${GAIA_CSV_URLS_FILE:-}" ]; then
  echo "using GAIA_CSV_URLS_FILE=$GAIA_CSV_URLS_FILE"
  grep -E 'https?://.*\.csv\.gz' "$GAIA_CSV_URLS_FILE" | head -n "$MAX_FILES" > "$SEL" || true
elif [ -n "${GAIA_CSV_URL:-}" ]; then
  echo "using GAIA_CSV_URL=$GAIA_CSV_URL"
  echo "$GAIA_CSV_URL" > "$SEL"
else
  # 1) checksum-manifest discovery (plain text listing of all file names)
  for cf in _MD5SUM.txt MD5SUM.txt md5sum.txt _checksums.txt; do
    if curl --globoff -fsSL --max-time 180 -A "$UA" "${BASE_URL}${cf}" -o "$DOWNLOAD_DIR/listing.txt" 2>/dev/null; then
      python3 -c "$PARSE_NAMES" "$BASE_URL" "$MAX_FILES" < "$DOWNLOAD_DIR/listing.txt" > "$SEL" || true
      if [ -s "$SEL" ]; then echo "discovered via ${cf}"; break; fi
    fi
  done
  # 2) autoindex HTML discovery
  if [ ! -s "$SEL" ]; then
    if curl --globoff -fsSL --max-time 180 -A "$UA" "$BASE_URL" -o "$DOWNLOAD_DIR/listing.html" 2>/dev/null; then
      python3 -c "$PARSE_NAMES" "$BASE_URL" "$MAX_FILES" < "$DOWNLOAD_DIR/listing.html" > "$SEL" || true
      [ -s "$SEL" ] && echo "discovered via autoindex html"
    fi
  fi
fi

if [ ! -s "$SEL" ]; then
  echo "ERROR: could not discover Gaia gaia_source files under $BASE_URL" >&2
  echo "Set GAIA_BASE_URL to the correct directory, or provide GAIA_CSV_URL=<direct .csv.gz url>" >&2
  echo "or GAIA_CSV_URLS_FILE=<file listing .csv.gz urls>." >&2
  exit 1
fi

echo "selected files ($(wc -l < "$SEL")):"; cat "$SEL"

while IFS= read -r url; do
  [ -z "$url" ] && continue
  fn="$(basename "$url")"
  out="$DOWNLOAD_DIR/$fn"
  echo "downloading $url"
  # resumable, stall-based (files are large; no hard timeout)
  curl -fL -C - --retry 5 --retry-delay 5 --speed-limit 1024 --speed-time 60 \
    -A "$UA" -o "$out" "$url"
  # reject semantically invalid payloads: must gunzip and carry the expected columns
  python3 - "$out" <<'PY'
import gzip, sys
p = sys.argv[1]
need = {"source_id", "parallax", "pmra", "pmdec"}
with gzip.open(p, "rt", encoding="utf-8", errors="strict") as fh:
    header = None
    for line in fh:
        if line.startswith("#"):
            continue
        header = line.strip()
        break
    if not header:
        raise SystemExit(f"{p}: no header line")
    cols = {h.strip() for h in header.split(",")}
    missing = need - cols
    if missing:
        raise SystemExit(f"{p}: missing expected columns {sorted(missing)} (got {len(cols)} cols)")
print(f"validated {p}: header ok, {len(cols)} columns")
PY
done < "$SEL"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
