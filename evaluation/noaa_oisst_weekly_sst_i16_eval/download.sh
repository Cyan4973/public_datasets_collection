#!/usr/bin/env bash
# Acquire one pinned NOAA OISST source into evaluation-only storage.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_oisst_weekly_sst_i16_eval"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
DOWNLOAD_DIR="$EVAL_ROOT/downloads"
RIGHTS_DIR="$EVAL_ROOT/rights"
LOG_DIR="$EVAL_ROOT/logs"
RIGHTS_URL="https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00844"

mkdir -p "$DOWNLOAD_DIR" "$RIGHTS_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] evaluation download start dataset=$DATASET_ID"

rights="$RIGHTS_DIR/ncei_iso_c00844.html"
curl --fail --show-error --location --retry 3 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 \
  --user-agent "openzl-evaluation-noaa-oisst/1.0" \
  --output "$rights.part" "$RIGHTS_URL"
mv "$rights.part" "$rights"
python3 - "$rights" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
required = (
    r"NOAA Optimum Interpolation.*Sea Surface Temperature.*Version 2",
    r"doi:10\.7289/V5SQ8XB5",
    r"Use Constraints",
    r"See the Use Agreement for this CDR",
)
for pattern in required:
    if not re.search(pattern, text, re.I | re.S):
        raise SystemExit(f"official NCEI rights metadata lacks expected evidence: {pattern}")
print("validated exact OISST V2 rights metadata; training rights remain unclear")
PY

IFS=$'\t' read -r name size_bytes etag last_modified sha256 _aggregate_output_sha256 url < <(tail -n +2 "$RECIPE_DIR/selection.tsv")
target="$DOWNLOAD_DIR/$name"
if [[ -f "$target" \
   && "$(stat -c %s "$target")" == "$size_bytes" \
   && "$(sha256sum "$target" | awk '{print $1}')" == "$sha256" ]]; then
  echo "using existing source name=$name bytes=$size_bytes"
else
  partial="$target.part"
  if [[ -f "$partial" && "$(stat -c %s "$partial")" -gt "$size_bytes" ]]; then
    rm -f "$partial"
  fi
  current_bytes=0
  [[ -f "$partial" ]] && current_bytes="$(stat -c %s "$partial")"
  echo "fetch source name=$name bytes=$size_bytes resume_from=$current_bytes"
  curl --fail --show-error --location --retry 5 --retry-all-errors \
    --retry-delay 3 --connect-timeout 30 --max-time 7200 \
    --continue-at - --header "If-Match: \"$etag\"" \
    --user-agent "openzl-evaluation-noaa-oisst/1.0" \
    --output "$partial" "$url"
  if [[ "$(stat -c %s "$partial")" != "$size_bytes" ]]; then
    echo "source size mismatch after download" >&2
    exit 1
  fi
  if [[ "$(sha256sum "$partial" | awk '{print $1}')" != "$sha256" ]]; then
    echo "source SHA-256 mismatch after download" >&2
    exit 1
  fi
  mv "$partial" "$target"
fi

export DATASET_ID EVAL_ROOT RIGHTS_URL TARGET="$target" URL="$url" ETAG="$etag" EXPECTED_SHA256="$sha256"
export SIZE_BYTES="$size_bytes" LAST_MODIFIED="$last_modified"
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


target = Path(os.environ["TARGET"])
digest = hashlib.sha256()
with target.open("rb") as handle:
    while chunk := handle.read(8 * 1024 * 1024):
        digest.update(chunk)
record = {
    "dataset_id": os.environ["DATASET_ID"],
    "intended_use": "evaluation_only",
    "training_eligible": False,
    "redistribution_authorized": False,
    "rights_status": "unclear",
    "name": target.name,
    "url": os.environ["URL"],
    "size_bytes": int(os.environ["SIZE_BYTES"]),
    "discovery_etag": f'"{os.environ["ETAG"]}"',
    "discovery_last_modified": os.environ["LAST_MODIFIED"],
    "sha256": digest.hexdigest(),
    "rights_metadata_url": os.environ["RIGHTS_URL"],
}
if record["sha256"] != os.environ["EXPECTED_SHA256"]:
    raise SystemExit("pinned source SHA-256 mismatch")
(Path(os.environ["EVAL_ROOT"]) / "acquisition.json").write_text(
    json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"source_sha256={record['sha256']}")
PY

echo "[$(date -Is)] evaluation download done dataset=$DATASET_ID"
