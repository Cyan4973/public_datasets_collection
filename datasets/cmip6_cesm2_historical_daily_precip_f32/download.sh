#!/usr/bin/env bash
# Download the pinned CMIP6 CESM2 historical r1i1p1f1 daily precipitation file
# for 1940-1949 (one NetCDF4 object, 663,390,696 bytes, dataset version
# v20190401) from the anonymous esgf-world S3 bucket, plus the small license and
# provenance documents, and validate them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cmip6_cesm2_historical_daily_precip_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
DOC_DIR="$DOWNLOAD_DIR/docs"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

BUCKET_URL="https://esgf-world.s3.amazonaws.com"
OBJECT_KEY="CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/pr/gn/v20190401/pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc"
FILE_URL="$BUCKET_URL/$OBJECT_KEY"
FILE_NAME="pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc"
FILE_BYTES=663390696
FILE_ETAG="accfa4a438ca6393474430698d9489dd-80"   # S3 multipart ETag, 80 parts of 8 MiB
FILE_SHA256="fce6d860a9e01b259b9534150392681c0766c6e904814737ad9ea657e36addba"
LICENSE_TABLE_URL="https://wcrp-cmip.github.io/CMIP6_CVs/docs/CMIP6_source_id_licenses.html"
TERMS_URL="https://pcmdi.llnl.gov/CMIP6/TermsOfUse/TermsOfUse6-2.html"
REGISTRY_URL="https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/cmip6.yaml"

mkdir -p "$DOWNLOAD_DIR" "$DOC_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_small() {  # url dest max_bytes
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 120 --max-filesize "$3" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. License and provenance evidence (small documents, refreshed every run).
fetch_small "$LICENSE_TABLE_URL" "$DOC_DIR/CMIP6_source_id_licenses.html" 2000000
fetch_small "$TERMS_URL" "$DOC_DIR/TermsOfUse6-2.html" 2000000
fetch_small "$REGISTRY_URL" "$DOC_DIR/cmip6.yaml" 200000
python3 -I - "$DOC_DIR" <<'PY'
import html
import re
import sys
from pathlib import Path

doc = Path(sys.argv[1])


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


table = doc.joinpath("CMIP6_source_id_licenses.html").read_text(encoding="utf-8", errors="replace")
rows = []
for row in re.split(r"<tr[ >]", table):
    cells = [text_of(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
    if cells and cells[0] == "CESM2":
        rows.append(cells)
if len(rows) != 1:
    raise SystemExit(f"license table holds {len(rows)} rows for source_id CESM2, expected 1")
cells = rows[0]
if cells[1] != "NCAR" or "CC BY 4.0" not in cells:
    raise SystemExit(f"CESM2 license row unexpected: {cells}")
if not any("relaxed to CC BY 4.0" in c for c in cells):
    raise SystemExit(f"CESM2 license row lacks the relaxation history: {cells}")
history = [c for c in cells if "relaxed to CC BY 4.0" in c][0]
terms = text_of(doc.joinpath("TermsOfUse6-2.html").read_text(encoding="utf-8", errors="replace"))
for needle in ("Creative Commons Attribution 4.0 International", "relaxed in October 2022"):
    if needle not in terms:
        raise SystemExit(f"CMIP6 Terms of Use page no longer contains {needle!r}")
yaml = doc.joinpath("cmip6.yaml").read_text(encoding="utf-8")
for needle in ("Name: Coupled Model Intercomparison Project 6", "ARN: arn:aws:s3:::esgf-world"):
    if needle not in yaml:
        raise SystemExit(f"AWS registry YAML no longer contains {needle!r}")
print(f"docs_validation=ok cesm2_license={cells[cells.index('CC BY 4.0')]!r} history={history!r}")
PY

# 2. The object must still have the pinned size and ETag.
headers="$(curl --fail --silent --show-error --location --head --max-time 60 --retry 5 --retry-all-errors "$FILE_URL")"
remote_len="$(printf '%s\n' "$headers" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
remote_etag="$(printf '%s\n' "$headers" | tr -d '\r' | awk 'tolower($1)=="etag:"{v=$2} END{print v}' | tr -d '"')"
if [ "$remote_len" != "$FILE_BYTES" ] || [ "$remote_etag" != "$FILE_ETAG" ]; then
  echo "FATAL: remote object changed: length=$remote_len etag=$remote_etag (pinned $FILE_BYTES $FILE_ETAG)" >&2
  exit 1
fi
echo "remote_head=ok length=$remote_len etag=$remote_etag"

validate_file() {  # path
  python3 -I - "$1" "$FILE_BYTES" "$FILE_ETAG" "$FILE_SHA256" <<'PY'
import hashlib
import sys
from pathlib import Path

path, size, etag, sha_pin = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
if path.stat().st_size != size:
    raise SystemExit(f"size {path.stat().st_size} != {size}")
part = 8 * 1024 * 1024
sha = hashlib.sha256()
digests = []
with path.open("rb") as fh:
    first = True
    while block := fh.read(part):
        if first and block[:8] != b"\x89HDF\r\n\x1a\n":
            raise SystemExit("payload lacks the HDF5 signature")
        first = False
        sha.update(block)
        digests.append(hashlib.md5(block).digest())
multipart = f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}"
if multipart != etag:
    raise SystemExit(f"multipart MD5 {multipart} != pinned ETag {etag}")
if sha_pin and sha.hexdigest() != sha_pin:
    raise SystemExit(f"sha256 {sha.hexdigest()} != pinned {sha_pin}")
print(f"file_validation=ok bytes={size} etag={multipart} sha256={sha.hexdigest()}")
PY
}

# 3. The NetCDF file: resumable, stall-bounded transfer into a .part file.
target="$DOWNLOAD_DIR/$FILE_NAME"
if [ -f "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  validate_file "$target"
  echo "cache_hit $target"
else
  rm -f "$target"
  part="$target.part"
  if [ -f "$part" ] && [ "$(stat -c %s "$part")" -gt "$FILE_BYTES" ]; then
    rm -f "$part"
  fi
  for attempt in 1 2 3 4 5 6; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    [ "$have" = "$FILE_BYTES" ] && break
    echo "transfer attempt=$attempt resume_from=$have"
    if curl --fail --location --show-error --silent -C - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --output "$part" "$FILE_URL"; then
      break
    fi
    sleep 10
  done
  if [ ! -f "$part" ] || [ "$(stat -c %s "$part")" != "$FILE_BYTES" ]; then
    echo "FATAL: transfer incomplete ($(stat -c %s "$part" 2>/dev/null || echo 0) of $FILE_BYTES bytes)" >&2
    exit 1
  fi
  if ! validate_file "$part"; then
    echo "FATAL: downloaded payload failed validation; removing it" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
fi

# 4. Semantic check: the file must decode as the expected CESM2 pr variable
#    (attributes, datatype, chunk layout, complete chunk index, time axis,
#    coordinates, and two decoded daily fields free of fill/NaN).
python3 -I "$RECIPE_DIR/scripts/cesm2_pr.py" check-source --source "$target"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
