#!/usr/bin/env bash
# Acquire ten exact CC0 native-int16 BOLD NIfTI objects selected by discovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="openneuro_ds000030_fmri_bold_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
VOLUME_DIR="$DOWNLOAD_DIR/volumes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
DESCRIPTION="$DOWNLOAD_DIR/dataset_description.json"
REUSE_DESCRIPTION="$REPO_ROOT/$DATA_DIR/downloads/openneuro_ds000030_t1w_mri_f32/dataset_description.json"

mkdir -p "$VOLUME_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

if [[ -f "$REUSE_DESCRIPTION" ]]; then
  cp --reflink=auto "$REUSE_DESCRIPTION" "$DESCRIPTION"
else
  curl --fail --show-error --location --retry 3 --retry-all-errors \
    --max-time 180 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets-openneuro-bold/1.0" \
    --output "$DESCRIPTION.part" "$BASE_URL/ds000030/dataset_description.json"
  mv "$DESCRIPTION.part" "$DESCRIPTION"
fi

python3 - "$DESCRIPTION" <<'PY'
import json
import sys
from pathlib import Path

description = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if description.get("License") != "CC0":
    raise SystemExit(f"expected License=CC0, found {description.get('License')!r}")
if description.get("DatasetDOI") != "10.18112/openneuro.ds000030.v1.0.0":
    raise SystemExit(f"unexpected dataset DOI: {description.get('DatasetDOI')!r}")
print(f"license={description['License']} doi={description['DatasetDOI']}")
PY

valid_file() {
  local path="$1"
  local expected_size="$2"
  local expected_md5="$3"
  local expected_sha256="$4"
  [[ -f "$path" ]] \
    && [[ "$(stat -c %s "$path")" == "$expected_size" ]] \
    && [[ "$(md5sum "$path" | awk '{print $1}')" == "$expected_md5" ]] \
    && [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_sha256" ]]
}

downloaded=0
compressed_bytes=0
decoded_bytes=0
while IFS=$'\t' read -r key size_bytes md5 sha256 _payload_sha256 subject task _shape _value_count output_bytes; do
  [[ "$key" == "key" ]] && continue
  [[ -n "$key" ]] || continue
  name="${key##*/}"
  target="$VOLUME_DIR/$name"
  if valid_file "$target" "$size_bytes" "$md5" "$sha256"; then
    echo "validated existing name=$name bytes=$size_bytes"
  else
    rm -f "$target.part"
    echo "fetch subject=$subject task=$task name=$name bytes=$size_bytes"
    curl --fail --show-error --location --retry 4 --retry-all-errors \
      --retry-delay 2 --max-time 1800 --max-filesize "$size_bytes" \
      --user-agent "openzl-public-datasets-openneuro-bold/1.0" \
      --output "$target.part" "$BASE_URL/$key"
    if ! valid_file "$target.part" "$size_bytes" "$md5" "$sha256"; then
      echo "size/digest validation failed: $name" >&2
      exit 1
    fi
    mv "$target.part" "$target"
  fi
  downloaded=$((downloaded + 1))
  compressed_bytes=$((compressed_bytes + size_bytes))
  decoded_bytes=$((decoded_bytes + output_bytes))
done < "$RECIPE_DIR/selection.tsv"

if [[ "$downloaded" -ne 10 \
   || "$compressed_bytes" -ne 309475689 \
   || "$decoded_bytes" -ne 514998272 ]]; then
  echo "selection aggregate mismatch files=$downloaded compressed=$compressed_bytes decoded=$decoded_bytes" >&2
  exit 1
fi

export DOWNLOAD_DIR RECIPE_DIR VOLUME_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path


download_dir = Path(os.environ["DOWNLOAD_DIR"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
volume_dir = Path(os.environ["VOLUME_DIR"])
records = []
with (recipe_dir / "selection.tsv").open(newline="") as handle:
    for row in csv.DictReader(handle, delimiter="\t"):
        path = volume_dir / Path(row["key"]).name
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(8 * 1024 * 1024):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        if sha256 != row["sha256"]:
            raise SystemExit(f"source SHA-256 mismatch after acquisition: {path.name}")
        records.append(
            {
                **row,
                "size_bytes": int(row["size_bytes"]),
                "value_count": int(row["value_count"]),
                "decoded_bytes": int(row["decoded_bytes"]),
                "sha256": sha256,
            }
        )
(download_dir / "acquisition.json").write_text(
    json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"validated files={len(records)} compressed_bytes={sum(r['size_bytes'] for r in records)}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
