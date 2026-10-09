#!/usr/bin/env bash
# Download the pinned GEOS-Chem 14.7.0 fullchem 4x5 restart file (one object,
# 589,309,764 bytes) from the geos-chem AWS Open Data bucket, plus the small
# license/provenance documents, and validate them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="geoschem_gc1470_fullchem_restart_species_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
DOC_DIR="$DOWNLOAD_DIR/docs"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

BUCKET_URL="https://geos-chem.s3.amazonaws.com"
OBJECT_KEY="GEOSCHEM_RESTARTS/GC_14.7.0/GEOSChem.Restart.fullchem.20190101_0000z.nc4"
FILE_URL="$BUCKET_URL/$OBJECT_KEY"
FILE_NAME="GEOSChem.Restart.fullchem.20190101_0000z.nc4"
FILE_BYTES=589309764
FILE_ETAG="b0aa35c196ae37c34af5b0478b818072-71"   # S3 multipart ETag, 71 parts of 8 MiB
FILE_SHA256="f13333b8cdc504fca1621ce3021a71d508633fd26e5e073bb14d882dd7d2ab2e"
README_URL="$BUCKET_URL/GEOSCHEM_RESTARTS/GC_14.7.0/README"
REGISTRY_URL="https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/geoschem-input-data.yaml"
LICENSE_URL="https://geoschem.github.io/license.html"

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
fetch_small "$REGISTRY_URL" "$DOC_DIR/geoschem-input-data.yaml" 200000
fetch_small "$LICENSE_URL" "$DOC_DIR/license.html" 2000000
fetch_small "$README_URL" "$DOC_DIR/GC_14.7.0_README.txt" 200000
python3 -I - "$DOC_DIR" <<'PY'
import html
import re
import sys
from pathlib import Path

doc = Path(sys.argv[1])
yaml = doc.joinpath("geoschem-input-data.yaml").read_text(encoding="utf-8")
for needle in ("Name: GEOS-Chem Input Data", "License: https://geoschem.github.io/license.html",
               "ARN: arn:aws:s3:::geos-chem", "initial conditions"):
    if needle not in yaml:
        raise SystemExit(f"registry YAML no longer contains {needle!r}")
page = doc.joinpath("license.html").read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
sentence = 'GEOS-Chem, including developments, is distributed under the MIT "Expat" public license.'
if sentence not in text:
    raise SystemExit("license page no longer contains the MIT Expat sentence")
readme = doc.joinpath("GC_14.7.0_README.txt").read_text(encoding="utf-8", errors="replace")
if "1-year benchmark" not in readme or "fullchem" not in readme or "14.7.0-rc.0" not in readme:
    raise SystemExit("GC_14.7.0 README no longer describes the fullchem 1-year benchmark restarts")
print("docs_validation=ok registry_license=https://geoschem.github.io/license.html license=MIT-Expat")
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

# 3. The restart file: resumable, stall-bounded transfer into a .part file.
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

echo "[$(date -Is)] download done dataset=$DATASET_ID"
